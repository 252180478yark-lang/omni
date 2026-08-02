from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest
import yaml

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.services.system_graph.feature_definitions import (
    DefinitionError,
    build_bundle,
    discover_frontend_page_routes,
    generate_bundle,
    load_definitions,
)
from app.services.health_registry import (
    discover_visible_frontend_feature_ids,
    discover_visible_frontend_hrefs,
)


def _definition(
    feature_id: str = "sample-feature",
    href: str = "/sample",
    aliases: str = "aliases: []",
) -> str:
    return f"""schema_version: 1
feature_id: {feature_id}
title: 示例功能
domain: test
owner:
  kind: team
  id: omni
lifecycle: active
routes:
  canonical: {href}
  visible: true
  placements: [direct]
  owned_surfaces: [{href}]
ia:
  mode: work
  primary_group: today
  primary_order: 0
  contextual_groups: []
  phase: retain
  flag: null
capabilities:
  - capability_id: read
    kind: read
expected_edges: []
checks: []
{aliases}
dependencies: []
"""


def _root(tmp_path: Path) -> Path:
    path = tmp_path / "services" / "knowledge-engine" / "config" / "features"
    path.mkdir(parents=True)
    return path


def test_schema_is_versioned_draft_2020_12() -> None:
    repo = Path(__file__).resolve().parents[3]
    schema = json.loads(
        (
            repo
            / "services/knowledge-engine/config/features/feature-definition.schema.json"
        ).read_text(encoding="utf-8")
    )
    assert schema["$id"] == "omni.feature-definition.v1"
    assert schema["$schema"].endswith("2020-12/schema")
    assert schema["additionalProperties"] is False
    assert "ia" in schema["required"]
    assert "owned_surfaces" in schema["properties"]["routes"]["required"]


def test_utf8_definition_and_projection_are_stable(tmp_path: Path) -> None:
    definitions = _root(tmp_path)
    (definitions / "sample.yaml").write_text(_definition(), encoding="utf-8")
    parsed = load_definitions(tmp_path)
    bundle = build_bundle(parsed)
    assert parsed[0].title == "示例功能"
    assert bundle["frontend_registry"][0]["title"] == "示例功能"  # type: ignore[index]
    first = generate_bundle(tmp_path)
    second = generate_bundle(tmp_path, check=True)
    assert first == second
    backend = definitions / "generated" / "features.v1.json"
    frontend = tmp_path / "frontend/src/generated/feature-registry.v1.json"
    assert backend.read_bytes() == frontend.read_bytes()


def test_duplicate_feature_id_or_href_reports_conflict(tmp_path: Path) -> None:
    definitions = _root(tmp_path)
    (definitions / "a.yaml").write_text(_definition(), encoding="utf-8")
    (definitions / "b.yaml").write_text(
        _definition(feature_id="sample-feature", href="/other"), encoding="utf-8"
    )
    with pytest.raises(DefinitionError, match="duplicate feature_id"):
        load_definitions(tmp_path)

    (definitions / "b.yaml").write_text(
        _definition(feature_id="other-feature", href="/sample"), encoding="utf-8"
    )
    with pytest.raises(DefinitionError, match="duplicate canonical href"):
        load_definitions(tmp_path)


def test_alias_must_target_the_feature_canonical_directly(tmp_path: Path) -> None:
    definitions = _root(tmp_path)
    aliases = """aliases:
  - href: /old-a
    target: /old-b"""
    (definitions / "sample.yaml").write_text(
        _definition(aliases=aliases), encoding="utf-8"
    )
    with pytest.raises(DefinitionError, match="alias target must be canonical"):
        load_definitions(tmp_path)


def test_alias_cannot_overlap_an_owned_surface(tmp_path: Path) -> None:
    definitions = _root(tmp_path)
    aliases = """aliases:
  - href: /sample
    target: /sample"""
    (definitions / "sample.yaml").write_text(
        _definition(aliases=aliases), encoding="utf-8"
    )
    with pytest.raises(DefinitionError, match="alias overlaps owned surface"):
        load_definitions(tmp_path)


