"""Append every metric observation; only the claimed source mutates canonical values."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class MetricObservation:
    sku_id: str
    metric_date: date
    metric_name: str
    value: Decimal | None
    platform: str
    source: str
    source_run_id: str | None = None

    def payload_hash(self) -> str:
        value = {
            "sku_id": self.sku_id,
            "date": self.metric_date.isoformat(),
            "metric_name": self.metric_name,
            "value": str(self.value) if self.value is not None else None,
            "platform": self.platform,
            "source": self.source,
            "source_run_id": self.source_run_id,
        }
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class MetricWriteResult:
    observation_id: uuid.UUID
    owner_source: str
    canonical_updated: bool
    collision_id: uuid.UUID | None = None


async def submit_metric_observation(conn: Any, observation: MetricObservation) -> MetricWriteResult:
    if not all((observation.sku_id, observation.metric_name, observation.platform, observation.source)):
        raise ValueError("metric observation identity fields cannot be empty")

    # First source claims an exact metric/platform key. Later ownership changes are
    # deliberate admin data changes, never implicit writer behavior.
    await conn.execute(
        """
        INSERT INTO mcp.metric_source_owners (platform, metric_name, owner_source)
        VALUES ($1,$2,$3)
        ON CONFLICT (platform, metric_name) DO NOTHING
        """,
        observation.platform, observation.metric_name, observation.source,
    )
    owner = await conn.fetchval(
        "SELECT owner_source FROM mcp.metric_source_owners WHERE platform=$1 AND metric_name=$2",
        observation.platform, observation.metric_name,
    )
    observation_id = uuid.uuid4()
    payload_hash = observation.payload_hash()
    existing = await conn.fetchrow(
        "SELECT observation_id FROM mcp.metric_observations WHERE payload_hash=$1",
        payload_hash,
    )
    if existing:
        return MetricWriteResult(existing["observation_id"], str(owner), str(owner) == observation.source)
    await conn.execute(
        """
        INSERT INTO mcp.metric_observations
          (observation_id,sku_id,metric_date,metric_name,value,platform,source,source_run_id,payload_hash)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
        """,
        observation_id, observation.sku_id, observation.metric_date, observation.metric_name,
        observation.value, observation.platform, observation.source, observation.source_run_id,
        payload_hash,
    )
    if owner == observation.source:
        await conn.execute(
            """
            INSERT INTO mvp_daily_metric
              (sku_id,date,metric_name,value,platform,source_runbook,source_run_id)
            VALUES ($1,$2,$3,$4,$5,$6,$7)
            ON CONFLICT (sku_id,date,metric_name,platform)
            DO UPDATE SET value=EXCLUDED.value, source_runbook=EXCLUDED.source_runbook,
                          source_run_id=EXCLUDED.source_run_id, created_at=NOW()
            """,
            observation.sku_id, observation.metric_date, observation.metric_name,
            observation.value, observation.platform, observation.source, observation.source_run_id,
        )
        return MetricWriteResult(observation_id, str(owner), True)

    canonical = await conn.fetchrow(
        """
        SELECT value,source_runbook FROM mvp_daily_metric
        WHERE sku_id=$1 AND date=$2 AND metric_name=$3 AND platform=$4
        """,
        observation.sku_id, observation.metric_date, observation.metric_name, observation.platform,
    )
    collision_id = uuid.uuid4()
    await conn.execute(
        """
        INSERT INTO mcp.metric_collisions
          (collision_id,observation_id,owner_source,canonical_value,canonical_source)
        VALUES ($1,$2,$3,$4,$5)
        """,
        collision_id, observation_id, owner,
        canonical["value"] if canonical else None,
        canonical["source_runbook"] if canonical else None,
    )
    return MetricWriteResult(observation_id, str(owner), False, collision_id)

