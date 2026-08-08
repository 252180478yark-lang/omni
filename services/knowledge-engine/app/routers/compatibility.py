"""Internal compatibility telemetry and fail-closed retirement report API."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field

from app.services.compatibility import (
    CompatibilityEvent,
    append_compatibility_event,
    database_retirement_report,
    safe_metadata,
)

router = APIRouter(prefix="/api/v1/compatibility", tags=["compatibility"])


def require_compatibility_access() -> None:
    """Compatibility dependency retained for imports; local access is trusted."""


class TelemetryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{1,99}$")
    capability_id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.:-]{1,199}$")
    route_family: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.:-]{1,99}$")
    exclusive: bool = False
    observed_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


@router.post("/telemetry")
async def record_telemetry(payload: TelemetryInput) -> dict[str, Any]:
    event = CompatibilityEvent(
        client_id=payload.client_id,
        capability_id=payload.capability_id,
        route_family=payload.route_family,
        exclusive=payload.exclusive,
        observed_at=payload.observed_at.astimezone(timezone.utc),
        metadata=safe_metadata(payload.metadata),
    )
    event_id = await append_compatibility_event(event)
    return {"ok": True, "event_id": str(event_id), "metadata_fields": sorted(event.metadata)}


@router.get("/retirement-report")
async def retirement_report(client_id: str = Query(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{1,99}$")) -> dict[str, Any]:
    return await database_retirement_report(client_id)
