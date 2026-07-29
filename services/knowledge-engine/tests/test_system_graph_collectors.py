from __future__ import annotations

import sys
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))
from app.schemas.system_graph import SourceStatus
from app.services.system_graph.scanner import ScanRequest, scan_repository


REPO = Path(__file__).resolve().parents[3]


def test_real_cost_feature_has_required_static_chain() -> None:
    snapshot = scan_repository(
        ScanRequest(repo=REPO, feature_ids=("cost-management",), dynamic=False)
    )
    nodes = {node.id for node in snapshot.content.nodes}
    assert {
        "feature:cost-management",
        "ui_route:/cost",
        "bff_operation:GET:/api/omni/cost/cost-items",
        "rest_operation:GET:/api/v1/accounting/cost-items",
        "service_symbol:app.services.accounting_tool.query_costs",
        "mcp_tool:query_costs",
        "migration:015_cost_items",
        "table:accounting.cost_items",
    } <= nodes
    edges = {
        (edge.source, edge.target, edge.relation) for edge in snapshot.content.edges
    }
    assert (
        "ui_route:/cost",
        "bff_operation:GET:/api/omni/cost/cost-items",
        "calls",
    ) in edges
    assert (
        "rest_operation:GET:/api/v1/accounting/cost-items",
        "service_symbol:app.services.accounting_tool.query_costs",
        "invokes",
    ) in edges
    assert (
        "service_symbol:app.services.accounting_tool.query_costs",
        "table:accounting.cost_items",
        "reads",
    ) in edges


def test_dynamic_catalog_failures_are_isolated(monkeypatch) -> None:
    monkeypatch.setenv(
        "OMNI_SYSTEM_GRAPH_FORCE_DYNAMIC_FAILURE",
        "catalog.openapi,catalog.mcp,health.runtime",
    )
    snapshot = scan_repository(
        ScanRequest(repo=REPO, feature_ids=("cost-management",), dynamic=True)
    )
    statuses = {
        result.collector_id: result.status for result in snapshot.content.source_results
    }
    assert statuses["catalog.openapi"] == SourceStatus.UNKNOWN
    assert statuses["catalog.mcp"] == SourceStatus.UNKNOWN
    assert statuses["health.runtime"] == SourceStatus.UNKNOWN
    assert any(node.id == "mcp_tool:query_costs" for node in snapshot.content.nodes)
    assert any(
        node.id == "rest_operation:GET:/api/v1/accounting/cost-items"
        for node in snapshot.content.nodes
    )


def test_static_nodes_do_not_claim_health() -> None:
    snapshot = scan_repository(
        ScanRequest(repo=REPO, feature_ids=("cost-management",), dynamic=False)
    )
    static = next(node for node in snapshot.content.nodes if node.id == "ui_route:/cost")
    assert static.state.health.value == "unknown"


def test_every_evidence_has_no_source_snippet_field() -> None:
    snapshot = scan_repository(
        ScanRequest(repo=REPO, feature_ids=("cost-management",), dynamic=False)
    )
    for node in snapshot.content.nodes:
        for evidence in node.evidence:
            assert set(evidence.model_dump()) == {"path", "line", "symbol", "blob"}
    for edge in snapshot.content.edges:
        for evidence in edge.evidence:
            assert set(evidence.model_dump()) == {"path", "line", "symbol", "blob"}
