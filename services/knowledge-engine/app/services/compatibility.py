"""Fail-closed compatibility telemetry and legacy-client retirement readiness."""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from app.database import get_pool

logger = logging.getLogger(__name__)

OBSERVATION_DAYS = 14
REQUIRED_INVENTORIES = (
    "sqlite",
    "attachments",
    "settings",
    "secret_reauthorization",
    "host_smoke",
    "restore_smoke",
)
ALLOWED_METADATA = {"version", "client_version", "operation_id", "state", "reason_code", "device_class"}


@dataclass(frozen=True)
class CompatibilityEvent:
    client_id: str
    capability_id: str
    route_family: str
    exclusive: bool
    observed_at: datetime
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ReconciliationEvidence:
    inventory_kind: str
    state: str
    observed_at: datetime
    source_checksum: str | None = None
    target_checksum: str | None = None


def safe_metadata(values: dict[str, Any] | None) -> dict[str, Any]:
    if not values:
        return {}
    return {
        key: value
        for key, value in values.items()
        if key in ALLOWED_METADATA and isinstance(value, (str, int, float, bool, type(None)))
    }


def event_hash(event: CompatibilityEvent) -> str:
    value = {
        "client_id": event.client_id,
        "capability_id": event.capability_id,
        "route_family": event.route_family,
        "exclusive": event.exclusive,
        "observed_at": event.observed_at.astimezone(timezone.utc).isoformat(),
        "metadata": safe_metadata(event.metadata),
    }
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def append_compatibility_event(event: CompatibilityEvent) -> uuid.UUID:
    event_id = uuid.uuid5(uuid.NAMESPACE_URL, event_hash(event))
    pool = get_pool()
    await pool.execute(
        """
        INSERT INTO mcp.compatibility_telemetry
          (event_id,client_id,capability_id,route_family,exclusive,observed_at,metadata,payload_hash)
        VALUES($1,$2,$3,$4,$5,$6,$7::jsonb,$8)
        ON CONFLICT(payload_hash) DO NOTHING
        """,
        event_id, event.client_id, event.capability_id, event.route_family,
        event.exclusive, event.observed_at, json.dumps(safe_metadata(event.metadata)), event_hash(event),
    )
    return event_id


async def append_route_telemetry(*, route_family: str, capability_id: str, state: str) -> None:
    try:
        await append_compatibility_event(
            CompatibilityEvent(
                client_id="http-adapter",
                capability_id=capability_id,
                route_family=route_family,
                exclusive=False,
                observed_at=datetime.now(timezone.utc),
                metadata={"state": state, "operation_id": capability_id},
            )
        )
    except RuntimeError as exc:
        if "pool not initialized" in str(exc).casefold():
            logger.debug("compatibility telemetry unavailable before database startup")
            return
        logger.warning("compatibility telemetry append failed", exc_info=True)
    except Exception:
        # Telemetry gaps are visible in the retirement report; they must not change
        # the business tool result while a migration is rolling out.
        logger.warning("compatibility telemetry append failed", exc_info=True)


