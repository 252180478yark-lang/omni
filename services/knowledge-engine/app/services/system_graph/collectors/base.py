"""Shared collector result, fact builders and isolated subprocess runner."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from app.schemas.system_graph import (
    CollectorDiagnostic,
    EvidenceRef,
    GraphEdge,
    GraphNode,
    GraphState,
    SourceResult,
    SourceStatus,
)
from app.services.system_graph.canonical import make_edge_id, make_node_id
from app.services.system_graph.feature_definitions import FeatureDefinition
from app.services.system_graph.redaction import redact


@dataclass(frozen=True)
class CollectorContext:
    repo: Path
    definitions: tuple[FeatureDefinition, ...]
    dynamic: bool = True
    timeout_seconds: float = 8.0
    delivery_attestation: Path | None = None


@dataclass
class CollectorOutput:
    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)
    source_results: list[SourceResult] = field(default_factory=list)
    diagnostics: list[CollectorDiagnostic] = field(default_factory=list)


class Collector(Protocol):
    collector_id: str
    version: str

    def collect(self, context: CollectorContext) -> CollectorOutput: ...


def source_result(
    collector_id: str,
    version: str,
    status: SourceStatus,
    reason_code: str = "",
    *,
    retryable: bool = False,
) -> SourceResult:
    return SourceResult(
        collector_id=collector_id,
        version=version,
        status=status,
        reason_code=reason_code,
        retryable=retryable,
    )


def observed_node(
    kind: str,
    key: str,
    *,
    label: str,
    collector_id: str,
    evidence: list[EvidenceRef] | None = None,
    attrs: dict[str, Any] | None = None,
    lifecycle: str = "active",
) -> GraphNode:
    state = GraphState(lifecycle=lifecycle)
    return GraphNode(
        id=make_node_id(kind, key),
        kind=kind,
        key=key,
        label=label,
        state=state,
        attrs=redact(attrs or {}),
        evidence=evidence or [],
        sources=[collector_id],
    )


def observed_edge(
    relation: str,
    source: str,
    target: str,
    *,
    collector_id: str,
    evidence: list[EvidenceRef] | None = None,
    attrs: dict[str, Any] | None = None,
    confidence: float = 1.0,
) -> GraphEdge:
    return GraphEdge(
        id=make_edge_id(relation, source, target),
        relation=relation,
        source=source,
        target=target,
        confidence=confidence,
        attrs=redact(attrs or {}),
        evidence=evidence or [],
        sources=[collector_id],
    )


def run_isolated_json(
    context: CollectorContext,
    *,
    collector_id: str,
    version: str,
    code: str,
) -> tuple[dict[str, Any] | list[Any] | None, SourceResult]:
    if not context.dynamic:
        return None, source_result(
            collector_id, version, SourceStatus.UNKNOWN, "dynamic_disabled", retryable=True
        )
    forced = {
        item.strip()
        for item in os.environ.get("OMNI_SYSTEM_GRAPH_FORCE_DYNAMIC_FAILURE", "").split(",")
        if item.strip()
    }
    if collector_id in forced:
        return None, source_result(
            collector_id, version, SourceStatus.UNKNOWN, "forced_failure", retryable=True
        )
    service_root = context.repo / "services" / "knowledge-engine"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(service_root)
    try:
        completed = subprocess.run(
            [sys.executable, "-B", "-c", code],
            cwd=service_root,
            env=env,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
            timeout=context.timeout_seconds,
        )
        payload = json.loads(completed.stdout)
        if not isinstance(payload, (dict, list)):
            raise ValueError("isolated collector did not return an object or array")
        return payload, source_result(collector_id, version, SourceStatus.SUCCESS)
    except subprocess.TimeoutExpired:
        return None, source_result(
            collector_id, version, SourceStatus.UNKNOWN, "collector_timeout", retryable=True
        )
    except (OSError, subprocess.SubprocessError, UnicodeError, json.JSONDecodeError, ValueError):
        return None, source_result(
            collector_id, version, SourceStatus.UNKNOWN, "collector_unavailable", retryable=True
        )
