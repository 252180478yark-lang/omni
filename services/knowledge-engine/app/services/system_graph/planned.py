"""S4 deterministic planned-to-fact projection and repair-card generation.

This module deliberately reads an impact contract and an immutable S3 snapshot;
it never writes a product file, changes the snapshot, or treats a failed
collector as a deletion.  CI can render its findings as warnings now and S6
can later promote a selected, deterministic issue code to a block.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml
from pydantic import Field

from app.schemas.system_graph import (
    EvidenceClassification,
    GraphSnapshot,
    RequiredEdgeState,
    SourceStatus,
    StrictModel,
)
from app.services.system_graph.canonical import sha256_value


class PlannedNode(StrictModel):
    node_id: str = Field(min_length=3)
    decision: str = Field(min_length=1)


class RequiredEdgeResult(StrictModel):
    source: str = Field(min_length=3)
    target: str = Field(min_length=3)
    relation: str = Field(min_length=1)
    state: RequiredEdgeState
    evidence_refs: list[str] = Field(default_factory=list)


class RepairCard(StrictModel):
    fingerprint: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    code: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    severity: str = Field(pattern=r"^(warning|unknown|blocking)$")
    classification: EvidenceClassification
    observed: str
    expected: str
    impact_paths: list[str]
    evidence_refs: list[str] = Field(default_factory=list)
    suggested_locations: list[str] = Field(default_factory=list)
    verification_command: str = Field(min_length=1)


class PlannedFactReport(StrictModel):
    change_id: str = Field(min_length=1)
    snapshot_id: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    planned_nodes: list[PlannedNode]
    required_edges: list[RequiredEdgeResult]
    issues: list[RepairCard]

    @property
    def selected_blocking(self) -> list[RepairCard]:
        return [issue for issue in self.issues if issue.severity == "blocking"]


def load_impact(path: Path) -> dict[str, Any]:
    """Load the narrow contract surface required by the S4 projection."""

    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("impact contract must be a mapping")
    if not str(value.get("change_id", "")).strip():
        raise ValueError("impact contract is missing change_id")
    return value


def _as_edge(item: Mapping[str, Any]) -> tuple[str, str, str]:
    source = str(item.get("from", "")).strip()
    target = str(item.get("to", "")).strip()
    relation = str(item.get("relation", "")).strip()
    if not source or not target or not relation:
        raise ValueError("required edge needs from, to, and relation")
    return source, target, relation


def _planned_nodes(impact: Mapping[str, Any]) -> list[PlannedNode]:
    nodes: dict[str, str] = {}
    for change in impact.get("planned_changes") or []:
        if not isinstance(change, Mapping):
            continue
        node_id = str(change.get("node_id", "")).strip()
        if node_id:
            nodes[node_id] = str(change.get("action", "modify")).strip() or "modify"
    for raw_edge in (impact.get("graph_acceptance") or {}).get("required_edges") or []:
        if isinstance(raw_edge, Mapping):
            source, target, _ = _as_edge(raw_edge)
            nodes.setdefault(source, "planned")
            nodes.setdefault(target, "planned")
    return [PlannedNode(node_id=node_id, decision=nodes[node_id]) for node_id in sorted(nodes)]


def _all_sources_succeeded(snapshot: GraphSnapshot) -> bool:
    return bool(snapshot.content.source_results) and all(
        result.status is SourceStatus.SUCCESS for result in snapshot.content.source_results
    )


def _edge_evidence(snapshot: GraphSnapshot, edge_id: str) -> list[str]:
    edge = next((item for item in snapshot.content.edges if item.id == edge_id), None)
    if edge is None:
        return []
    return [
        f"{ref.path}:{ref.line}:{ref.symbol}:{ref.blob}"
        for ref in edge.evidence
    ]


def _repair_card(
    *,
    change_id: str,
    snapshot_id: str,
    edge: RequiredEdgeResult,
    planned_paths: list[str],
    selected_block_codes: set[str],
) -> RepairCard:
    code = "required_edge_missing" if edge.state is RequiredEdgeState.MISSING else "required_edge_unknown"
    classification = (
        EvidenceClassification.OBSERVED_FACT
        if edge.state is RequiredEdgeState.MISSING
        else EvidenceClassification.HYPOTHESIS
    )
    severity = "unknown" if edge.state is RequiredEdgeState.UNKNOWN else "warning"
    if code in selected_block_codes and classification is EvidenceClassification.OBSERVED_FACT:
        severity = "blocking"
    expected = f"{edge.source} --{edge.relation}--> {edge.target}"
    fingerprint = sha256_value(
        {
            "code": code,
            "change_id": change_id,
            "snapshot_id": snapshot_id,
            "expected": expected,
        }
    )
    observed = "no matching fact edge in successful snapshot" if edge.state is RequiredEdgeState.MISSING else "collector result is partial or unknown"
    return RepairCard(
        fingerprint=fingerprint,
        code=code,
        severity=severity,
        classification=classification,
        observed=observed,
        expected=expected,
        impact_paths=planned_paths,
        evidence_refs=edge.evidence_refs,
        suggested_locations=planned_paths,
        verification_command="python -B services/knowledge-engine/scripts/system_graph.py verify --feature <feature-id> --ref <commit>",
    )


def project_impact(
    impact: Mapping[str, Any],
    snapshot: GraphSnapshot,
    *,
    selected_block_codes: Iterable[str] = (),
) -> PlannedFactReport:
    """Project required impact edges over facts without mutating either input."""

    change_id = str(impact.get("change_id", "")).strip()
    if not change_id:
        raise ValueError("impact contract is missing change_id")
    actual = {
        (edge.source, edge.target, edge.relation): edge.id
        for edge in snapshot.content.edges
    }
    paths = sorted(
        {
            str(path)
            for change in impact.get("planned_changes") or []
            if isinstance(change, Mapping)
            for path in (change.get("paths") or [])
            if str(path).strip()
        }
    )
    block_codes = {str(code) for code in selected_block_codes}
    results: list[RequiredEdgeResult] = []
    issues: list[RepairCard] = []
    raw_edges = (impact.get("graph_acceptance") or {}).get("required_edges") or []
    for raw_edge in raw_edges:
        if not isinstance(raw_edge, Mapping):
            raise ValueError("required edge must be a mapping")
        source, target, relation = _as_edge(raw_edge)
        edge_id = actual.get((source, target, relation))
        state = (
            RequiredEdgeState.PRESENT
            if edge_id
            else RequiredEdgeState.MISSING
            if _all_sources_succeeded(snapshot)
            else RequiredEdgeState.UNKNOWN
        )
        result = RequiredEdgeResult(
            source=source,
            target=target,
            relation=relation,
            state=state,
            evidence_refs=_edge_evidence(snapshot, edge_id) if edge_id else [],
        )
        results.append(result)
        if state is not RequiredEdgeState.PRESENT:
            issues.append(
                _repair_card(
                    change_id=change_id,
                    snapshot_id=snapshot.snapshot_id,
                    edge=result,
                    planned_paths=paths,
                    selected_block_codes=block_codes,
                )
            )
    return PlannedFactReport(
        change_id=change_id,
        snapshot_id=snapshot.snapshot_id,
        planned_nodes=_planned_nodes(impact),
        required_edges=results,
        issues=sorted(issues, key=lambda issue: issue.fingerprint),
    )
