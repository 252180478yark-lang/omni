from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))
from app.schemas.system_graph import (
    GraphNode,
    GraphSnapshot,
    GraphSnapshotContent,
    SourceResult,
    SourceStatus,
)
from app.services.system_graph.canonical import sha256_value
from app.services.system_graph.collectors.base import CollectorOutput, source_result
from app.services.system_graph.diff import diff_snapshots
from app.services.system_graph.scanner import ScanRequest, scan_repository
from app.services.system_graph.snapshots import read_snapshot, verify_evidence, write_snapshot


REPO = Path(__file__).resolve().parents[3]


def _snapshot(*, include_node: bool, status: SourceStatus) -> GraphSnapshot:
    nodes = (
        [
            GraphNode(
                id="service_symbol:fixture.query",
                kind="service_symbol",
                key="fixture.query",
                label="fixture.query",
                sources=["runtime.fixture"],
            )
        ]
        if include_node
        else []
    )
    content = GraphSnapshotContent(
        commit="a" * 40,
        definition_revision="sha256:" + "b" * 64,
        collector_versions={"runtime.fixture": "1"},
        feature_ids=["fixture"],
        source_results=[
            SourceResult(
                collector_id="runtime.fixture",
                version="1",
                status=status,
                reason_code="collector_timeout" if status != SourceStatus.SUCCESS else "",
                retryable=status != SourceStatus.SUCCESS,
            )
        ],
        nodes=nodes,
        edges=[],
    )
    digest = sha256_value(content.model_dump(mode="json"))
    return GraphSnapshot(
        snapshot_id=digest,
        content_hash=digest,
        generated_at_utc=datetime.now(timezone.utc),
        content=content,
    )


def test_same_inputs_have_stable_hash_empty_diff_and_immutable_path(tmp_path: Path) -> None:
    request = ScanRequest(repo=REPO, feature_ids=("cost-management",), dynamic=False)
    first = scan_repository(request)
    second = scan_repository(request)
    assert first.content_hash == second.content_hash
    assert diff_snapshots(first, second).is_empty
    first_path = write_snapshot(first, tmp_path)
    second_path = write_snapshot(second, tmp_path)
    assert first_path == second_path
    assert read_snapshot(first_path).content_hash == first.content_hash
    assert verify_evidence(first, REPO) == []


def test_failed_source_never_produces_removed() -> None:
    before = _snapshot(include_node=True, status=SourceStatus.SUCCESS)
    unavailable = _snapshot(include_node=False, status=SourceStatus.UNKNOWN)
    diff = diff_snapshots(before, unavailable)
    assert diff.removed_nodes == []
    assert diff.unknown_nodes == ["service_symbol:fixture.query"]


def test_successful_source_can_prove_removed() -> None:
    before = _snapshot(include_node=True, status=SourceStatus.SUCCESS)
    after = _snapshot(include_node=False, status=SourceStatus.SUCCESS)
    diff = diff_snapshots(before, after)
    assert diff.removed_nodes == ["service_symbol:fixture.query"]
    assert diff.unknown_nodes == []


def test_base_snapshot_carries_failed_collector_facts_as_unknown(monkeypatch) -> None:
    before = scan_repository(
        ScanRequest(repo=REPO, feature_ids=("cost-management",), dynamic=False)
    )

    def unavailable_frontend(self, context):
        return CollectorOutput(
            source_results=[
                source_result(
                    self.collector_id,
                    self.version,
                    SourceStatus.UNKNOWN,
                    "collector_timeout",
                    retryable=True,
                )
            ]
        )

    monkeypatch.setattr(
        scan_repository.__globals__["FrontendCollector"],
        "collect",
        unavailable_frontend,
    )
    after = scan_repository(
        ScanRequest(
            repo=REPO,
            feature_ids=("cost-management",),
            dynamic=False,
            base_snapshot=before,
        )
    )
    ui = next(node for node in after.content.nodes if node.id == "ui_route:/cost")
    assert ui.state.existence.value == "unknown"
    diff = diff_snapshots(before, after)
    assert "ui_route:/cost" in diff.unknown_nodes
    assert "ui_route:/cost" not in diff.removed_nodes
