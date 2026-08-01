"""Scout adapter to the canonical metric ownership contract."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any


async def submit_metric(
    conn: Any,
    *,
    sku_id: str,
    metric_date: date | str,
    metric_name: str,
    value: Decimal | float | int | None,
    platform: str,
    source: str,
    source_run_id: str | None = None,
) -> dict[str, Any]:
    day = metric_date if isinstance(metric_date, date) else datetime.fromisoformat(str(metric_date)[:10]).date()
    number = Decimal(str(value)) if value is not None else None
    identity = {
        "sku_id": sku_id, "date": day.isoformat(), "metric_name": metric_name,
        "value": str(number) if number is not None else None, "platform": platform,
        "source": source, "source_run_id": source_run_id,
    }
    payload_hash = "sha256:" + hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    await conn.execute(
        "INSERT INTO mcp.metric_source_owners(platform,metric_name,owner_source) VALUES($1,$2,$3) ON CONFLICT DO NOTHING",
        platform, metric_name, source,
    )
    owner = await conn.fetchval(
        "SELECT owner_source FROM mcp.metric_source_owners WHERE platform=$1 AND metric_name=$2",
        platform, metric_name,
    )
    existing = await conn.fetchrow("SELECT observation_id FROM mcp.metric_observations WHERE payload_hash=$1", payload_hash)
    if existing:
        return {"observation_id": str(existing["observation_id"]), "canonical_updated": owner == source, "owner_source": owner, "duplicate": True}
    observation_id = uuid.uuid4()
    await conn.execute(
        """INSERT INTO mcp.metric_observations
           (observation_id,sku_id,metric_date,metric_name,value,platform,source,source_run_id,payload_hash)
           VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9)""",
        observation_id, sku_id, day, metric_name, number, platform, source, source_run_id, payload_hash,
    )
    if owner == source:
        await conn.execute(
            """INSERT INTO mvp_daily_metric(sku_id,date,metric_name,value,platform,source_runbook,source_run_id)
               VALUES($1,$2,$3,$4,$5,$6,$7)
               ON CONFLICT(sku_id,date,metric_name,platform) DO UPDATE SET
               value=EXCLUDED.value,source_runbook=EXCLUDED.source_runbook,
               source_run_id=EXCLUDED.source_run_id,created_at=NOW()""",
            sku_id, day, metric_name, number, platform, source, source_run_id,
        )
        return {"observation_id": str(observation_id), "canonical_updated": True, "owner_source": owner}
    canonical = await conn.fetchrow(
        "SELECT value,source_runbook FROM mvp_daily_metric WHERE sku_id=$1 AND date=$2 AND metric_name=$3 AND platform=$4",
        sku_id, day, metric_name, platform,
    )
    collision_id = uuid.uuid4()
    await conn.execute(
        """INSERT INTO mcp.metric_collisions
           (collision_id,observation_id,owner_source,canonical_value,canonical_source)
           VALUES($1,$2,$3,$4,$5)""",
        collision_id, observation_id, owner,
        canonical["value"] if canonical else None,
        canonical["source_runbook"] if canonical else None,
    )
    return {"observation_id": str(observation_id), "canonical_updated": False, "owner_source": owner, "collision_id": str(collision_id)}
