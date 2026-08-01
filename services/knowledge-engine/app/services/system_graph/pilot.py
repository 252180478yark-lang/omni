"""S6 pilot calibration and repository-backed evidence contracts.

The helpers in this module never claim delivery.  R1/R2 can prove a local
candidate against real repository paths, while R3 deliberately stops after a
pending approval operation has been persisted without an effect handler.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from pydantic import Field, field_validator

from app.schemas.system_graph import EvidenceClassification, StrictModel
from app.services.system_graph.planned import PlannedFactReport, RepairCard


@dataclass(frozen=True)
class PilotResult:
    risk_level: str
    state: str
    selected_block_codes: tuple[str, ...]
    blocking_fingerprints: tuple[str, ...]
    effect_executed: bool


class PilotCommand(StrictModel):
    working_directory: str = "."
    argv: list[str] = Field(min_length=1)

    @field_validator("working_directory")
    @classmethod
    def relative_working_directory(cls, value: str) -> str:
        normalized = value.replace("\\", "/").strip("/") or "."
        if normalized == ".." or normalized.startswith("../"):
            raise ValueError("pilot working directory must remain inside the repository")
        return normalized


class RepositoryPilot(StrictModel):
    pilot_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    risk_level: str = Field(pattern=r"^R[123]$")
    purpose: str = Field(min_length=1)
    candidate_paths: list[str] = Field(min_length=1)
    allocation_paths: list[str] = Field(default_factory=list)
    commands: list[PilotCommand] = Field(default_factory=list)
    selected_block_codes: list[str] = Field(default_factory=list)
    approval_handler: str = ""
    approval_target: str = ""

    @field_validator("candidate_paths", "allocation_paths")
    @classmethod
    def repository_relative_paths(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            path = value.replace("\\", "/").strip("/")
            if not path or path == ".." or path.startswith("../"):
                raise ValueError("pilot paths must remain inside the repository")
            normalized.append(path)
        return normalized


class PilotManifest(StrictModel):
    schema_version: int = Field(ge=1, le=1)
    pilots: list[RepositoryPilot] = Field(min_length=3)

    @field_validator("pilots")
    @classmethod
    def contains_one_pilot_per_risk_level(cls, values: list[RepositoryPilot]) -> list[RepositoryPilot]:
        levels = [value.risk_level for value in values]
        if sorted(levels) != ["R1", "R2", "R3"]:
            raise ValueError("S6 manifest must contain exactly one R1, R2, and R3 pilot")
        if len({value.pilot_id for value in values}) != len(values):
            raise ValueError("pilot_id values must be unique")
        for value in values:
            if value.risk_level in {"R1", "R2"} and (not value.commands or not value.allocation_paths):
                raise ValueError("R1/R2 pilots require commands and isolated allocation paths")
            if value.risk_level == "R3" and (not value.approval_handler or not value.approval_target):
                raise ValueError("R3 pilot requires an approval handler and target")
        return values


def validate_repository_paths(root: Path, pilot: RepositoryPilot) -> tuple[str, ...]:
    """Return verified repository-relative paths without following paths outside root."""

    resolved_root = root.resolve()
    verified: list[str] = []
    for relative in pilot.candidate_paths:
        candidate = (resolved_root / relative).resolve()
        try:
            candidate.relative_to(resolved_root)
        except ValueError as exc:
            raise ValueError(f"pilot path escapes repository: {relative}") from exc
        if not candidate.exists():
            raise ValueError(f"pilot candidate path does not exist: {relative}")
        verified.append(relative)
    return tuple(verified)


def eligible_block_codes(issues: Iterable[RepairCard]) -> tuple[str, ...]:
    """Only deterministic observed facts may be calibrated into a block."""

    return tuple(
        sorted(
            {
                issue.code
                for issue in issues
                if issue.classification is EvidenceClassification.OBSERVED_FACT
                and issue.code == "required_edge_missing"
            }
        )
    )


def run_r1_r2_pilot(
    report: PlannedFactReport, *, risk_level: str, selected_block_codes: Iterable[str] = ()
) -> PilotResult:
    if risk_level not in {"R1", "R2"}:
        raise ValueError("R1/R2 pilot only")
    selected = tuple(sorted(set(selected_block_codes)))
    eligible = set(eligible_block_codes(report.issues))
    invalid = set(selected) - eligible
    if invalid:
        raise ValueError("only selected deterministic observed-fact codes may block: " + ", ".join(sorted(invalid)))
    blocked = tuple(
        issue.fingerprint
        for issue in report.issues
        if issue.code in selected and issue.classification is EvidenceClassification.OBSERVED_FACT
    )
    return PilotResult(
        risk_level=risk_level,
        state="blocked" if blocked else "graph_diff_ready",
        selected_block_codes=selected,
        blocking_fingerprints=blocked,
        effect_executed=False,
    )


def r3_pending_fixture(*, request_id: str, target: str, payload_hash: str) -> PilotResult:
    """A deliberately inert R3 fixture: it cannot receive or invoke an effect."""

    if not request_id or not target or not payload_hash:
        raise ValueError("R3 fixture requires request_id, target, and payload_hash")
    return PilotResult(
        risk_level="R3",
        state="waiting_approval",
        selected_block_codes=(),
        blocking_fingerprints=(),
        effect_executed=False,
    )