def test_duplicate_ia_order_is_rejected(tmp_path: Path) -> None:
    definitions = _root(tmp_path)
    (definitions / "a.yaml").write_text(_definition(), encoding="utf-8")
    (definitions / "b.yaml").write_text(
        _definition(feature_id="other-feature", href="/other"), encoding="utf-8"
    )
    with pytest.raises(DefinitionError, match="duplicate IA order work/today/0"):
        load_definitions(tmp_path)


def test_failed_generation_does_not_replace_previous_bundle(tmp_path: Path) -> None:
    definitions = _root(tmp_path)
    (definitions / "a.yaml").write_text(_definition(), encoding="utf-8")
    generate_bundle(tmp_path)
    generated = definitions / "generated" / "features.v1.json"
    before = generated.read_bytes()
    (definitions / "b.yaml").write_text(
        _definition(feature_id="sample-feature", href="/other"), encoding="utf-8"
    )
    with pytest.raises(DefinitionError):
        generate_bundle(tmp_path)
    assert generated.read_bytes() == before


def test_repository_workbench_ia_and_page_routes_are_exactly_partitioned() -> None:
    repo = Path(__file__).resolve().parents[3]
    definitions = load_definitions(repo)
    by_id = {definition.feature_id: definition for definition in definitions}

    original_ids = {
        "ad-review",
        "approval-inbox",
        "chat",
        "commerce-feedback",
        "content-studio",
        "cost-management",
        "knowledge",
        "knowledge-harvester",
        "livestream-analysis",
        "news",
        "product-management",
        "reverse-engineer",
        "scout-monitoring",
        "sku-pipeline",
        "system-console",
        "system-convergence-runtime-execution",
        "system-convergence-s4-s6",
        "video-analysis",
        "workspace-operations",
    }
    added_ids = {
        "agent-log",
        "playground",
        "prompt-lab",
        "knowledge-evaluation",
        "model-management",
        "task-management",
        "tri-mind",
    }
    assert len(definitions) == 26
    assert set(by_id) == original_ids | added_ids
    assert by_id["sku-pipeline"].title == "SKU 圈包链路"
    assert by_id["sku-pipeline"].routes.canonical == "/sku-pipeline"

    expected_groups = {
        ("work", "today"),
        ("work", "products"),
        ("work", "operations"),
        ("work", "content"),
        ("work", "knowledge"),
        ("development", "agents"),
        ("development", "skills-tools"),
        ("development", "workflows"),
        ("development", "prompt-eval"),
        ("development", "runs-system"),
    }
    grouped: dict[tuple[str, str], list[tuple[int, str]]] = {}
    for definition in definitions:
        raw = yaml.safe_load(
            (repo / definition.source_path).read_text(encoding="utf-8")
        )
        assert "ia" in raw
        assert "owned_surfaces" in raw["routes"]
        grouped.setdefault(
            (definition.ia.mode, definition.ia.primary_group), []
        ).append((definition.ia.primary_order, definition.feature_id))
        for contextual in definition.ia.contextual_groups:
            grouped.setdefault((contextual.mode, contextual.group), []).append(
                (contextual.order, definition.feature_id)
            )

    assert set(grouped) == expected_groups
    assert all(
        len(items) == len({order for order, _ in items}) for items in grouped.values()
    )
    landings = {group: min(items)[1] for group, items in grouped.items()}
    assert landings == {
        ("work", "today"): "workspace-operations",
        ("work", "products"): "product-management",
        ("work", "operations"): "scout-monitoring",
        ("work", "content"): "content-studio",
        ("work", "knowledge"): "knowledge",
        ("development", "agents"): "chat",
        ("development", "skills-tools"): "playground",
        ("development", "workflows"): "sku-pipeline",
        ("development", "prompt-eval"): "prompt-lab",
        ("development", "runs-system"): "system-convergence-runtime-execution",
    }

    page_routes = discover_frontend_page_routes(repo)
    owned_routes = {
        href for definition in definitions for href in definition.routes.owned_surfaces
    }
    aliases = {
        alias.href: alias.target
        for definition in definitions
        for alias in definition.aliases
    }
    assert len(page_routes) == 45
    assert len(owned_routes) == 44
    assert len(aliases) == 2
    assert owned_routes.isdisjoint(aliases)
    page_backed_aliases = set(aliases) & page_routes
    assert owned_routes | page_backed_aliases == page_routes
    assert aliases == {
        "/marketing/review": "/ad-review",
        "/qa": "/chat",
    }
    assert {
        "/ad-review/flywheel",
        "/content-leaderboard",
        "/decisions",
        "/insights",
        "/review",
        "/system-graph",
        "/workspace/development",
    } <= owned_routes
    assert by_id["system-convergence-s4-s6"].routes.canonical == "/system-graph"
    assert by_id["system-convergence-s4-s6"].routes.owned_surfaces == ["/system-graph"]
    assert (
        "/workspace/development" in by_id["workspace-operations"].routes.owned_surfaces
    )

    bundle = build_bundle(definitions)
    projected = bundle["frontend_registry"]
    assert len(projected) == 26  # type: ignore[arg-type]
    assert all("ia" in entry and "owned_surfaces" in entry for entry in projected)  # type: ignore[union-attr]


