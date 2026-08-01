from __future__ import annotations

import sys
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SERVICE_ROOT.parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.services.system_graph.feature_definitions import generate_bundle
from app.services.system_graph.scanner import ScanRequest, scan_repository
from app.services.system_graph.snapshots import verify_evidence


def test_s4_s6_feature_definition_binds_observed_rest_service_mcp_and_tests() -> None:
    generate_bundle(REPO_ROOT, check=True)
    snapshot = scan_repository(
        ScanRequest(
            repo=REPO_ROOT,
            feature_ids=("system-convergence-s4-s6",),
            ref="HEAD",
            dynamic=False,
        )
    )
    edges = {(edge.source, edge.target, edge.relation) for edge in snapshot.content.edges}
    assert (
        "ui_route:/system-graph",
        "bff_operation:GET:/api/omni/system-graph/integration-plans",
        "calls",
    ) in edges
    assert (
        "bff_operation:GET:/api/omni/system-graph/integration-plans",
        "rest_operation:GET:/api/v1/system-graph/integration-plans",
        "proxies_to",
    ) in edges
    assert (
        "rest_operation:POST:/api/v1/system-graph/integration-plans",
        "service_symbol:app.services.system_graph.integration_plans.create_candidate_plan",
        "invokes",
    ) in edges
    assert (
        "test:services/knowledge-engine/tests/test_system_graph_integration_router.py::test_rest_plan_requires_owner_and_returns_only_candidate_artifacts",
        "rest_operation:POST:/api/v1/system-graph/integration-plans",
        "verifies",
    ) in edges
    assert (
        "test:services/knowledge-engine/tests/test_system_graph_mcp_registration.py::test_system_graph_mcp_tools_are_registered_and_in_doctor_contract",
        "mcp_tool:system_graph_confirm_plan",
        "verifies",
    ) in edges
    assert verify_evidence(snapshot, REPO_ROOT) == []
