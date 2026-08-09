"""Strict request/response contracts for durable Workbench context snapshots."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import Field, field_validator, model_validator

from app.schemas.runtime_trace import IDENTIFIER, StrictModel
from app.schemas.workbench_foundation import WorkbenchContextSnapshot


class WorkbenchContextInput(StrictModel):
    context_ref: str = Field(pattern=IDENTIFIER)
    workspace_ref: str = Field(pattern=IDENTIFIER)
    shop_ref: str | None = Field(default=None, pattern=IDENTIFIER)
    sku_ref: str | None = Field(default=None, pattern=IDENTIFIER)
    project_ref: str | None = Field(default=None, pattern=IDENTIFIER)
    environment_ref: str | None = Field(default=None, pattern=IDENTIFIER)
    task_ref: str | None = Field(default=None, pattern=IDENTIFIER)
    evidence_refs: list[str] = Field(default_factory=list, max_length=100)
    origin_surface_ref: str = Field(pattern=IDENTIFIER)
    availability: Literal["available", "unavailable"] = "available"
    rebind_reason: str | None = Field(
        default=None,
        pattern=r"^[a-z][a-z0-9_.-]{0,99}$",
    )

    @field_validator(
        "context_ref",
        "workspace_ref",
        "shop_ref",
        "sku_ref",
        "project_ref",
        "environment_ref",
        "task_ref",
        "origin_surface_ref",
    )
    @classmethod
    def references_never_expose_raw_paths(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if re.search(r":[\\/]", value) and re.fullmatch(
            r"ui_route:/[A-Za-z0-9._/-]*",
            value,
        ) is None:
            raise ValueError("workbench references must not expose a raw path")
        return value

    @field_validator("evidence_refs")
    @classmethod
    def evidence_refs_are_unique_identifiers(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("evidence_refs must be unique")
        for ref in value:
            if re.fullmatch(IDENTIFIER, ref) is None:
                raise ValueError("evidence_refs must contain stable identifiers")
        return value


class WorkbenchContextResolveRequest(StrictModel):
    context: WorkbenchContextInput
    expected_snapshot_id: str | None = Field(default=None, pattern=IDENTIFIER)
    expected_revision: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def expected_pair_is_complete(self):
        if (self.expected_snapshot_id is None) != (self.expected_revision is None):
            raise ValueError("expected_snapshot_id and expected_revision must be supplied together")
        return self


class WorkbenchContextResult(StrictModel):
    snapshot: WorkbenchContextSnapshot
    reused: bool
