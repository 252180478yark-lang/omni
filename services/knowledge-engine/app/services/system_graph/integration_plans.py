"""S5 storage-neutral candidate-plan revisions with optimistic concurrency.

The service has no product-code writer.  It creates only candidate-plan
artifacts and an in-memory impact projection after explicit confirmation.
"""

from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from pydantic import Field

from app.schemas.system_graph import (
    EvidenceClassification,
    IntegrationPlanState,
    PlanDecision,
    StrictModel,
)
from app.services.system_graph.canonical import sha256_value
from app.services.system_graph.snapshots import read_snapshot


class PlanItem(StrictModel):
    item_id: str = Field(min_length=1)
    layer: str = Field(min_length=1)
    target_ref: str = Field(min_length=1)
    decision: PlanDecision
    evidence_class: EvidenceClassification
    evidence_refs: list[str] = Field(default_factory=list)
    recommendation: str = ""
    verification: str = Field(min_length=1)
    risk: str = Field(pattern=r"^R[0-3]$")
    critical: bool = False


class IntegrationPlanRevision(StrictModel):
    plan_id: str = Field(pattern=r"^plan-[0-9a-f]{16}$")
    feature_id: str = Field(min_length=1)
    base_snapshot_id: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    intent_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    revision: int = Field(ge=1)
    state: IntegrationPlanState
    items: list[PlanItem]
    confirmed_request_id: str | None = None


class PlanConflict(ValueError):
    pass


class PlanStale(ValueError):
    pass


class UnresolvedCriticalUnknown(ValueError):
    pass


@dataclass
class PlanStore:
    """An artifact-oriented revision store; callers choose durable storage."""

    revisions: dict[str, list[IntegrationPlanRevision]] = field(default_factory=dict)
    confirmations: dict[tuple[str, str], IntegrationPlanRevision] = field(default_factory=dict)

    def create_or_reuse(
        self, *, feature_id: str, base_snapshot_id: str, intent: str, items: Iterable[PlanItem]
    ) -> IntegrationPlanRevision:
        intent_hash = sha256_value({"feature_id": feature_id, "intent": intent})
        plan_id = "plan-" + sha256_value(
            {"feature_id": feature_id, "base_snapshot_id": base_snapshot_id, "intent_hash": intent_hash}
        ).split(":", 1)[1][:16]
        existing = self.revisions.get(plan_id, [])
        draft = next((item for item in reversed(existing) if item.state is IntegrationPlanState.DRAFT), None)
        if draft is not None:
            return copy.deepcopy(draft)
        revision = IntegrationPlanRevision(
            plan_id=plan_id,
            feature_id=feature_id,
            base_snapshot_id=base_snapshot_id,
            intent_hash=intent_hash,
            revision=1,
            state=IntegrationPlanState.DRAFT,
            items=list(items),
        )
        self.revisions.setdefault(plan_id, []).append(revision)
        return copy.deepcopy(revision)

    def latest(self, plan_id: str) -> IntegrationPlanRevision:
        if not self.revisions.get(plan_id):
            raise KeyError(plan_id)
        return copy.deepcopy(self.revisions[plan_id][-1])

    def patch(
        self, *, plan_id: str, expected_revision: int, items: Iterable[PlanItem], current_snapshot_id: str
    ) -> IntegrationPlanRevision:
        current = self.latest(plan_id)
        if current.base_snapshot_id != current_snapshot_id:
            raise PlanStale("base snapshot changed; rebase and reconfirm the candidate plan")
        if current.revision != expected_revision:
            raise PlanConflict("revision conflict; reload the latest plan revision")
        if current.state is not IntegrationPlanState.DRAFT:
            raise PlanConflict("frozen plans cannot be overwritten")
        updated = current.model_copy(
            update={"revision": current.revision + 1, "items": list(items)}
        )
        self.revisions[plan_id].append(updated)
        return copy.deepcopy(updated)

    def confirm(
        self, *, plan_id: str, expected_revision: int, request_id: str, current_snapshot_id: str, confirmed: bool
    ) -> IntegrationPlanRevision:
        duplicate = self.confirmations.get((plan_id, request_id))
        if duplicate is not None:
            return copy.deepcopy(duplicate)
        if not confirmed:
            raise ValueError("explicit user confirmation is required")
        current = self.latest(plan_id)
        if current.base_snapshot_id != current_snapshot_id:
            raise PlanStale("base snapshot changed; rebase and reconfirm the candidate plan")
        if current.revision != expected_revision:
            raise PlanConflict("revision conflict; reload the latest plan revision")
        critical_unknown = [
            item.item_id
            for item in current.items
            if item.critical and item.decision is PlanDecision.UNKNOWN
        ]
        if critical_unknown:
            raise UnresolvedCriticalUnknown(
                "critical unknown plan items prevent IMPACT_LOCKED: " + ", ".join(critical_unknown)
            )
        frozen = current.model_copy(
            update={
                "revision": current.revision + 1,
                "state": IntegrationPlanState.FROZEN,
                "confirmed_request_id": request_id,
            }
        )
        self.revisions[plan_id].append(frozen)
        self.confirmations[(plan_id, request_id)] = frozen
        return copy.deepcopy(frozen)


