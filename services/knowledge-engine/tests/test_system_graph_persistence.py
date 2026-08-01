from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

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
from app.services.system_graph.canonical import sha256_value
from app.services.system_graph.query import graph_page, search_page
from app.services.system_graph.repository import MemoryGraphRepository, refresh_fingerprint


def snapshot(*, label: str = "Workspace", source_status: SourceStatus = SourceStatus.SUCCESS) -> GraphSnapshot:
    nodes = [
        GraphNode(id="ui_route:/workspace", kind="ui_route", key="/workspace", label=label),
        GraphNode(id="rest_operation:GET:/api/v1/system-graph", kind="rest_operation", key="GET:/api/v1/system-graph", label="Graph API"),
    ]
    edges = [
        GraphEdge(
            id="edge:workspace-graph",
            relation="calls",
            source=nodes[0].id,
            target=nodes[1].id,
        )
    ]
    content = GraphSnapshotContent(
        commit="a" * 40,
        definition_revision="sha256:" + "b" * 64,
        collector_versions={"frontend.static": "1"},
        feature_ids=["system-command-center"],
        source_results=[SourceResult(collector_id="frontend.static", version="1", status=source_status)],
        nodes=nodes,
        edges=edges,
    )
    digest = sha256_value(content.model_dump(mode="json"))
    return GraphSnapshot(
        snapshot_id=digest,
        content_hash=digest,
        generated_at_utc=datetime.now(timezone.utc),
        content=content,
    )


@pytest.mark.asyncio
async def test_memory_repository_is_idempotent_and_snapshot_content_is_immutable() -> None:
    repository = MemoryGraphRepository()
    request = {"feature_ids": [], "include_runtime": False, "idempotency_key": "fixture-123"}
    fingerprint = refresh_fingerprint(request)
    first, created = await repository.begin_refresh(fingerprint=fingerprint, actor_id="owner", request=request)
    again, reused_created = await repository.begin_refresh(fingerprint=fingerprint, actor_id="owner", request=request)
    assert created is True
    assert reused_created is False
    assert first.refresh_id == again.refresh_id

    graph = snapshot()
    await repository.save_snapshot(graph)
    await repository.save_snapshot(graph.model_copy(update={"generated_at_utc": datetime.now(timezone.utc)}))
    conflicting = snapshot(label="Changed label").model_copy(
        update={"snapshot_id": graph.snapshot_id, "content_hash": graph.content_hash}
    )
    with pytest.raises(ValueError, match="immutable_snapshot_collision"):
        await repository.save_snapshot(conflicting)


def test_graph_query_paginates_filters_and_searches_without_dangling_edges() -> None:
    graph = snapshot()
    page = graph_page(graph, root="ui_route:/workspace", direction="out", depth=1, limit=1)
    assert [node.id for node in page.nodes] == ["rest_operation:GET:/api/v1/system-graph"]
    assert page.edges == []
    assert page.page_info.has_more is True
    second = graph_page(graph, root="ui_route:/workspace", direction="out", depth=1, cursor="1", limit=1)
    assert [node.id for node in second.nodes] == ["ui_route:/workspace"]
    assert second.page_info.has_more is False
    result = search_page(graph, query="workspace")
    assert result.results[0].node.id == "ui_route:/workspace"
    assert result.results[0].path == ["rest_operation:GET:/api/v1/system-graph"]
    with pytest.raises(ValueError, match="invalid_cursor"):
        graph_page(graph, cursor="not-a-cursor")
