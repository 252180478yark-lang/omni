from datetime import date
from decimal import Decimal

import pytest

from app.services.metric_ownership import MetricObservation, submit_metric_observation


class FakeConnection:
    def __init__(self):
        self.owners = {}
        self.observations = {}
        self.canonical = {}
        self.collisions = []

    async def execute(self, query, *args):
        if "INSERT INTO mcp.metric_source_owners" in query:
            self.owners.setdefault((args[0], args[1]), args[2])
        elif "INSERT INTO mcp.metric_observations" in query:
            self.observations[args[8]] = args[0]
        elif "INSERT INTO mvp_daily_metric" in query:
            self.canonical[(args[0], args[1], args[2], args[4])] = {"value": args[3], "source_runbook": args[5]}
        elif "INSERT INTO mcp.metric_collisions" in query:
            self.collisions.append(args)
        return "OK"

    async def fetchval(self, query, *args):
        return self.owners.get((args[0], args[1]))

    async def fetchrow(self, query, *args):
        if "metric_observations" in query:
            value = self.observations.get(args[0])
            return {"observation_id": value} if value else None
        return self.canonical.get((args[0], args[1], args[2], args[3]))


@pytest.mark.asyncio
async def test_non_owner_is_preserved_as_collision_without_overwrite() -> None:
    conn = FakeConnection()
    owner = MetricObservation("SKU-1", date(2026, 8, 1), "gmv", Decimal("10"), "douyin", "compass")
    challenger = MetricObservation("SKU-1", date(2026, 8, 1), "gmv", Decimal("99"), "douyin", "csv")
    first = await submit_metric_observation(conn, owner)
    second = await submit_metric_observation(conn, challenger)
    assert first.canonical_updated is True
    assert second.canonical_updated is False
    assert conn.canonical[("SKU-1", date(2026, 8, 1), "gmv", "douyin")]["value"] == Decimal("10")
    assert len(conn.observations) == 2
    assert len(conn.collisions) == 1
