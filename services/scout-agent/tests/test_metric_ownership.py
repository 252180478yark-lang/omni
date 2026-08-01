from datetime import date

import pytest

from app.services.metric_ownership import submit_metric


class FakeConnection:
    def __init__(self):
        self.owner = None
        self.observations = {}
        self.canonical = None
        self.collisions = []

    async def execute(self, query, *args):
        if "metric_source_owners" in query:
            self.owner = self.owner or args[2]
        elif "metric_observations" in query:
            self.observations[args[8]] = args[0]
        elif "mvp_daily_metric" in query:
            self.canonical = {"value": args[3], "source_runbook": args[5]}
        elif "metric_collisions" in query:
            self.collisions.append(args)

    async def fetchval(self, _query, *_args):
        return self.owner

    async def fetchrow(self, query, *args):
        if "metric_observations" in query:
            value = self.observations.get(args[0])
            return {"observation_id": value} if value else None
        return self.canonical


@pytest.mark.asyncio
async def test_scout_adapter_enforces_first_claimed_owner() -> None:
    conn = FakeConnection()
    first = await submit_metric(conn, sku_id="SKU-1", metric_date=date(2026, 8, 1), metric_name="gmv", value=10, platform="douyin", source="compass")
    second = await submit_metric(conn, sku_id="SKU-1", metric_date=date(2026, 8, 1), metric_name="gmv", value=20, platform="douyin", source="csv")
    assert first["canonical_updated"] is True
    assert second["canonical_updated"] is False
    assert conn.canonical["value"] == 10
    assert len(conn.collisions) == 1
