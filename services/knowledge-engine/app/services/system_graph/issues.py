"""Durable, searchable S4 issue history for planned/fact repair cards."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Iterable

from pydantic import Field

from app.schemas.system_graph import EvidenceClassification, StrictModel
from app.services.system_graph.planned import PlannedFactReport, RepairCard


class IssueStatus(StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    SNOOZED = "snoozed"
    RESOLVED = "resolved"


class IssueEvent(StrictModel):
    sequence: int = Field(ge=1)
    status: IssueStatus
    actor: str = Field(min_length=1)
    reason: str = ""
    observed_at_utc: datetime


class SystemGraphIssue(StrictModel):
    fingerprint: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    code: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    severity: str = Field(pattern=r"^(warning|unknown|blocking)$")
    classification: EvidenceClassification
    change_id: str = Field(min_length=1)
    observed: str
    expected: str
    impact_paths: list[str]
    evidence_refs: list[str]
    suggested_locations: list[str]
    verification_command: str
    first_seen_snapshot: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    last_seen_snapshot: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    occurrences: int = Field(ge=1)
    revision: int = Field(ge=1)
    status: IssueStatus
    history: list[IssueEvent]


class IssueConflict(ValueError):
    pass


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class IssueStore:
    """One immutable-identity JSON document per fingerprint.

    Replacement is atomic.  Status updates use an explicit revision check so a
    stale UI cannot overwrite a newer acknowledgement or resolution.
    """

    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, fingerprint: str) -> Path:
        token = fingerprint.removeprefix("sha256:")
        if len(token) != 64 or any(ch not in "0123456789abcdef" for ch in token):
            raise ValueError("invalid issue fingerprint")
        return self.root / f"sha256-{token}.json"

    def _write(self, issue: SystemGraphIssue) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self._path(issue.fingerprint)
        temporary = path.with_suffix(f".{os.getpid()}.tmp")
        temporary.write_text(
            json.dumps(issue.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
        return path

    def get(self, fingerprint: str) -> SystemGraphIssue:
        path = self._path(fingerprint)
        if not path.is_file():
            raise KeyError(fingerprint)
        return SystemGraphIssue.model_validate_json(path.read_text(encoding="utf-8"))

    def upsert_report(
        self, report: PlannedFactReport, *, actor: str = "system-graph-scanner", now: datetime | None = None
    ) -> list[SystemGraphIssue]:
        observed_at = now or _utc_now()
        values: list[SystemGraphIssue] = []
        for card in report.issues:
            try:
                current = self.get(card.fingerprint)
            except KeyError:
                current = None
            if current is None:
                issue = SystemGraphIssue(
                    **card.model_dump(mode="python"),
                    change_id=report.change_id,
                    first_seen_snapshot=report.snapshot_id,
                    last_seen_snapshot=report.snapshot_id,
                    occurrences=1,
                    revision=1,
                    status=IssueStatus.OPEN,
                    history=[
                        IssueEvent(
                            sequence=1,
                            status=IssueStatus.OPEN,
                            actor=actor,
                            reason="observed",
                            observed_at_utc=observed_at,
                        )
                    ],
                )
            else:
                history = list(current.history)
                status = current.status
                if status is IssueStatus.RESOLVED:
                    status = IssueStatus.OPEN
                    history.append(
                        IssueEvent(
                            sequence=len(history) + 1,
                            status=status,
                            actor=actor,
                            reason="reopened_after_recurrence",
                            observed_at_utc=observed_at,
                        )
                    )
                issue = current.model_copy(
                    update={
                        **card.model_dump(mode="python"),
                        "last_seen_snapshot": report.snapshot_id,
                        "occurrences": current.occurrences + 1,
                        "revision": current.revision + 1,
                        "status": status,
                        "history": history,
                    }
                )
            self._write(issue)
            values.append(issue)
        return values

    def list(
        self,
        *,
        status: IssueStatus | None = None,
        code: str | None = None,
        query: str = "",
    ) -> list[SystemGraphIssue]:
        if not self.root.is_dir():
            return []
        needle = query.casefold().strip()
        values: list[SystemGraphIssue] = []
        for path in sorted(self.root.glob("sha256-*.json")):
            try:
                issue = SystemGraphIssue.model_validate_json(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if status is not None and issue.status is not status:
                continue
            if code and issue.code != code:
                continue
            haystack = " ".join((issue.code, issue.observed, issue.expected, *issue.impact_paths)).casefold()
            if needle and needle not in haystack:
                continue
            values.append(issue)
        return values

    def transition(
        self,
        fingerprint: str,
        *,
        expected_revision: int,
        status: IssueStatus,
        actor: str,
        reason: str,
        now: datetime | None = None,
    ) -> SystemGraphIssue:
        current = self.get(fingerprint)
        if current.revision != expected_revision:
            raise IssueConflict("issue revision conflict; reload the latest issue")
        if current.status is status:
            return current
        event = IssueEvent(
            sequence=len(current.history) + 1,
            status=status,
            actor=actor,
            reason=reason,
            observed_at_utc=now or _utc_now(),
        )
        updated = current.model_copy(
            update={
                "status": status,
                "revision": current.revision + 1,
                "history": [*current.history, event],
            }
        )
        self._write(updated)
        return updated


def default_issue_store() -> IssueStore:
    return IssueStore(Path(os.environ.get("OMNI_SYSTEM_GRAPH_ISSUE_ROOT", ".omni/system-graph/issues")))
