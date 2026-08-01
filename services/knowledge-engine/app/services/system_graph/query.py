"""Stable graph normalization, traversal, pagination, and search for S7."""

from __future__ import annotations

from collections import defaultdict, deque

from app.schemas.system_graph import (
    GraphPage,
    GraphPageInfo,
    GraphSearchHit,
    GraphSearchPage,
    GraphSnapshot,
    SourceStatus,
)


def _cursor(value: str | None) -> int:
    if value in {None, ""}:
        return 0
    if not value.isdigit():
        raise ValueError("invalid_cursor")
    return int(value)


def _node_ids_for_root(
    snapshot: GraphSnapshot,
    *,
    root: str | None,
    direction: str,
    depth: int,
) -> set[str]:
    known = {node.id for node in snapshot.content.nodes}
    if not root:
        return known
    if root not in known:
        raise KeyError(root)
    outgoing: dict[str, set[str]] = defaultdict(set)
    incoming: dict[str, set[str]] = defaultdict(set)
    for edge in snapshot.content.edges:
        outgoing[edge.source].add(edge.target)
        incoming[edge.target].add(edge.source)
    selected = {root}
    queue = deque([(root, 0)])
    while queue:
        current, current_depth = queue.popleft()
        if current_depth >= depth:
            continue
        neighbours: set[str] = set()
        if direction in {"out", "both"}:
            neighbours.update(outgoing[current])
        if direction in {"in", "both"}:
            neighbours.update(incoming[current])
        for neighbour in sorted(neighbours):
            if neighbour not in selected:
                selected.add(neighbour)
                queue.append((neighbour, current_depth + 1))
    return selected


def graph_page(
    snapshot: GraphSnapshot,
    *,
    root: str | None = None,
    direction: str = "both",
    depth: int = 2,
    cursor: str | None = None,
    limit: int = 200,
    kinds: set[str] | None = None,
    states: set[str] | None = None,
) -> GraphPage:
    if direction not in {"in", "out", "both"}:
        raise ValueError("invalid_direction")
    selected_ids = _node_ids_for_root(snapshot, root=root, direction=direction, depth=depth)
    nodes = [node for node in snapshot.content.nodes if node.id in selected_ids]
    if kinds:
        nodes = [node for node in nodes if node.kind in kinds]
    if states:
        nodes = [
            node
            for node in nodes
            if {
                node.state.existence.value,
                node.state.health.value,
                node.state.lifecycle.value,
                node.state.evidence.value,
            }
            & states
        ]
    nodes.sort(key=lambda item: item.id)
    start = _cursor(cursor)
    visible = nodes[start : start + limit]
    visible_ids = {node.id for node in visible}
    edges = sorted(
        [
            edge
            for edge in snapshot.content.edges
            if edge.source in visible_ids and edge.target in visible_ids
        ],
        key=lambda item: item.id,
    )
    degree: dict[str, int] = defaultdict(int)
    for edge in snapshot.content.edges:
        degree[edge.source] += 1
        degree[edge.target] += 1
    orphans = [node.id for node in visible if degree[node.id] == 0]
    next_offset = start + len(visible)
    partial = any(item.status is not SourceStatus.SUCCESS for item in snapshot.content.source_results)
    return GraphPage(
        snapshot_id=snapshot.snapshot_id,
        generated_at_utc=snapshot.generated_at_utc,
        nodes=visible,
        edges=edges,
        source_results=snapshot.content.source_results,
        partial=partial,
        orphan_node_ids=orphans,
        page_info=GraphPageInfo(
            next_cursor=str(next_offset) if next_offset < len(nodes) else None,
            has_more=next_offset < len(nodes),
        ),
    )


def search_page(
    snapshot: GraphSnapshot,
    *,
    query: str,
    cursor: str | None = None,
    limit: int = 50,
) -> GraphSearchPage:
    needle = query.casefold().strip()
    if not needle or len(needle) > 200:
        raise ValueError("invalid_query")
    edges_by_node: dict[str, list[str]] = defaultdict(list)
    for edge in snapshot.content.edges:
        edges_by_node[edge.source].append(edge.target)
        edges_by_node[edge.target].append(edge.source)
    matches = []
    for node in sorted(snapshot.content.nodes, key=lambda item: item.id):
        haystack = " ".join((node.id, node.kind, node.key, node.label)).casefold()
        if needle in haystack:
            matches.append(
                GraphSearchHit(
                    node=node,
                    path=sorted(set(edges_by_node[node.id]))[:8],
                )
            )
    start = _cursor(cursor)
    visible = matches[start : start + limit]
    next_offset = start + len(visible)
    return GraphSearchPage(
        snapshot_id=snapshot.snapshot_id,
        query=query,
        results=visible,
        page_info=GraphPageInfo(
            next_cursor=str(next_offset) if next_offset < len(matches) else None,
            has_more=next_offset < len(matches),
        ),
    )