class FilePlanStore(PlanStore):
    """Durable candidate-plan artifact adapter rooted in an explicit directory.

    This adapter never writes product code, a database, or an external system.
    Its only durable effect is a candidate-plan revision JSON file below ``root``.
    """

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
        if not path.exists():
            path.write_text(
                json.dumps(revision.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                encoding="utf-8",
            )
        return path

    def create_or_reuse(
        self, *, feature_id: str, base_snapshot_id: str, intent: str, items: Iterable[PlanItem]
    ) -> IntegrationPlanRevision:
        revision = super().create_or_reuse(
            feature_id=feature_id,
            base_snapshot_id=base_snapshot_id,
            intent=intent,
            items=items,
        )
        self.persist(revision)
        return revision

    def patch(
        self, *, plan_id: str, expected_revision: int, items: Iterable[PlanItem], current_snapshot_id: str
    ) -> IntegrationPlanRevision:
        revision = super().patch(
            plan_id=plan_id,
            expected_revision=expected_revision,
            items=items,
            current_snapshot_id=current_snapshot_id,
        )
        self.persist(revision)
        return revision

    def confirm(
        self, *, plan_id: str, expected_revision: int, request_id: str, current_snapshot_id: str, confirmed: bool
    ) -> IntegrationPlanRevision:
        revision = super().confirm(
            plan_id=plan_id,
            expected_revision=expected_revision,
            request_id=request_id,
            current_snapshot_id=current_snapshot_id,
            confirmed=confirmed,
        )
        self.persist(revision)
        return revision


@dataclass
class IntegrationPlanService:
    """S5 application service with immutable snapshot and no-product-write guards."""

    store: PlanStore
    snapshot_root: Path

    def _snapshot_id(self, snapshot_id: str) -> str:
        # Snapshot ids are schema-validated at the boundary.  Constructing the
        # filename ourselves prevents accepting a caller-supplied filesystem path.
        path = self.snapshot_root / (snapshot_id.replace(":", "-") + ".json")
        try:
            snapshot = read_snapshot(path)
        except (OSError, ValueError) as exc:
            raise PlanStale("immutable base snapshot is unavailable; rescan before planning") from exc
        if snapshot.snapshot_id != snapshot_id:
            raise PlanStale("immutable base snapshot identity mismatch; rescan before planning")
        return snapshot.snapshot_id

    def create(
        self, *, feature_id: str, base_snapshot_id: str, intent: str, items: Iterable[PlanItem]
    ) -> IntegrationPlanRevision:
        snapshot_id = self._snapshot_id(base_snapshot_id)
        return self.store.create_or_reuse(
            feature_id=feature_id,
            base_snapshot_id=snapshot_id,
            intent=intent,
            items=items,
        )

    def latest(self, plan_id: str) -> IntegrationPlanRevision:
        return self.store.latest(plan_id)

    def patch(
        self, *, plan_id: str, expected_revision: int, current_snapshot_id: str, items: Iterable[PlanItem]
    ) -> IntegrationPlanRevision:
        snapshot_id = self._snapshot_id(current_snapshot_id)
        return self.store.patch(
            plan_id=plan_id,
            expected_revision=expected_revision,
            current_snapshot_id=snapshot_id,
            items=items,
        )

    def confirm(
        self, *, plan_id: str, expected_revision: int, current_snapshot_id: str, request_id: str, confirmed: bool
    ) -> tuple[IntegrationPlanRevision, dict[str, object]]:
        snapshot_id = self._snapshot_id(current_snapshot_id)
        frozen = self.store.confirm(
            plan_id=plan_id,
            expected_revision=expected_revision,
            current_snapshot_id=snapshot_id,
            request_id=request_id,
            confirmed=confirmed,
        )
        # This is intentionally not persisted as an impact contract and cannot
        # call a product writer.  A separate owner-reviewed change must adopt it.
        return frozen, project_confirmed_plan(frozen)


def default_integration_plan_service() -> IntegrationPlanService:
    """Return the local artifact service without opening runtime infrastructure."""

    root = Path(os.environ.get("OMNI_SYSTEM_GRAPH_PLAN_ROOT", ".omni/system-graph/integration-plans"))
    snapshots = Path(os.environ.get("OMNI_SYSTEM_GRAPH_SNAPSHOT_ROOT", "output/system-graph/snapshots"))
    return IntegrationPlanService(store=FilePlanStore(root), snapshot_root=snapshots)


def create_candidate_plan(
    service: IntegrationPlanService,
    *,
    feature_id: str,
    base_snapshot_id: str,
    intent: str,
    items: Iterable[PlanItem],
) -> IntegrationPlanRevision:
    """Observable REST application entrypoint; still only creates a plan artifact."""

    return service.create(
        feature_id=feature_id,
        base_snapshot_id=base_snapshot_id,
        intent=intent,
        items=items,
    )


def project_confirmed_plan(plan: IntegrationPlanRevision) -> dict[str, object]:
    """Return an impact *draft*, never write it or transition it automatically."""

    if plan.state is not IntegrationPlanState.FROZEN:
        raise ValueError("only a frozen, explicitly confirmed revision can project an impact draft")
    planned_changes = [
        {
            "id": f"PLAN-{item.item_id}",
            "action": item.decision.value,
            "node_id": item.target_ref,
            "verification": item.verification,
            "risk": item.risk,
        }
        for item in plan.items
        if item.decision is not PlanDecision.NOT_DO
    ]
    return {
        "schema_version": 3,
        "change_id": f"candidate-{plan.plan_id}",
        "feature_refs": [{"feature_id": plan.feature_id, "feature_ref": plan.plan_id}],
        "before_snapshot": {"ref": plan.base_snapshot_id},
        "plan_revision": plan.revision,
        "planned_changes": planned_changes,
        "expected_graph_diff": [item.target_ref for item in plan.items if item.decision is PlanDecision.ADD],
        "requires_user_confirmation": False,
        "product_write_performed": False,
    }
