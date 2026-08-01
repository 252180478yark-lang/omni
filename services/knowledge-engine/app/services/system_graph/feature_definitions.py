"""Load, validate and atomically project canonical FeatureDefinition YAML."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.services.system_graph.canonical import canonical_json, sha256_value


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

    @field_validator("placements")
    @classmethod
    def placements_are_unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("route placements must be unique")
        return value


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
    capabilities: list[FeatureCapability]
    expected_edges: list[ExpectedEdge]
    checks: list[FeatureCheck]
    aliases: list[FeatureAlias]
    dependencies: list[FeatureDependency]
    source_path: str = Field(exclude=True)

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


def _validate_aliases(definitions: list[FeatureDefinition]) -> None:
    canonical_to_feature: dict[str, str] = {}
    alias_targets: dict[str, str] = {}
    for definition in definitions:
        canonical = definition.routes.canonical
        if canonical in canonical_to_feature or canonical in alias_targets:
            previous = canonical_to_feature.get(canonical, "alias")
            raise DefinitionError(
                f"duplicate canonical href {canonical}: "
                f"{previous} and {definition.feature_id}"
            )
        canonical_to_feature[canonical] = definition.feature_id
        for alias in definition.aliases:
            if alias.href in alias_targets or alias.href in canonical_to_feature:
                raise DefinitionError(f"duplicate alias href {alias.href} in {definition.source_path}")
            alias_targets[alias.href] = alias.target

    all_routes = set(canonical_to_feature) | set(alias_targets)
    for href, target in alias_targets.items():
        if target not in all_routes:
            raise DefinitionError(f"alias target does not exist: {href} -> {target}")

    for start in alias_targets:
        seen: set[str] = set()
        current = start
        while current in alias_targets:
            if current in seen:
                chain = " -> ".join([*sorted(seen), current])
                raise DefinitionError(f"alias cycle detected: {chain}")
            seen.add(current)
            current = alias_targets[current]


def load_definitions(repo: Path) -> list[FeatureDefinition]:
    root = definitions_dir(repo)
    definitions: list[FeatureDefinition] = []
    for path in sorted(root.glob("*.yaml"), key=lambda item: item.name):
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise DefinitionError(f"cannot read {path}: {exc.__class__.__name__}") from exc
        if not isinstance(raw, dict):
            raise DefinitionError(f"definition must be an object: {path}")
        try:
            definitions.append(
                FeatureDefinition.model_validate(
                    {**raw, "source_path": path.relative_to(repo).as_posix()}
                )
            )
        except Exception as exc:
            raise DefinitionError(f"invalid FeatureDefinition {path}: {exc}") from exc

    if not definitions:
        raise DefinitionError(f"no FeatureDefinition YAML found under {root}")
    feature_ids = [definition.feature_id for definition in definitions]
    if len(feature_ids) != len(set(feature_ids)):
        duplicates = sorted({value for value in feature_ids if feature_ids.count(value) > 1})
        raise DefinitionError(f"duplicate feature_id: {duplicates}")
    _validate_aliases(definitions)
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
                "owner": definition.owner.model_dump(mode="json"),
                "lifecycle": definition.lifecycle,
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
                    for check in sorted(definition.checks, key=lambda item: item.check_id)
                ],
                "dependencies": [
                    dependency.model_dump(mode="json")
                    for dependency in sorted(definition.dependencies, key=lambda item: item.ref)
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
            target for target in targets
            if (target.read_text(encoding="utf-8") if target.exists() else "") != expected
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
