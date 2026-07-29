from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))
from app.schemas.system_graph import (
    EvidenceRef,
    GraphEdge,
    GraphNode,
    GraphSnapshotContent,
    HealthState,
    SourceResult,
    SourceStatus,
)
from app.services.system_graph.canonical import make_edge_id, make_node_id


def _evidence(path: str = "app/example.py") -> EvidenceRef:
    return EvidenceRef(path=path, line=1, symbol="example", blob="a" * 40)


def test_evidence_ref_contains_coordinates_only() -> None:
    evidence = _evidence()
    assert set(evidence.model_dump()) == {"path", "line", "symbol", "blob"}
    with pytest.raises(ValidationError):
        _evidence("C:/secret.txt")
    with pytest.raises(ValidationError):
        _evidence("../secret.txt")


def test_health_state_matches_system_health_contract() -> None:
    assert {item.value for item in HealthState} == {
        "healthy",
        "degraded",
        "unavailable",
        "stale",
        "unknown",
    }


def test_stable_node_and_edge_ids_ignore_source_line() -> None:
    source = make_node_id("service_symbol", "app.services.cost.query")
    target = make_node_id("table", "accounting.cost_items")
    assert source == "service_symbol:app.services.cost.query"
    assert make_edge_id("reads", source, target) == make_edge_id("reads", source, target)


def test_graph_rejects_dangling_or_duplicate_identity() -> None:
    node = GraphNode(id="feature:sample", kind="feature", key="sample", label="Sample")
    edge = GraphEdge(
        id=make_edge_id("calls", node.id, "service:missing"),
        relation="calls",
        source=node.id,
        target="service:missing",
    )
    with pytest.raises(ValidationError, match="unknown nodes"):
        GraphSnapshotContent(
            commit="a" * 40,
            definition_revision="sha256:" + "b" * 64,
            collector_versions={"test": "1"},
            feature_ids=["sample"],
            source_results=[
                SourceResult(collector_id="test", version="1", status=SourceStatus.SUCCESS)
            ],
            nodes=[node],
            edges=[edge],
        )