def test_all_home_quick_tools_are_canonical_visible_definitions() -> None:
    repo = Path(__file__).resolve().parents[3]
    definitions = load_definitions(repo)
    home_registry = {
        definition.feature_id: definition.routes.canonical
        for definition in definitions
        if definition.lifecycle == "active"
        and definition.routes.visible
        and "home" in definition.routes.placements
    }
    assert home_registry == {
        "ad-review": "/ad-review",
        "chat": "/chat",
        "content-studio": "/content-studio",
        "knowledge": "/knowledge",
        "knowledge-harvester": "/knowledge/harvester",
        "livestream-analysis": "/livestream-analysis",
        "news": "/news",
        "video-analysis": "/video-analysis",
    }

    bundle = build_bundle(definitions)
    projected = {
        item["feature_id"]: item["href"]
        for item in bundle["frontend_registry"]  # type: ignore[index]
        if item["visible"] and "home" in item["placements"]
    }
    assert projected == home_registry

    page_source = (repo / "frontend/src/app/page.tsx").read_text(encoding="utf-8")
    presentation = page_source.split("const QUICK_TOOL_PRESENTATION", 1)[1].split(
        "interface Step", 1
    )[0]
    presented_ids = set(re.findall(r"featureId:\s*'([^']+)'", presentation))
    assert presented_ids == set(home_registry)
    assert discover_visible_frontend_feature_ids(repo) == presented_ids
    assert "href:" not in presentation
    assert "label:" not in presentation


def test_sidebar_and_home_visible_hrefs_all_map_to_one_definition() -> None:
    repo = Path(__file__).resolve().parents[3]
    definitions = load_definitions(repo)
    visible_hrefs = discover_visible_frontend_hrefs(repo)
    definition_hrefs = {
        href
        for definition in definitions
        if definition.lifecycle == "active" and definition.routes.visible
        for href in (
            definition.routes.canonical,
            *(alias.href for alias in definition.aliases),
        )
    }
    projected_hrefs = {
        href
        for definition in definitions
        if definition.lifecycle == "active"
        and definition.routes.visible
        and set(definition.routes.placements).intersection(
            {"sidebar", "home", "onboarding"}
        )
        for href in (
            definition.routes.canonical,
            *(alias.href for alias in definition.aliases),
        )
    }
    assert "/workspace" in visible_hrefs
    assert "/sku-pipeline" in visible_hrefs
    assert "/system-graph" not in visible_hrefs
    assert visible_hrefs == projected_hrefs
    assert visible_hrefs <= definition_hrefs
