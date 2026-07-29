"""Typed contracts for feature-level health and partial source failures."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HealthState(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    STALE = "stale"
    UNKNOWN = "unknown"


class OperationError(StrictModel):
    code: str
    message: str
    source: str
    status: int = Field(ge=400, le=599)
    retryable: bool = False
    details: dict[str, Any] = Field(default_factory=dict)


class BuildIdentity(StrictModel):
    expected_commit: str | None = None
    observed_commit: str | None = None
    expected_source_fingerprint: str | None = None
    source_fingerprint: str | None = None
    worktree_id: str | None = None
    allocation_id: str | None = None
    runtime_id: str | None = None


class DependencyRegistration(StrictModel):
    dependency_id: str
    base_url: str | None = None
    health_path: str = "/health"
    read_path: str | None = None
    freshness_seconds: int | None = Field(default=None, gt=0)
    expected_build: str | None = None
    expected_source_fingerprint: str | None = None
    timeout_seconds: float = Field(default=2.0, gt=0, le=30)


class ProbeResult(StrictModel):
    availability: bool | None = None
    authenticated: bool | None = None
    readable: bool | None = None
    latest_data_at: datetime | None = None
    observed_build: str | None = None
    observed_source_fingerprint: str | None = None
    observed_at: datetime
    reason_codes: list[str] = Field(default_factory=list)


class DependencyHealth(StrictModel):
    dependency_id: str
    ref: str
    required: bool
    state: HealthState
    reason_codes: list[str] = Field(default_factory=list)
    latest_data_at: datetime | None = None
    freshness_seconds: int | None = None
    build_identity: BuildIdentity = Field(default_factory=BuildIdentity)
    observed_at: datetime


class FeatureHealth(StrictModel):
    feature_id: str
    title: str
    href: str | None = None
    state: HealthState
    dependencies: list[DependencyHealth] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)


class SystemHealthResponse(StrictModel):
    schema_version: Literal[1] = 1
    state: HealthState
    healthy_percentage: float = Field(ge=0, le=100)
    partial: bool
    generated_at: datetime
    build_identity: BuildIdentity = Field(default_factory=BuildIdentity)
    features: list[FeatureHealth] = Field(default_factory=list)
    errors: list[OperationError] = Field(default_factory=list)
