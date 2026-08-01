"""S6 pilot calibration that is safe to run entirely from deterministic fixtures."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from app.schemas.system_graph import EvidenceClassification
from app.services.system_graph.planned import PlannedFactReport, RepairCard


@dataclass(frozen=True)
class PilotResult:
    risk_level: str
    state: str
    selected_block_codes: tuple[str, ...]
    blocking_fingerprints: tuple[str, ...]
    effect_executed: bool


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
