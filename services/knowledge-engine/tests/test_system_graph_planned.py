from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.schemas.system_graph import (
    GraphEdge,
    GraphNode,
    GraphSnapshot,
    GraphSnapshotContent,
    SourceResult,
    SourceStatus,
)
from app.services.system_graph.canonical import make_edge_id, sha256_value
from app.services.system_graph.planned import project_impact
from app.services.system_graph.snapshots import write_snapshot


def _snapshot(*, success: bool, include_edge: bool = True, commit: str = "a" * 40) -> GraphSnapshot:
    source = "fixture.collector"
    left = GraphNode(id="page:/fixture", kind="page", key="/fixture", label="Fixture")
    right = GraphNode(id="api:GET:/fixture", kind="api", key="GET:/fixture", label="Fixture API")
    edge = GraphEdge(
        id=make_edge_id("calls", left.id, right.id),
        relation="calls",
        source=left.id,
        target=right.id,
        sources=[source],
    )
    content = GraphSnapshotContent(
        commit=commit,
        definition_revision="sha256:" + "b" * 64,
        collector_versions={source: "1"},
        feature_ids=["fixture"],
        source_results=[
            SourceResult(
                collector_id=source,
                version="1",
                status=SourceStatus.SUCCESS if success else SourceStatus.UNKNOWN,
                reason_code="" if success else "collector_timeout",
                retryable=not success,
            )
        ],
        nodes=[left, right],
        edges=[edge] if include_edge else [],
    )
    digest = sha256_value(content.model_dump(mode="json"))
    return GraphSnapshot(
        snapshot_id=digest,
        content_hash=digest,
        generated_at_utc=datetime.now(timezone.utc),
        content=content,
    )


def _impact() -> dict:
    return {
        "change_id": "fixture-s4",
        "planned_changes": [
            {
                "node_id": "service:fixture.query",
                "action": "add",
                "paths": ["services/knowledge-engine/app/services/fixture.py"],
            }
        ],
        "graph_acceptance": {
            "required_edges": [
                {"from": "page:/fixture", "to": "api:GET:/fixture", "relation": "calls"},
                {"from": "api:GET:/fixture", "to": "service:fixture.query", "relation": "calls"},
            ]
        },
    }


def test_planned_fact_only_turns_present_required_edge_into_fact() -> None:
    report = project_impact(_impact(), _snapshot(success=True))
    states = [item.state.value for item in report.required_edges]
    assert states == ["present", "missing"]
    assert {item.node_id for item in report.planned_nodes} >= {
        "page:/fixture",
        "api:GET:/fixture",
        "service:fixture.query",
    }
    issue = report.issues[0]
    assert issue.code == "required_edge_missing"
    assert issue.severity == "warning"
    assert issue.classification.value == "observed_fact"
    assert issue.impact_paths == ["services/knowledge-engine/app/services/fixture.py"]


def test_unknown_collector_never_reports_missing_or_blocking() -> None:
    report = project_impact(
        _impact(), _snapshot(success=False), selected_block_codes=["required_edge_missing"]
    )
    assert [item.state.value for item in report.required_edges] == ["present", "unknown"]
    assert report.issues[0].code == "required_edge_unknown"
    assert report.issues[0].severity == "unknown"
    assert report.selected_blocking == []


def test_repair_card_fingerprint_is_stable_and_block_is_explicit() -> None:
    snapshot = _snapshot(success=True)
    first = project_impact(_impact(), snapshot)
    second = project_impact(_impact(), _snapshot(success=True, commit="c" * 40))
    promoted = project_impact(
        _impact(), snapshot, selected_block_codes=["required_edge_missing"]
    )
    assert first.issues[0].fingerprint == second.issues[0].fingerprint
    assert promoted.issues[0].severity == "blocking"


def test_cli_warning_artifact_is_nonblocking_until_a_code_is_selected(tmp_path: Path, capsys) -> None:
    snapshot_path = write_snapshot(_snapshot(success=True), tmp_path / "snapshots")
    impact_path = tmp_path / "impact.yaml"
    impact_path.write_text(yaml.safe_dump(_impact()), encoding="utf-8")
    output = tmp_path / "warning.json"

    from scripts.system_graph import command_check_contract

    code = command_check_contract(
        argparse.Namespace(
            impact=str(impact_path),
            snapshot=str(snapshot_path),
            output=str(output),
            block_code=[],
            policy=None,
            issue_root=str(tmp_path / "issues"),
        )
    )
    assert code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["issues"][0]["severity"] == "warning"
    assert "::warning title=system-graph::" in capsys.readouterr().out
    assert len(list((tmp_path / "issues").glob("sha256-*.json"))) == 1
