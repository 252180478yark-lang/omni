"""Internal compatibility telemetry and fail-closed retirement report API."""

from __future__ import annotations

import hmac
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from app.services.compatibility import (
    CompatibilityEvent,
    append_compatibility_event,
    database_retirement_report,
    safe_metadata,
)

router = APIRouter(prefix="/api/v1/compatibility", tags=["compatibility"])


def require_compatibility_access(authorization: str | None = Header(default=None)) -> None:
    path = os.getenv("OMNI_COMPATIBILITY_TOKEN_FILE", "").strip()
    if not path:
        raise HTTPException(status_code=503, detail={"code": "compatibility_auth_unconfigured"})
    try:
        expected = Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        raise HTTPException(status_code=503, detail={"code": "compatibility_auth_unavailable"}) from None
    supplied = authorization.removeprefix("Bearer ") if authorization else ""
    if len(expected) < 24 or not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail={"code": "compatibility_auth_required"})


class TelemetryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{1,99}$")
    capability_id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.:-]{1,199}$")
    route_family: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.:-]{1,99}$")
    exclusive: bool = False
    observed_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


@router.post("/telemetry", dependencies=[Depends(require_compatibility_access)])
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


@router.get("/retirement-report", dependencies=[Depends(require_compatibility_access)])
async def retirement_report(client_id: str = Query(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{1,99}$")) -> dict[str, Any]:
    return await database_retirement_report(client_id)

