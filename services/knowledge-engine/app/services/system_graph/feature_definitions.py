"""Load, validate and atomically project canonical FeatureDefinition YAML."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.services.system_graph.canonical import canonical_json, sha256_value


WorkbenchMode = Literal["work", "development"]
WorkbenchGroup = Literal[
    "today",
    "products",
    "operations",
    "content",
    "knowledge",
    "agents",
    "skills-tools",
    "workflows",
    "prompt-eval",
    "runs-system",
]
WorkbenchPhase = Literal[
    "retain", "merge", "degrade", "host_only", "retirement_candidate"
]

WORK_GROUPS = frozenset({"today", "products", "operations", "content", "knowledge"})
DEVELOPMENT_GROUPS = frozenset(
    {"agents", "skills-tools", "workflows", "prompt-eval", "runs-system"}
)


class DefinitionError(ValueError):
    """A FeatureDefinition set is invalid or its generated projection is stale."""


class DefinitionModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FeatureOwner(DefinitionModel):
    kind: Literal["team", "service", "person"]
    id: str = Field(min_length=1)


class FeatureRoutes(DefinitionModel):
    canonical: str = Field(pattern=r"^/[^?#]*$")
    visible: bool
    placements: list[Literal["sidebar", "home", "onboarding", "direct"]]
    # Additive defaults keep historical/fixture v1 definitions readable. Every
    # canonical repository definition writes this field explicitly and the JSON
    # schema requires it.
    owned_surfaces: list[str] = Field(default_factory=list)

    @field_validator("placements", "owned_surfaces")
    @classmethod
    def route_lists_are_unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("route lists must contain unique values")
        return value

    @field_validator("owned_surfaces")
    @classmethod
    def owned_surfaces_are_routes(cls, value: list[str]) -> list[str]:
        if any(
            not href.startswith("/") or "?" in href or "#" in href for href in value
        ):
            raise ValueError("owned surfaces must be path-only hrefs")
        return value

    @model_validator(mode="after")
    def canonical_is_owned(self) -> "FeatureRoutes":
        if not self.owned_surfaces:
            self.owned_surfaces = [self.canonical]
        elif self.canonical not in self.owned_surfaces:
            raise ValueError("canonical route must be present in owned_surfaces")
        return self


def _validate_mode_group(mode: str, group: str) -> None:
    allowed = WORK_GROUPS if mode == "work" else DEVELOPMENT_GROUPS
    if group not in allowed:
        raise ValueError(f"group {group} is invalid for mode {mode}")


class FeatureContextualGroup(DefinitionModel):
    mode: WorkbenchMode
    group: WorkbenchGroup
    order: int = Field(ge=0)

    @model_validator(mode="after")
    def group_matches_mode(self) -> "FeatureContextualGroup":
        _validate_mode_group(self.mode, self.group)
        return self


class FeatureIA(DefinitionModel):
    # Defaults are only for read compatibility with historical v1 fixtures.
    # Canonical definitions must persist the complete mapping explicitly.
    mode: WorkbenchMode = "work"
    primary_group: WorkbenchGroup = "today"
    primary_order: int = Field(default=0, ge=0)
    contextual_groups: list[FeatureContextualGroup] = Field(default_factory=list)
    phase: WorkbenchPhase = "retain"
    flag: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]*$")

    @model_validator(mode="after")
    def placements_are_valid(self) -> "FeatureIA":
        _validate_mode_group(self.mode, self.primary_group)
        identities = [(item.mode, item.group) for item in self.contextual_groups]
        if len(identities) != len(set(identities)):
            raise ValueError("contextual groups must be unique")
        if (self.mode, self.primary_group) in identities:
            raise ValueError("primary group cannot also be contextual")
        return self


class FeatureCapability(DefinitionModel):
    capability_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]*$")
    kind: Literal["read", "write", "generate", "admin"]


class ExpectedEdge(DefinitionModel):
    source: str = Field(alias="from", pattern=r"^[a-z_]+:.+$")
    target: str = Field(alias="to", pattern=r"^[a-z_]+:.+$")
    relation: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    required: bool


class FeatureCheck(DefinitionModel):
    check_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]*$")
    kind: Literal["pytest", "command", "schema", "health"]
    target: str = Field(min_length=1)
    verifies: str = Field(pattern=r"^[a-z_]+:.+$")
    required: bool


class FeatureAlias(DefinitionModel):
    href: str = Field(pattern=r"^/[^?#]*$")
    target: str = Field(pattern=r"^/[^?#]*$")


class FeatureDependency(DefinitionModel):
    ref: str = Field(pattern=r"^[a-z_]+:.+$")
    required: bool


class FeatureDefinition(DefinitionModel):
    schema_version: Literal[1]
    feature_id: str = Field(pattern=r"^[a-z][a-z0-9-]{2,63}$")
    title: str = Field(min_length=1)
    domain: str = Field(pattern=r"^[a-z][a-z0-9_.-]*$")
    owner: FeatureOwner
    lifecycle: Literal["active", "deprecated", "archived"]
    routes: FeatureRoutes
    ia: FeatureIA = Field(default_factory=FeatureIA)
    capabilities: list[FeatureCapability]
    expected_edges: list[ExpectedEdge]
    checks: list[FeatureCheck]
    aliases: list[FeatureAlias]
    dependencies: list[FeatureDependency]
    source_path: str = Field(exclude=True)
    ia_explicit: bool = Field(default=False, exclude=True)
    owned_surfaces_explicit: bool = Field(default=False, exclude=True)

    @model_validator(mode="after")
    def local_ids_are_unique(self) -> "FeatureDefinition":
        for label, values in (
            ("capability", [item.capability_id for item in self.capabilities]),
            ("check", [item.check_id for item in self.checks]),
            ("alias", [item.href for item in self.aliases]),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"duplicate {label} in {self.feature_id}")
        return self


def definitions_dir(repo: Path) -> Path:
    return repo / "services" / "knowledge-engine" / "config" / "features"


def generated_bundle_path(repo: Path) -> Path:
    return definitions_dir(repo) / "generated" / "features.v1.json"


def frontend_bundle_path(repo: Path) -> Path:
    return repo / "frontend" / "src" / "generated" / "feature-registry.v1.json"


def _workbench_ia_is_required(repo: Path) -> bool:
    schema_path = definitions_dir(repo) / "feature-definition.schema.json"
    if not schema_path.exists():
        return False
    import json

    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        root_required = set(schema.get("required") or [])
        route_required = set(
            schema.get("properties", {}).get("routes", {}).get("required") or []
        )
    except (OSError, ValueError, AttributeError) as exc:
        raise DefinitionError(
            f"cannot read FeatureDefinition schema {schema_path}: {exc.__class__.__name__}"
        ) from exc
    return "ia" in root_required and "owned_surfaces" in route_required


def _validate_routes_and_ia(definitions: list[FeatureDefinition]) -> None:
    canonical_to_feature: dict[str, str] = {}
    owned_to_feature: dict[str, str] = {}
    alias_targets: dict[str, tuple[str, str]] = {}
    group_orders: dict[tuple[str, str, int], str] = {}
    for definition in definitions:
        canonical = definition.routes.canonical
        if canonical in canonical_to_feature:
            previous = canonical_to_feature[canonical]
            raise DefinitionError(
                f"duplicate canonical href {canonical}: "
                f"{previous} and {definition.feature_id}"
            )
        canonical_to_feature[canonical] = definition.feature_id
        for href in definition.routes.owned_surfaces:
            if href in owned_to_feature:
                raise DefinitionError(
                    f"duplicate owned surface {href}: "
                    f"{owned_to_feature[href]} and {definition.feature_id}"
                )
            owned_to_feature[href] = definition.feature_id

        if definition.ia_explicit:
            placements = [
                (
                    definition.ia.mode,
                    definition.ia.primary_group,
                    definition.ia.primary_order,
                ),
                *[
                    (item.mode, item.group, item.order)
                    for item in definition.ia.contextual_groups
                ],
            ]
            for mode, group, order in placements:
                key = (mode, group, order)
                if key in group_orders:
                    raise DefinitionError(
                        f"duplicate IA order {mode}/{group}/{order}: "
                        f"{group_orders[key]} and {definition.feature_id}"
                    )
                group_orders[key] = definition.feature_id

    for definition in definitions:
        for alias in definition.aliases:
            if alias.href in alias_targets:
                raise DefinitionError(
                    f"duplicate alias href {alias.href} in {definition.source_path}"
                )
            if alias.href in owned_to_feature:
                raise DefinitionError(
                    f"alias overlaps owned surface {alias.href}: "
                    f"{owned_to_feature[alias.href]} and {definition.feature_id}"
                )
            if alias.target not in canonical_to_feature:
                raise DefinitionError(
                    f"alias target must be canonical: {alias.href} -> {alias.target}"
                )
            if alias.target != definition.routes.canonical:
                raise DefinitionError(
                    f"alias must target its feature canonical route: "
                    f"{alias.href} -> {alias.target}"
                )
            alias_targets[alias.href] = (alias.target, definition.feature_id)


def discover_frontend_page_routes(repo: Path) -> set[str]:
    app_root = repo / "frontend" / "src" / "app"
    if not app_root.exists():
        return set()
    routes: set[str] = set()
    for path in app_root.rglob("page.tsx"):
        relative = path.parent.relative_to(app_root)
        segments = [
            segment
            for segment in relative.parts
            if not (segment.startswith("(") and segment.endswith(")"))
            and not segment.startswith("@")
        ]
        routes.add("/" + "/".join(segments) if segments else "/")
    return routes


def _validate_frontend_route_partition(
    repo: Path, definitions: list[FeatureDefinition]
) -> None:
    if not all(definition.owned_surfaces_explicit for definition in definitions):
        return
    page_routes = discover_frontend_page_routes(repo)
    if not page_routes:
        return
    owned_routes = {
        href for definition in definitions for href in definition.routes.owned_surfaces
    }
    alias_routes = {
        alias.href for definition in definitions for alias in definition.aliases
    }
    declared_page_routes = owned_routes | (alias_routes & page_routes)
    uncovered = sorted(page_routes - declared_page_routes)
    owned_without_page = sorted(owned_routes - page_routes)
    if uncovered or owned_without_page:
        raise DefinitionError(
            "frontend page route partition mismatch: "
            f"uncovered={uncovered}, owned_without_page={owned_without_page}"
        )


def load_definitions(repo: Path) -> list[FeatureDefinition]:
    root = definitions_dir(repo)
    definitions: list[FeatureDefinition] = []
    for path in sorted(root.glob("*.yaml"), key=lambda item: item.name):
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise DefinitionError(
                f"cannot read {path}: {exc.__class__.__name__}"
            ) from exc
        if not isinstance(raw, dict):
            raise DefinitionError(f"definition must be an object: {path}")
        try:
            definitions.append(
                FeatureDefinition.model_validate(
                    {
                        **raw,
                        "source_path": path.relative_to(repo).as_posix(),
                        "ia_explicit": "ia" in raw,
                        "owned_surfaces_explicit": (
                            isinstance(raw.get("routes"), dict)
                            and "owned_surfaces" in raw["routes"]
                        ),
                    }
                )
            )
        except Exception as exc:
            raise DefinitionError(f"invalid FeatureDefinition {path}: {exc}") from exc

    if not definitions:
        raise DefinitionError(f"no FeatureDefinition YAML found under {root}")
    feature_ids = [definition.feature_id for definition in definitions]
    if len(feature_ids) != len(set(feature_ids)):
        duplicates = sorted(
            {value for value in feature_ids if feature_ids.count(value) > 1}
        )
        raise DefinitionError(f"duplicate feature_id: {duplicates}")
    if _workbench_ia_is_required(repo):
        missing_ia = sorted(
            definition.feature_id
            for definition in definitions
            if not definition.ia_explicit
        )
        missing_surfaces = sorted(
            definition.feature_id
            for definition in definitions
            if not definition.owned_surfaces_explicit
        )
        if missing_ia or missing_surfaces:
            raise DefinitionError(
                "canonical FeatureDefinition is missing W1 fields: "
                f"ia={missing_ia}, owned_surfaces={missing_surfaces}"
            )
    _validate_routes_and_ia(definitions)
    _validate_frontend_route_partition(repo, definitions)
    return definitions


def build_bundle(definitions: list[FeatureDefinition]) -> dict[str, object]:
    source_items = [
        definition.model_dump(mode="json", by_alias=True, exclude={"source_path"})
        for definition in definitions
    ]
    revision = sha256_value(source_items)
    frontend_registry = []
    graph_expectations = []
    for definition in definitions:
        frontend_registry.append(
            {
                "feature_id": definition.feature_id,
                "title": definition.title,
                "domain": definition.domain,
                "href": definition.routes.canonical,
                "visible": definition.routes.visible,
                "placements": sorted(definition.routes.placements),
                "owned_surfaces": sorted(definition.routes.owned_surfaces),
                "owner": definition.owner.model_dump(mode="json"),
                "lifecycle": definition.lifecycle,
                "ia": {
                    **definition.ia.model_dump(
                        mode="json", exclude={"contextual_groups"}
                    ),
                    "contextual_groups": [
                        item.model_dump(mode="json")
                        for item in sorted(
                            definition.ia.contextual_groups,
                            key=lambda item: (item.mode, item.group, item.order),
                        )
                    ],
                },
                "aliases": [
                    alias.model_dump(mode="json")
                    for alias in sorted(definition.aliases, key=lambda item: item.href)
                ],
                "capabilities": [
                    capability.model_dump(mode="json")
                    for capability in sorted(
                        definition.capabilities, key=lambda item: item.capability_id
                    )
                ],
            }
        )
        graph_expectations.append(
            {
                "feature_id": definition.feature_id,
                "expected_edges": [
                    edge.model_dump(mode="json", by_alias=True)
                    for edge in sorted(
                        definition.expected_edges,
                        key=lambda item: (item.source, item.relation, item.target),
                    )
                ],
                "checks": [
                    check.model_dump(mode="json")
                    for check in sorted(
                        definition.checks, key=lambda item: item.check_id
                    )
                ],
                "dependencies": [
                    dependency.model_dump(mode="json")
                    for dependency in sorted(
                        definition.dependencies, key=lambda item: item.ref
                    )
                ],
            }
        )
    return {
        "schema_version": 1,
        "schema_id": "omni.feature-projections.v1",
        "definition_revision": revision,
        "frontend_registry": frontend_registry,
        "graph_expectations": graph_expectations,
    }


def bundle_text(bundle: dict[str, object]) -> str:
    # Pretty output is still deterministic because canonical ordering is explicit.
    import json

    return json.dumps(bundle, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def generate_bundle(repo: Path, *, check: bool = False) -> dict[str, object]:
    definitions = load_definitions(repo)
    bundle = build_bundle(definitions)
    expected = bundle_text(bundle)
    targets = [generated_bundle_path(repo), frontend_bundle_path(repo)]
    if check:
        stale = [
            target
            for target in targets
            if (target.read_text(encoding="utf-8") if target.exists() else "")
            != expected
        ]
        if stale:
            raise DefinitionError(
                "generated FeatureDefinition bundle is stale: "
                + ", ".join(str(target) for target in stale)
            )
        return bundle

    temporary_names: list[tuple[Path, str]] = []
    try:
        for target in targets:
            target.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
            )
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(expected)
                handle.flush()
                os.fsync(handle.fileno())
            temporary_names.append((target, temporary_name))
        for target, temporary_name in temporary_names:
            os.replace(temporary_name, target)
    except Exception:
        try:
            for _, temporary_name in temporary_names:
                Path(temporary_name).unlink(missing_ok=True)
        finally:
            raise
    return bundle


def select_definitions(
    definitions: list[FeatureDefinition], feature_ids: list[str]
) -> list[FeatureDefinition]:
    if not feature_ids:
        return definitions
    by_id = {definition.feature_id: definition for definition in definitions}
    missing = sorted(set(feature_ids) - set(by_id))
    if missing:
        raise DefinitionError(f"unknown feature_id: {missing}")
    return [by_id[feature_id] for feature_id in sorted(set(feature_ids))]


def definition_revision(definitions: list[FeatureDefinition]) -> str:
    return build_bundle(definitions)["definition_revision"]  # type: ignore[return-value]


def canonical_definition_text(definitions: list[FeatureDefinition]) -> str:
    return canonical_json(
        [
            definition.model_dump(mode="json", by_alias=True, exclude={"source_path"})
            for definition in definitions
        ]
    )