def evaluate_retirement_readiness(
    *,
    client_id: str,
    as_of: datetime,
    coverage_started_at: datetime | None,
    events: Iterable[CompatibilityEvent],
    reconciliations: Iterable[ReconciliationEvidence],
) -> dict[str, Any]:
    as_of = as_of.astimezone(timezone.utc)
    window_start = as_of - timedelta(days=OBSERVATION_DAYS)
    blockers: list[dict[str, str]] = []
    coverage_ok = coverage_started_at is not None and coverage_started_at.astimezone(timezone.utc) <= window_start
    if not coverage_ok:
        blockers.append({"code": "observation_window_incomplete", "detail": f"need coverage since {window_start.isoformat()}"})
    exclusive = [
        event for event in events
        if event.client_id == client_id and event.exclusive and window_start <= event.observed_at.astimezone(timezone.utc) <= as_of
    ]
    if exclusive:
        blockers.append({"code": "exclusive_usage_observed", "detail": f"{len(exclusive)} event(s) in the 14-day window"})

    capability_groups: dict[str, dict[str, Any]] = {}
    for event in events:
        observed_at = event.observed_at.astimezone(timezone.utc)
        if event.client_id != client_id or not (window_start <= observed_at <= as_of):
            continue
        group = capability_groups.setdefault(
            event.capability_id,
            {
                "capability_id": event.capability_id,
                "route_families": set(),
                "observation_count": 0,
                "exclusive_event_count": 0,
                "last_observed_at": None,
            },
        )
        group["route_families"].add(event.route_family)
        group["observation_count"] += 1
        group["exclusive_event_count"] += int(event.exclusive)
        if group["last_observed_at"] is None or observed_at > group["last_observed_at"]:
            group["last_observed_at"] = observed_at
    capability_matrix = []
    for capability_id in sorted(capability_groups):
        group = capability_groups[capability_id]
        capability_matrix.append(
            {
                "capability_id": capability_id,
                "route_families": sorted(group["route_families"]),
                "observation_count": group["observation_count"],
                "exclusive_event_count": group["exclusive_event_count"],
                "last_observed_at": group["last_observed_at"].isoformat(),
                "compatibility_state": "exclusive" if group["exclusive_event_count"] else "shared_or_canonical",
            }
        )

    latest: dict[str, ReconciliationEvidence] = {}
    for item in reconciliations:
        current = latest.get(item.inventory_kind)
        if current is None or item.observed_at > current.observed_at:
            latest[item.inventory_kind] = item
    inventory: dict[str, dict[str, Any]] = {}
    for kind in REQUIRED_INVENTORIES:
        item = latest.get(kind)
        matched = bool(item and item.state == "matched")
        if kind in {"sqlite", "attachments", "settings"}:
            matched = matched and bool(item and item.source_checksum and item.source_checksum == item.target_checksum)
        inventory[kind] = {"state": item.state if item else "missing", "matched": matched, "observed_at": item.observed_at.isoformat() if item else None}
        if not matched:
            blockers.append({"code": f"{kind}_not_reconciled", "detail": "latest evidence is absent or mismatched"})

    ready = not blockers
    return {
        "client_id": client_id,
        "as_of": as_of.isoformat(),
        "observation_days_required": OBSERVATION_DAYS,
        "window_start": window_start.isoformat(),
        "coverage_ok": coverage_ok,
        "exclusive_event_count": len(exclusive),
        "capability_matrix": capability_matrix,
        "inventory": inventory,
        "ready_for_r3_review": ready,
        # Physical retirement is never authorized by telemetry alone.
        "physical_retirement_allowed": False,
        "required_gate": "R3 explicit owner approval",
        "blockers": blockers,
    }


async def database_retirement_report(client_id: str, *, as_of: datetime | None = None) -> dict[str, Any]:
    as_of = as_of or datetime.now(timezone.utc)
    pool = get_pool()
    coverage_started = await pool.fetchval(
        "SELECT MIN(observed_at) FROM mcp.compatibility_telemetry WHERE client_id=$1",
        client_id,
    )
    event_rows = await pool.fetch(
        """SELECT client_id,capability_id,route_family,exclusive,observed_at,metadata
           FROM mcp.compatibility_telemetry WHERE client_id=$1 AND observed_at >= $2""",
        client_id, as_of - timedelta(days=OBSERVATION_DAYS),
    )
    reconciliation_rows = await pool.fetch(
        """SELECT inventory_kind,state,observed_at,source_checksum,target_checksum
           FROM mcp.retirement_reconciliations WHERE client_id=$1 ORDER BY observed_at""",
        client_id,
    )
    return evaluate_retirement_readiness(
        client_id=client_id,
        as_of=as_of,
        coverage_started_at=coverage_started,
        events=[CompatibilityEvent(**dict(row)) for row in event_rows],
        reconciliations=[ReconciliationEvidence(**dict(row)) for row in reconciliation_rows],
    )
