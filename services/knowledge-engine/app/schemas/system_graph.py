"""Versioned, storage-neutral contracts for the deterministic system graph."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExistenceState(StrEnum):
    PLANNED = "planned"
    OBSERVED = "observed"
    REMOVED = "removed"
    UNKNOWN = "unknown"


try:  # S2.5 can land in parallel; keep S3 independently importable until then.
    from app.schemas.system_health import HealthState as HealthState
except (ImportError, AttributeError):
    class HealthState(StrEnum):
        HEALTHY = "healthy"
        DEGRADED = "degraded"
        UNAVAILABLE = "unavailable"
        STALE = "stale"
        UNKNOWN = "unknown"


class LifecycleState(StrEnum):
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    ARCHIVED = "archived"


class EvidenceState(StrEnum):
    STATIC = "static"
    RUNTIME = "runtime"
    BOTH = "both"
    NONE = "none"


class SourceStatus(StrEnum):
    SUCCESS = "success"
    PARTIAL = "partial"
    UNKNOWN = "unknown"


class EvidenceRef(StrictModel):
    """A source coordinate, deliberately without source text or arbitrary metadata."""

    path: str
    line: int = Field(ge=1)
    symbol: str = ""
    blob: str = Field(min_length=7, max_length=128, pattern=r"^[0-9a-f]+$")

    @field_validator("path")
    @classmethod
    def path_must_be_repo_relative(cls, value: str) -> str:
        normalized = value.replace("\\", "/")
        parts = normalized.split("/")
        if (
            not normalized
            or normalized.startswith("/")
            or ":" in parts[0]
            or any(part in {"", ".", ".."} for part in parts)
        ):
            raise ValueError("evidence path must be a normalized repository-relative path")
        return normalized


class GraphState(StrictModel):
    existence: ExistenceState = ExistenceState.OBSERVED
    health: HealthState = HealthState.UNKNOWN
    lifecycle: LifecycleState = LifecycleState.ACTIVE
    evidence: EvidenceState = EvidenceState.STATIC


class GraphNode(StrictModel):
    id: str = Field(min_length=3)
    kind: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    key: str = Field(min_length=1)
    label: str = Field(min_length=1)
    state: GraphState = Field(default_factory=GraphState)
    attrs: dict[str, Any] = Field(default_factory=dict)
    evidence: list[EvidenceRef] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)

    @field_validator("evidence")
    @classmethod
    def evidence_is_unique(cls, value: list[EvidenceRef]) -> list[EvidenceRef]:
        keys = [(item.path, item.line, item.symbol, item.blob) for item in value]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate evidence coordinate")
        return value


class GraphEdge(StrictModel):
    id: str = Field(min_length=3)
    relation: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    source: str = Field(min_length=3)
    target: str = Field(min_length=3)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    state: GraphState = Field(default_factory=GraphState)
    attrs: dict[str, Any] = Field(default_factory=dict)
    evidence: list[EvidenceRef] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)


class SourceResult(StrictModel):
    collector_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]*$")
    version: str = Field(min_length=1)
    status: SourceStatus
    reason_code: str = Field(default="", pattern=r"^[a-z0-9_]*$")
    retryable: bool = False


class CollectorDiagnostic(StrictModel):
    fingerprint: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    code: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    severity: Literal["warning", "unknown"]
    collector_id: str
    evidence: list[EvidenceRef] = Field(default_factory=list)


class GraphSnapshotContent(StrictModel):
    schema_version: Literal[1] = 1
    commit: str = Field(pattern=r"^[0-9a-f]{40,64}$")
    definition_revision: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    collector_versions: dict[str, str]
    feature_ids: list[str]
    source_results: list[SourceResult]
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    diagnostics: list[CollectorDiagnostic] = Field(default_factory=list)

    @model_validator(mode="after")
    def graph_references_are_valid(self) -> "GraphSnapshotContent":
        node_ids = [node.id for node in self.nodes]
        edge_ids = [edge.id for edge in self.edges]
        source_ids = [source.collector_id for source in self.source_results]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("duplicate graph node id")
        if len(edge_ids) != len(set(edge_ids)):
            raise ValueError("duplicate graph edge id")
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("duplicate source result")
        known = set(node_ids)
        dangling = [edge.id for edge in self.edges if edge.source not in known or edge.target not in known]
        if dangling:
            raise ValueError(f"edges reference unknown nodes: {dangling}")
        return self


class GraphSnapshot(StrictModel):
    schema_version: Literal[1] = 1
    snapshot_id: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    generated_at_utc: datetime
    content: GraphSnapshotContent

    @model_validator(mode="after")
    def ids_match(self) -> "GraphSnapshot":
        if self.snapshot_id != self.content_hash:
            raise ValueError("snapshot_id must equal content_hash")
        return self


class GraphDiff(StrictModel):
    schema_version: Literal[1] = 1
    from_snapshot: str
    to_snapshot: str
    added_nodes: list[str] = Field(default_factory=list)
    changed_nodes: list[str] = Field(default_factory=list)
    removed_nodes: list[str] = Field(default_factory=list)
    unknown_nodes: list[str] = Field(default_factory=list)
    added_edges: list[str] = Field(default_factory=list)
    changed_edges: list[str] = Field(default_factory=list)
    removed_edges: list[str] = Field(default_factory=list)
    unknown_edges: list[str] = Field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not any(
            (
                self.added_nodes,
                self.changed_nodes,
                self.removed_nodes,
                self.unknown_nodes,
                self.added_edges,
                self.changed_edges,
                self.removed_edges,
                self.unknown_edges,
            )
        )
