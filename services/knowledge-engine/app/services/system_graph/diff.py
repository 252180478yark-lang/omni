"""Semantic fact-snapshot diff with fail-closed removed semantics."""

from __future__ import annotations

from typing import Any

from app.schemas.system_graph import (
    ExistenceState,
    GraphDiff,
    GraphEdge,
    GraphNode,
    GraphSnapshot,
    SourceStatus,
)
from app.services.system_graph.canonical import canonical_json


def _changed(left: Any, right: Any) -> bool:
    return canonical_json(left.model_dump(mode="json")) != canonical_json(
        right.model_dump(mode="json")
    )


def _removal_is_proven(
    item: GraphNode | GraphEdge, target: GraphSnapshot
) -> bool:
    if not item.sources:
        return False
    statuses = {
        result.collector_id: result.status for result in target.content.source_results
    }
    return all(statuses.get(source) == SourceStatus.SUCCESS for source in item.sources)


def _diff_items(
    before: dict[str, GraphNode | GraphEdge],
    after: dict[str, GraphNode | GraphEdge],
    target: GraphSnapshot,
) -> tuple[list[str], list[str], list[str], list[str]]:
    added = sorted(set(after) - set(before))
    changed: list[str] = []
    unknown: list[str] = []
    for item_id in sorted(set(before) & set(after)):
        if after[item_id].state.existence == ExistenceState.UNKNOWN:
            unknown.append(item_id)
        elif _changed(before[item_id], after[item_id]):
            changed.append(item_id)
    removed: list[str] = []
    for item_id in sorted(set(before) - set(after)):
        if _removal_is_proven(before[item_id], target):
            removed.append(item_id)
        else:
            unknown.append(item_id)
    return added, changed, removed, sorted(set(unknown))


def diff_snapshots(before: GraphSnapshot, after: GraphSnapshot) -> GraphDiff:
    if before.content.schema_version != after.content.schema_version:
        raise ValueError("incompatible snapshot schema")
    nodes = _diff_items(
        {node.id: node for node in before.content.nodes},
        {node.id: node for node in after.content.nodes},
        after,
    )
    edges = _diff_items(
        {edge.id: edge for edge in before.content.edges},
        {edge.id: edge for edge in after.content.edges},
        after,
    )
    return GraphDiff(
        from_snapshot=before.snapshot_id,
        to_snapshot=after.snapshot_id,
        added_nodes=nodes[0],
        changed_nodes=nodes[1],
        removed_nodes=nodes[2],
        unknown_nodes=nodes[3],
        added_edges=edges[0],
        changed_edges=edges[1],
        removed_edges=edges[2],
        unknown_edges=edges[3],
    )
