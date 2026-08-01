"""Orchestrate collectors into one deterministic, content-addressed snapshot."""

from __future__ import annotations

import subprocess
import tarfile
import tempfile
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from app.schemas.system_graph import (
    EvidenceState,
    ExistenceState,
    GraphEdge,
    GraphNode,
    GraphSnapshot,
    GraphSnapshotContent,
    GraphState,
    HealthState,
    SourceResult,
    SourceStatus,
)
from app.services.system_graph.canonical import resolve_commit, sha256_value
from app.services.system_graph.collectors import (
    CatalogCollector,
    FrontendCollector,
    HealthDeliveryCollector,
    MigrationCollector,
    PythonGraphCollector,
)
from app.services.system_graph.collectors.base import (
    CollectorContext,
    CollectorOutput,
    source_result,
)
from app.services.system_graph.feature_definitions import (
    definition_revision,
    load_definitions,
    select_definitions,
)
from app.services.system_graph.redaction import redact


@dataclass(frozen=True)
class ScanRequest:
    repo: Path
    feature_ids: tuple[str, ...] = ()
    ref: str | None = None
    dynamic: bool = True
    timeout_seconds: float = 8.0
    delivery_attestation: Path | None = None
    base_snapshot: GraphSnapshot | None = None


@contextmanager
def _materialized_git_tree(repo: Path, commit: str) -> Iterator[Path]:
    """Expose one immutable commit to collectors without reading the caller worktree."""

    with tempfile.TemporaryDirectory(prefix="omni-system-graph-") as temporary:
        temporary_root = Path(temporary)
        archive_path = temporary_root / "tree.tar"
        materialized = temporary_root / "repo"
        materialized.mkdir()
        with archive_path.open("wb") as archive:
            subprocess.run(
                ["git", "-C", str(repo), "archive", "--format=tar", commit],
                check=True,
                stdout=archive,
                stderr=subprocess.PIPE,
                timeout=60,
            )
        with tarfile.open(archive_path, mode="r:") as bundle:
            root = materialized.resolve()
            for member in bundle.getmembers():
                target = (materialized / member.name).resolve()
                if target != root and root not in target.parents:
                    raise ValueError(f"archived path escapes repository: {member.name}")
                if member.issym() or member.islnk():
                    link_target = (target.parent / member.linkname).resolve()
                    if link_target != root and root not in link_target.parents:
                        raise ValueError(
                            f"archived link escapes repository: {member.name}"
                        )
            bundle.extractall(materialized)
        # Evidence hashing uses `git hash-object`; an empty local repository is enough
        # because the materialized bytes are the immutable source of each blob ID.
        subprocess.run(
            ["git", "init", "--quiet"],
            check=True,
            cwd=materialized,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
        )
        yield materialized


def _evidence_key(item: Any) -> tuple[Any, ...]:
    return (item.path, item.line, item.symbol, item.blob)


def _merge_state(left: GraphState, right: GraphState) -> GraphState:
    health = left.health
    if health == HealthState.UNKNOWN:
        health = right.health
    elif right.health != HealthState.UNKNOWN and right.health != health:
        health = HealthState.DEGRADED
    evidence_values = {left.evidence, right.evidence}
    if EvidenceState.BOTH in evidence_values or evidence_values == {
        EvidenceState.STATIC,
        EvidenceState.RUNTIME,
    }:
        evidence = EvidenceState.BOTH
    elif EvidenceState.STATIC in evidence_values:
        evidence = EvidenceState.STATIC
    elif EvidenceState.RUNTIME in evidence_values:
        evidence = EvidenceState.RUNTIME
    else:
        evidence = EvidenceState.NONE
    existence = (
        ExistenceState.OBSERVED
        if ExistenceState.OBSERVED in {left.existence, right.existence}
        else left.existence
    )
    lifecycle = left.lifecycle if left.lifecycle == right.lifecycle else right.lifecycle
    return GraphState(
        existence=existence,
        health=health,
        lifecycle=lifecycle,
        evidence=evidence,
    )


def _merge_nodes(nodes: list[GraphNode]) -> list[GraphNode]:
    merged: dict[str, GraphNode] = {}
    for node in nodes:
        node = node.model_copy(update={"attrs": redact(node.attrs)})
        previous = merged.get(node.id)
        if previous is None:
            merged[node.id] = node
            continue
        if previous.kind != node.kind or previous.key != node.key:
            raise ValueError(f"conflicting graph node identity: {node.id}")
        attrs = dict(previous.attrs)
        for key, value in node.attrs.items():
            if key not in attrs:
                attrs[key] = value
            elif attrs[key] != value:
                attrs[key] = sorted(
                    {str(attrs[key]), str(value)}
                )
        evidence = {
            _evidence_key(item): item for item in [*previous.evidence, *node.evidence]
        }
        merged[node.id] = previous.model_copy(
            update={
                "label": min(previous.label, node.label),
                "state": _merge_state(previous.state, node.state),
                "attrs": redact(attrs),
                "evidence": [evidence[key] for key in sorted(evidence)],
                "sources": sorted(set(previous.sources) | set(node.sources)),
            }
        )
    return [merged[key] for key in sorted(merged)]


