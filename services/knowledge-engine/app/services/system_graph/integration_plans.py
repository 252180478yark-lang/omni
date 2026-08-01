"""S5 owner co-design plans with durable revisions and cross-process CAS."""

from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import yaml
from pydantic import Field, model_validator

from app.schemas.system_graph import (
    EvidenceClassification,
    IntegrationPlanState,
    PlanDecision,
    PlanReviewStatus,
    SourceStatus,
    StrictModel,
)
from app.services.system_graph.canonical import sha256_value
from app.services.system_graph.snapshots import read_snapshot


CO_DESIGN_LAYERS = (
    "page",
    "skill",
    "model",
    "bff",
    "api",
    "mcp_tool",
    "service",
    "table_field",
    "source",
    "test",
    "permission",
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _plan_items(items: Iterable[PlanItem | dict[str, object]]) -> list[PlanItem]:
    return [item if isinstance(item, PlanItem) else PlanItem.model_validate(item) for item in items]


class PlanItem(StrictModel):
    item_id: str = Field(min_length=1)
    layer: str = Field(min_length=1)
    target_ref: str = Field(min_length=1)
    decision: PlanDecision
    evidence_class: EvidenceClassification
    evidence_refs: list[str] = Field(default_factory=list)
    recommendation: str = ""
    rationale: str = ""
    missing_evidence: str = ""
    verification: str = Field(min_length=1)
    risk: str = Field(pattern=r"^R[0-3]$")
    critical: bool = False
    review_status: PlanReviewStatus = PlanReviewStatus.PENDING
    review_note: str = ""

    @model_validator(mode="after")
    def evidence_and_review_are_explicit(self) -> "PlanItem":
        if self.evidence_class is EvidenceClassification.OBSERVED_FACT and not self.evidence_refs:
            raise ValueError("observed_fact plan items require snapshot evidence_refs")
        if self.evidence_class is EvidenceClassification.RECOMMENDATION and not (
            self.rationale.strip() or self.recommendation.strip()
        ):
            raise ValueError("recommendation plan items require a rationale")
        if self.evidence_class is EvidenceClassification.HYPOTHESIS and not self.missing_evidence.strip():
            raise ValueError("hypothesis plan items must name missing evidence")
        if self.review_status is PlanReviewStatus.REJECTED and self.decision is not PlanDecision.NOT_DO:
            raise ValueError("rejected plan items must use not_do")
        if self.review_status is PlanReviewStatus.REWRITTEN and not self.review_note.strip():
            raise ValueError("rewritten plan items require a review_note")
        return self


class IntegrationPlanRevision(StrictModel):
    plan_id: str = Field(pattern=r"^plan-[0-9a-f]{16}$")
    feature_id: str = Field(min_length=1)
    base_snapshot_id: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    intent_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    revision: int = Field(ge=1)
    state: IntegrationPlanState
    items: list[PlanItem]
    snapshot_status: str = Field(pattern=r"^(complete|partial)$")
    missing_sources: list[str] = Field(default_factory=list)
    actor_id: str = Field(min_length=1)
    created_at_utc: datetime
    updated_at_utc: datetime
    confirmed_request_id: str | None = None
    archived_reason: str = ""


class PlanConflict(ValueError):
    pass


class PlanStale(ValueError):
    def __init__(self, message: str, revision: IntegrationPlanRevision | None = None) -> None:
        super().__init__(message)
        self.revision = revision


class UnresolvedCriticalUnknown(ValueError):
    pass


def default_plan_items(feature_id: str) -> list[PlanItem]:
    return [
        PlanItem(
            item_id=layer,
            layer=layer,
            target_ref=f"candidate:{feature_id}:{layer}",
            decision=PlanDecision.UNKNOWN,
            evidence_class=EvidenceClassification.HYPOTHESIS,
            missing_evidence=f"No verified {layer} evidence has been selected yet.",
            verification=f"Resolve the {layer} layer against the immutable base snapshot.",
            risk="R2" if layer in {"api", "mcp_tool", "table_field", "permission"} else "R1",
            critical=True,
        )
        for layer in CO_DESIGN_LAYERS
    ]


def plan_summary(plan: IntegrationPlanRevision) -> dict[str, object]:
    return {
        "facts": sum(item.evidence_class is EvidenceClassification.OBSERVED_FACT for item in plan.items),
        "recommendations": sum(item.evidence_class is EvidenceClassification.RECOMMENDATION for item in plan.items),
        "hypotheses": sum(item.evidence_class is EvidenceClassification.HYPOTHESIS for item in plan.items),
        "pending_reviews": sum(item.review_status is PlanReviewStatus.PENDING for item in plan.items),
        "critical_unknowns": sum(item.critical and item.decision is PlanDecision.UNKNOWN for item in plan.items),
        "snapshot_status": plan.snapshot_status,
        "missing_sources": plan.missing_sources,
    }


@dataclass
class PlanStore:
    revisions: dict[str, list[IntegrationPlanRevision]] = field(default_factory=dict)
    confirmations: dict[tuple[str, str], IntegrationPlanRevision] = field(default_factory=dict)

    def create_or_reuse(
        self,
        *,
        feature_id: str,
        base_snapshot_id: str,
        intent: str,
        items: Iterable[PlanItem],
        snapshot_status: str = "complete",
        missing_sources: Iterable[str] = (),
        actor_id: str = "system",
        now: datetime | None = None,
    ) -> IntegrationPlanRevision:
        intent_hash = sha256_value({"feature_id": feature_id, "intent": intent})
        plan_id = "plan-" + sha256_value(
            {"feature_id": feature_id, "base_snapshot_id": base_snapshot_id, "intent_hash": intent_hash}
        ).split(":", 1)[1][:16]
        existing = self.revisions.get(plan_id, [])
        active = next(
            (
                item
                for item in reversed(existing)
                if item.state in {IntegrationPlanState.DRAFT, IntegrationPlanState.REVIEWING}
            ),
            None,
        )
        if active is not None:
            return copy.deepcopy(active)
        observed_at = now or _utc_now()
        revision = IntegrationPlanRevision(
            plan_id=plan_id,
            feature_id=feature_id,
            base_snapshot_id=base_snapshot_id,
            intent_hash=intent_hash,
            revision=(existing[-1].revision + 1) if existing else 1,
            state=IntegrationPlanState.DRAFT,
            items=_plan_items(items),
            snapshot_status=snapshot_status,
            missing_sources=list(missing_sources),
            actor_id=actor_id,
            created_at_utc=observed_at,
            updated_at_utc=observed_at,
        )
        self.revisions.setdefault(plan_id, []).append(revision)
        return copy.deepcopy(revision)

    def latest(self, plan_id: str) -> IntegrationPlanRevision:
        if not self.revisions.get(plan_id):
            raise KeyError(plan_id)
        return copy.deepcopy(self.revisions[plan_id][-1])

    def list(self, *, state: IntegrationPlanState | None = None) -> list[IntegrationPlanRevision]:
        values = [items[-1] for items in self.revisions.values() if items]
        if state is not None:
            values = [item for item in values if item.state is state]
        return [copy.deepcopy(item) for item in sorted(values, key=lambda item: item.updated_at_utc, reverse=True)]

    def patch(
        self,
        *,
        plan_id: str,
        expected_revision: int,
        items: Iterable[PlanItem],
        current_snapshot_id: str,
        actor_id: str = "system",
        now: datetime | None = None,
    ) -> IntegrationPlanRevision:
        current = self.latest(plan_id)
        if current.base_snapshot_id != current_snapshot_id:
            stale = self.mark_stale(plan_id=plan_id, expected_revision=expected_revision, actor_id=actor_id, now=now)
            raise PlanStale("base snapshot changed; rebase and reconfirm the candidate plan", stale)
        if current.revision != expected_revision:
            raise PlanConflict("revision conflict; reload the latest plan revision")
        if current.state not in {IntegrationPlanState.DRAFT, IntegrationPlanState.REVIEWING}:
            raise PlanConflict("only draft or reviewing plans can be edited")
        updated = current.model_copy(
            update={
                "revision": current.revision + 1,
                "state": IntegrationPlanState.REVIEWING,
                "items": _plan_items(items),
                "actor_id": actor_id,
                "updated_at_utc": now or _utc_now(),
            }
        )
        self.revisions[plan_id].append(updated)
        return copy.deepcopy(updated)

    def mark_stale(
        self,
        *,
        plan_id: str,
        expected_revision: int,
        actor_id: str,
        now: datetime | None = None,
    ) -> IntegrationPlanRevision:
        current = self.latest(plan_id)
        if current.revision != expected_revision:
            raise PlanConflict("revision conflict; reload the latest plan revision")
        stale = current.model_copy(
            update={
                "revision": current.revision + 1,
                "state": IntegrationPlanState.STALE,
                "actor_id": actor_id,
                "updated_at_utc": now or _utc_now(),
            }
        )
        self.revisions[plan_id].append(stale)
        return copy.deepcopy(stale)

    def rebase(
        self,
        *,
        plan_id: str,
        expected_revision: int,
        base_snapshot_id: str,
        snapshot_status: str,
        missing_sources: Iterable[str],
        actor_id: str,
        items: Iterable[PlanItem] | None = None,
        now: datetime | None = None,
    ) -> IntegrationPlanRevision:
        current = self.latest(plan_id)
        if current.revision != expected_revision:
            raise PlanConflict("revision conflict; reload the latest plan revision")
        if current.state is IntegrationPlanState.ARCHIVED:
            raise PlanConflict("archived plans must be reopened as a new draft")
        selected = _plan_items(items) if items is not None else [
            item.model_copy(update={"review_status": PlanReviewStatus.PENDING, "review_note": ""})
            for item in current.items
        ]
        rebased = current.model_copy(
            update={
                "revision": current.revision + 1,
                "base_snapshot_id": base_snapshot_id,
                "state": IntegrationPlanState.REVIEWING,
                "items": selected,
                "snapshot_status": snapshot_status,
                "missing_sources": list(missing_sources),
                "actor_id": actor_id,
                "updated_at_utc": now or _utc_now(),
                "confirmed_request_id": None,
            }
        )
        self.revisions[plan_id].append(rebased)
        return copy.deepcopy(rebased)

    def archive(
        self,
        *,
        plan_id: str,
        expected_revision: int,
        actor_id: str,
        reason: str,
        now: datetime | None = None,
    ) -> IntegrationPlanRevision:
        current = self.latest(plan_id)
        if current.revision != expected_revision:
            raise PlanConflict("revision conflict; reload the latest plan revision")
        if current.state is IntegrationPlanState.ARCHIVED:
            return current
        archived = current.model_copy(
            update={
                "revision": current.revision + 1,
                "state": IntegrationPlanState.ARCHIVED,
                "actor_id": actor_id,
                "archived_reason": reason,
                "updated_at_utc": now or _utc_now(),
            }
        )
        self.revisions[plan_id].append(archived)
        return copy.deepcopy(archived)

    def confirm(
        self,
        *,
        plan_id: str,
        expected_revision: int,
        request_id: str,
        current_snapshot_id: str,
        confirmed: bool,
        actor_id: str = "system",
        now: datetime | None = None,
    ) -> IntegrationPlanRevision:
        duplicate = self.confirmations.get((plan_id, request_id))
        if duplicate is not None:
            return copy.deepcopy(duplicate)
        if not confirmed:
            raise ValueError("explicit user confirmation is required")
        current = self.latest(plan_id)
        if current.base_snapshot_id != current_snapshot_id:
            stale = self.mark_stale(plan_id=plan_id, expected_revision=expected_revision, actor_id=actor_id, now=now)
            raise PlanStale("base snapshot changed; rebase and reconfirm the candidate plan", stale)
        if current.revision != expected_revision:
            raise PlanConflict("revision conflict; reload the latest plan revision")
        if current.state is not IntegrationPlanState.REVIEWING:
            raise PlanConflict("plan must be reviewing before confirmation")
        critical_unknown = [
            item.item_id for item in current.items if item.critical and item.decision is PlanDecision.UNKNOWN
        ]
        if critical_unknown:
            raise UnresolvedCriticalUnknown(
                "critical unknown plan items prevent IMPACT_LOCKED: " + ", ".join(critical_unknown)
            )
        unreviewed = [
            item.item_id
            for item in current.items
            if item.decision in {PlanDecision.ADD, PlanDecision.MODIFY}
            and item.review_status not in {PlanReviewStatus.ACCEPTED, PlanReviewStatus.REWRITTEN}
        ]
        if unreviewed:
            raise ValueError("add/modify plan items require owner acceptance: " + ", ".join(unreviewed))
        frozen = current.model_copy(
            update={
                "revision": current.revision + 1,
                "state": IntegrationPlanState.FROZEN,
                "confirmed_request_id": request_id,
                "actor_id": actor_id,
                "updated_at_utc": now or _utc_now(),
            }
        )
        self.revisions[plan_id].append(frozen)
        self.confirmations[(plan_id, request_id)] = frozen
        return copy.deepcopy(frozen)


class FilePlanStore(PlanStore):
    """Immutable revision files; exclusive create is the cross-process CAS."""

    def __init__(self, root: Path) -> None:
        super().__init__()
        self.root = root
        self._load_existing()

    def _load_existing(self) -> None:
        if not self.root.is_dir():
            return
        for path in sorted(self.root.glob("plan-*/revision-*.json")):
            try:
                revision = IntegrationPlanRevision.model_validate_json(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            revisions = self.revisions.setdefault(revision.plan_id, [])
            if not any(item.revision == revision.revision for item in revisions):
                revisions.append(revision)
            if revision.confirmed_request_id:
                self.confirmations[(revision.plan_id, revision.confirmed_request_id)] = revision
        for revisions in self.revisions.values():
            revisions.sort(key=lambda item: item.revision)

    def persist(self, revision: IntegrationPlanRevision) -> Path:
        directory = self.root / revision.plan_id
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"revision-{revision.revision}.json"
        payload = json.dumps(revision.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        try:
            with path.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(payload)
        except FileExistsError as exc:
            try:
                current = path.read_text(encoding="utf-8")
            except OSError:
                current = ""
            if current != payload:
                raise PlanConflict("revision conflict; another process committed this revision") from exc
        return path

    def create_or_reuse(self, **kwargs) -> IntegrationPlanRevision:  # type: ignore[override]
        revision = super().create_or_reuse(**kwargs)
        try:
            self.persist(revision)
            return revision
        except PlanConflict:
            fresh = FilePlanStore(self.root).latest(revision.plan_id)
            if (
                fresh.feature_id == revision.feature_id
                and fresh.base_snapshot_id == revision.base_snapshot_id
                and fresh.intent_hash == revision.intent_hash
                and fresh.state in {IntegrationPlanState.DRAFT, IntegrationPlanState.REVIEWING}
            ):
                return fresh
            raise

    def patch(self, **kwargs) -> IntegrationPlanRevision:  # type: ignore[override]
        revision = super().patch(**kwargs)
        self.persist(revision)
        return revision

    def mark_stale(self, **kwargs) -> IntegrationPlanRevision:  # type: ignore[override]
        revision = super().mark_stale(**kwargs)
        self.persist(revision)
        return revision

    def rebase(self, **kwargs) -> IntegrationPlanRevision:  # type: ignore[override]
        revision = super().rebase(**kwargs)
        self.persist(revision)
        return revision

    def archive(self, **kwargs) -> IntegrationPlanRevision:  # type: ignore[override]
        revision = super().archive(**kwargs)
        self.persist(revision)
        return revision

    def confirm(self, **kwargs) -> IntegrationPlanRevision:  # type: ignore[override]
        revision = super().confirm(**kwargs)
        self.persist(revision)
        return revision

    def persist_impact_draft(self, plan: IntegrationPlanRevision, draft: dict[str, object]) -> Path:
        directory = self.root / plan.plan_id
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"impact-draft-r{plan.revision}.yaml"
        payload = yaml.safe_dump(draft, allow_unicode=True, sort_keys=False)
        try:
            with path.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(payload)
        except FileExistsError:
            if path.read_text(encoding="utf-8") != payload:
                raise PlanConflict("impact draft already exists with different content")
        return path


@dataclass
class IntegrationPlanService:
    store: PlanStore
    snapshot_root: Path

    def _snapshot(self, snapshot_id: str) -> tuple[str, str, list[str]]:
        path = self.snapshot_root / (snapshot_id.replace(":", "-") + ".json")
        try:
            snapshot = read_snapshot(path)
        except (OSError, ValueError) as exc:
            raise PlanStale("immutable base snapshot is unavailable; rescan before planning") from exc
        if snapshot.snapshot_id != snapshot_id:
            raise PlanStale("immutable base snapshot identity mismatch; rescan before planning")
        failed = [
            result.collector_id
            for result in snapshot.content.source_results
            if result.status is not SourceStatus.SUCCESS
        ]
        if not snapshot.content.source_results:
            failed = ["snapshot_sources_unavailable"]
        return snapshot.snapshot_id, "partial" if failed else "complete", failed

    def create(
        self,
        *,
        feature_id: str,
        base_snapshot_id: str,
        intent: str,
        items: Iterable[PlanItem],
        actor_id: str = "system",
    ) -> IntegrationPlanRevision:
        snapshot_id, status, missing = self._snapshot(base_snapshot_id)
        selected = _plan_items(items) or default_plan_items(feature_id)
        return self.store.create_or_reuse(
            feature_id=feature_id,
            base_snapshot_id=snapshot_id,
            intent=intent,
            items=selected,
            snapshot_status=status,
            missing_sources=missing,
            actor_id=actor_id,
        )

    def latest(self, plan_id: str) -> IntegrationPlanRevision:
        return self.store.latest(plan_id)

    def list(self, *, state: IntegrationPlanState | None = None) -> list[IntegrationPlanRevision]:
        return self.store.list(state=state)

    def patch(self, *, plan_id: str, expected_revision: int, current_snapshot_id: str, items: Iterable[PlanItem], actor_id: str = "system") -> IntegrationPlanRevision:
        snapshot_id, _, _ = self._snapshot(current_snapshot_id)
        return self.store.patch(
            plan_id=plan_id,
            expected_revision=expected_revision,
            current_snapshot_id=snapshot_id,
            items=items,
            actor_id=actor_id,
        )

    def rebase(self, *, plan_id: str, expected_revision: int, base_snapshot_id: str, items: Iterable[PlanItem] | None, actor_id: str) -> IntegrationPlanRevision:
        snapshot_id, status, missing = self._snapshot(base_snapshot_id)
        return self.store.rebase(
            plan_id=plan_id,
            expected_revision=expected_revision,
            base_snapshot_id=snapshot_id,
            snapshot_status=status,
            missing_sources=missing,
            items=items,
            actor_id=actor_id,
        )

    def archive(self, *, plan_id: str, expected_revision: int, reason: str, actor_id: str) -> IntegrationPlanRevision:
        return self.store.archive(
            plan_id=plan_id,
            expected_revision=expected_revision,
            reason=reason,
            actor_id=actor_id,
        )

    def confirm(self, *, plan_id: str, expected_revision: int, current_snapshot_id: str, request_id: str, confirmed: bool, actor_id: str = "system") -> tuple[IntegrationPlanRevision, dict[str, object]]:
        snapshot_id, _, _ = self._snapshot(current_snapshot_id)
        frozen = self.store.confirm(
            plan_id=plan_id,
            expected_revision=expected_revision,
            current_snapshot_id=snapshot_id,
            request_id=request_id,
            confirmed=confirmed,
            actor_id=actor_id,
        )
        draft = project_confirmed_plan(frozen)
        if isinstance(self.store, FilePlanStore):
            artifact = self.store.persist_impact_draft(frozen, draft)
            draft["artifact_path"] = artifact.as_posix()
        return frozen, draft


def default_integration_plan_service() -> IntegrationPlanService:
    root = Path(os.environ.get("OMNI_SYSTEM_GRAPH_PLAN_ROOT", ".omni/system-graph/integration-plans"))
    snapshots = Path(os.environ.get("OMNI_SYSTEM_GRAPH_SNAPSHOT_ROOT", "output/system-graph/snapshots"))
    return IntegrationPlanService(store=FilePlanStore(root), snapshot_root=snapshots)


def create_candidate_plan(service: IntegrationPlanService, *, feature_id: str, base_snapshot_id: str, intent: str, items: Iterable[PlanItem], actor_id: str = "system") -> IntegrationPlanRevision:
    return service.create(
        feature_id=feature_id,
        base_snapshot_id=base_snapshot_id,
        intent=intent,
        items=items,
        actor_id=actor_id,
    )


def project_confirmed_plan(plan: IntegrationPlanRevision) -> dict[str, object]:
    if plan.state is not IntegrationPlanState.FROZEN:
        raise ValueError("only a frozen, explicitly confirmed revision can project an impact draft")
    planned_changes = [
        {
            "id": f"PLAN-{item.item_id}",
            "action": item.decision.value,
            "kind": item.layer,
            "node_id": item.target_ref,
            "paths": [],
            "upstream": [],
            "downstream": [],
            "contract_change": "compatible",
            "verification": item.verification,
            "risk": item.risk,
            "evidence_refs": item.evidence_refs,
        }
        for item in plan.items
        if item.decision is not PlanDecision.NOT_DO
    ]
    return {
        "schema_version": 3,
        "change_id": f"candidate-{plan.plan_id}",
        "state": "DISCOVERED",
        "feature_refs": [{"feature_id": plan.feature_id, "feature_ref": plan.plan_id}],
        "before_snapshot": {"ref": plan.base_snapshot_id},
        "plan_revision": plan.revision,
        "current_chain": {"nodes": [], "edges": [], "evidence": sorted({ref for item in plan.items for ref in item.evidence_refs})},
        "planned_changes": planned_changes,
        "expected_graph_diff": [item.target_ref for item in plan.items if item.decision is PlanDecision.ADD],
        "tests": [item.verification for item in plan.items if item.decision is not PlanDecision.NOT_DO],
        "migration": {"required": any(item.layer == "table_field" and item.decision in {PlanDecision.ADD, PlanDecision.MODIFY} for item in plan.items)},
        "permissions": [item.target_ref for item in plan.items if item.layer == "permission" and item.decision is not PlanDecision.NOT_DO],
        "risk": {"level": max((item.risk for item in plan.items), default="R1"), "approval_required": any(item.risk == "R3" for item in plan.items)},
        "rollback": {"strategy": "Revert the adopted implementation change and preserve immutable plan revisions."},
        "requires_user_confirmation": False,
        "product_write_performed": False,
    }