def _merge_edges(edges: list[GraphEdge]) -> list[GraphEdge]:
    merged: dict[str, GraphEdge] = {}
    for edge in edges:
        edge = edge.model_copy(update={"attrs": redact(edge.attrs)})
        previous = merged.get(edge.id)
        if previous is None:
            merged[edge.id] = edge
            continue
        if (
            previous.relation != edge.relation
            or previous.source != edge.source
            or previous.target != edge.target
        ):
            raise ValueError(f"conflicting graph edge identity: {edge.id}")
        evidence = {
            _evidence_key(item): item for item in [*previous.evidence, *edge.evidence]
        }
        attrs = dict(previous.attrs)
        for key, value in edge.attrs.items():
            if key not in attrs:
                attrs[key] = value
            elif attrs[key] != value:
                attrs[key] = sorted({str(attrs[key]), str(value)})
        merged[edge.id] = previous.model_copy(
            update={
                "state": _merge_state(previous.state, edge.state),
                "confidence": max(previous.confidence, edge.confidence),
                "attrs": redact(attrs),
                "evidence": [evidence[key] for key in sorted(evidence)],
                "sources": sorted(set(previous.sources) | set(edge.sources)),
            }
        )
    return [merged[key] for key in sorted(merged)]


def _carry_unknowns(
    *,
    base: GraphSnapshot | None,
    nodes: list[GraphNode],
    edges: list[GraphEdge],
    source_results: list[SourceResult],
) -> tuple[list[GraphNode], list[GraphEdge]]:
    if base is None:
        return nodes, edges
    statuses = {result.collector_id: result.status for result in source_results}
    current_node_ids = {node.id for node in nodes}
    for prior in base.content.nodes:
        if prior.id in current_node_ids or not prior.sources:
            continue
        if all(statuses.get(source, SourceStatus.UNKNOWN) != SourceStatus.SUCCESS for source in prior.sources):
            nodes.append(
                prior.model_copy(
                    update={
                        "state": prior.state.model_copy(
                            update={
                                "existence": ExistenceState.UNKNOWN,
                                "health": HealthState.UNKNOWN,
                            }
                        )
                    }
                )
            )
    known_nodes = {node.id for node in nodes}
    current_edge_ids = {edge.id for edge in edges}
    for prior in base.content.edges:
        if prior.id in current_edge_ids or not prior.sources:
            continue
        failed = all(
            statuses.get(source, SourceStatus.UNKNOWN) != SourceStatus.SUCCESS
            for source in prior.sources
        )
        if failed and prior.source in known_nodes and prior.target in known_nodes:
            edges.append(
                prior.model_copy(
                    update={
                        "state": prior.state.model_copy(
                            update={
                                "existence": ExistenceState.UNKNOWN,
                                "health": HealthState.UNKNOWN,
                            }
                        )
                    }
                )
            )
    return nodes, edges


def scan_repository(request: ScanRequest) -> GraphSnapshot:
    repo = request.repo.resolve()
    subject_commit = resolve_commit(repo, request.ref or "HEAD")
    scan_context = (
        _materialized_git_tree(repo, subject_commit)
        if request.ref is not None
        else nullcontext(repo)
    )
    with scan_context as scan_repo:
        all_definitions = load_definitions(scan_repo)
        selected = select_definitions(all_definitions, list(request.feature_ids))
        context = CollectorContext(
            repo=scan_repo,
            definitions=tuple(selected),
            dynamic=request.dynamic,
            timeout_seconds=request.timeout_seconds,
            delivery_attestation=request.delivery_attestation,
        )
        collectors = [
            FrontendCollector(),
            PythonGraphCollector(),
            CatalogCollector(),
            MigrationCollector(),
            HealthDeliveryCollector(),
        ]
        combined = CollectorOutput()
        for collector in collectors:
            try:
                result = collector.collect(context)
            except Exception:
                result = CollectorOutput(
                    source_results=[
                        source_result(
                            collector.collector_id,
                            collector.version,
                            SourceStatus.UNKNOWN,
                            "collector_failed",
                            retryable=True,
                        )
                    ]
                )
            combined.nodes.extend(result.nodes)
            combined.edges.extend(result.edges)
            combined.source_results.extend(result.source_results)
            combined.diagnostics.extend(result.diagnostics)

    source_by_id: dict[str, SourceResult] = {}
    for result in combined.source_results:
        previous = source_by_id.get(result.collector_id)
        if previous is None:
            source_by_id[result.collector_id] = result
        elif previous.status != result.status:
            # Fail closed on inconsistent duplicate reports.
            source_by_id[result.collector_id] = source_result(
                result.collector_id,
                result.version,
                SourceStatus.PARTIAL,
                "inconsistent_source_status",
                retryable=True,
            )
    source_results = [source_by_id[key] for key in sorted(source_by_id)]
    nodes = _merge_nodes(combined.nodes)
    edges = _merge_edges(combined.edges)
    nodes, edges = _carry_unknowns(
        base=request.base_snapshot,
        nodes=nodes,
        edges=edges,
        source_results=source_results,
    )
    nodes = _merge_nodes(nodes)
    edges = _merge_edges(edges)

    known_nodes = {node.id for node in nodes}
    edges = [edge for edge in edges if edge.source in known_nodes and edge.target in known_nodes]
    diagnostics = sorted(combined.diagnostics, key=lambda item: item.fingerprint)
    content = GraphSnapshotContent(
        commit=subject_commit,
        definition_revision=definition_revision(all_definitions),
        collector_versions={result.collector_id: result.version for result in source_results},
        feature_ids=sorted(definition.feature_id for definition in selected),
        source_results=source_results,
        nodes=nodes,
        edges=edges,
        diagnostics=diagnostics,
    )
    content_hash = sha256_value(content.model_dump(mode="json"))
    return GraphSnapshot(
        snapshot_id=content_hash,
        content_hash=content_hash,
        generated_at_utc=datetime.now(timezone.utc).replace(microsecond=0),
        content=content,
    )
