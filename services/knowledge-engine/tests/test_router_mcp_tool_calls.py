"""Tests for /api/v1/mcp/tool-calls REST router (W4-B 切片 1 T1)."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.database import close_pool, get_pool, init_pool
from app.main import app
from app.mcp import pattern_lib


pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def tmp_state_dir(monkeypatch, tmp_path):
    """隔离 pattern_lib 写盘到 pytest tmp_path，避免污染 host data/agent_state/。

    rate_tool_call_logic 调 pattern_lib.append_successful_pattern / append_failed_pattern
    会按 pattern_lib.AGENT_STATE_DIR 解析路径，默认 /app/agent_state（host bind mount）。
    测试里全部 monkeypatch 到 tmp_path，跑完即销毁。
    """
    success = tmp_path / "successful_patterns.md"
    failed = tmp_path / "failed_patterns.md"
    success.write_text("# Successful Patterns\n\n", encoding="utf-8")
    failed.write_text("# Failed Patterns\n\n", encoding="utf-8")
    monkeypatch.setattr(pattern_lib, "AGENT_STATE_DIR", tmp_path)
    return tmp_path


@pytest_asyncio.fixture(scope="module", autouse=True)
async def _seed_tool_calls():
    """T1 测试前清表 + 塞 5 条已知数据。"""
    await init_pool()
    pool = get_pool()
    await pool.execute("DELETE FROM mcp.tool_calls WHERE tool_name LIKE '__t1_seed_%'")
    now = datetime.now(timezone.utc)
    seed_ids = []
    rows = [
        ("__t1_seed_query_costs", "completed", "good", 120),
        ("__t1_seed_record_cost", "completed", None, 80),
        ("__t1_seed_generate_brief", "completed", "bad", 5400),
        ("__t1_seed_search_kb", "error", None, 3000),
        ("__t1_seed_record_cost", "pending", None, None),
    ]
    for i, (tool, status, rating, dur) in enumerate(rows):
        new_id = uuid.uuid4()
        result_payload = (
            json.dumps({"ok": True, "trace": {"provider": "anthropic"}})
            if status == "completed"
            else None
        )
        await pool.execute(
            """INSERT INTO mcp.tool_calls
               (id, tool_name, args, result, status, require_approval,
                duration_ms, user_rating, created_at)
               VALUES ($1, $2, $3::jsonb, $4::jsonb, $5, $6, $7, $8, $9)""",
            new_id,
            tool,
            json.dumps({"sku_id": "SKU-A"}),
            result_payload,
            status,
            status == "pending",
            dur,
            rating,
            now - timedelta(minutes=i * 10),
        )
        seed_ids.append(str(new_id))
    yield seed_ids
    await pool.execute("DELETE FROM mcp.tool_calls WHERE tool_name LIKE '__t1_seed_%'")
    await close_pool()


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


# ─── list endpoint ────────────────────────────────────────────────────────


async def test_list_returns_recent_calls(client, _seed_tool_calls):
    """GET /api/v1/mcp/tool-calls 返最近调用，DESC 排序，含 summary_24h。"""
    resp = await client.get("/api/v1/mcp/tool-calls?limit=500")
    assert resp.status_code == 200
    body = resp.json()
    assert "data" in body
    assert "summary_24h" in body
    seed_rows = [r for r in body["data"] if r["tool_name"].startswith("__t1_seed_")]
    assert len(seed_rows) == 5
    # 第 0 条（offset=0min）就是 query_costs
    assert seed_rows[0]["tool_name"] == "__t1_seed_query_costs"
    s = body["summary_24h"]
    assert "success_rate" in s
    assert "avg_duration_ms" in s
    assert "pending_count" in s
    assert "rating_dist" in s


async def test_list_filter_by_status(client, _seed_tool_calls):
    resp = await client.get("/api/v1/mcp/tool-calls?status=error&limit=500")
    assert resp.status_code == 200
    seed = [r for r in resp.json()["data"] if r["tool_name"].startswith("__t1_seed_")]
    assert len(seed) == 1
    assert seed[0]["tool_name"] == "__t1_seed_search_kb"


async def test_list_filter_by_tool_name(client, _seed_tool_calls):
    resp = await client.get(
        "/api/v1/mcp/tool-calls?tool_name=__t1_seed_record_cost&limit=500"
    )
    assert resp.status_code == 200
    seed = [r for r in resp.json()["data"] if r["tool_name"].startswith("__t1_seed_")]
    assert len(seed) == 2


# ─── detail endpoint ──────────────────────────────────────────────────────


async def test_detail_returns_full_row(client, _seed_tool_calls):
    target = _seed_tool_calls[0]
    resp = await client.get(f"/api/v1/mcp/tool-calls/{target}")
    assert resp.status_code == 200
    row = resp.json()["data"]
    assert row["tool_name"] == "__t1_seed_query_costs"
    assert row["user_rating"] == "good"
    assert row["result"]["trace"]["provider"] == "anthropic"
    assert row["args"]["sku_id"] == "SKU-A"


async def test_detail_404(client):
    bogus = uuid.uuid4()
    resp = await client.get(f"/api/v1/mcp/tool-calls/{bogus}")
    assert resp.status_code == 404


# ─── rate endpoint ────────────────────────────────────────────────────────


async def test_rate_writes_user_rating(client, _seed_tool_calls, tmp_state_dir):
    target = _seed_tool_calls[1]
    resp = await client.post(
        f"/api/v1/mcp/tool-calls/{target}/rate",
        json={"rating": "good", "note": "录得对"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["result"]["rating"] == "good"
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT user_rating, rating_note FROM mcp.tool_calls WHERE id=$1",
        uuid.UUID(target),
    )
    assert row["user_rating"] == "good"
    assert row["rating_note"] == "录得对"
    # feedback-loop contract: rating="good" 必须双写 successful_patterns.md
    success_md = tmp_state_dir / "successful_patterns.md"
    assert success_md.exists(), "rating=good 必须写 successful_patterns.md"
    text = success_md.read_text(encoding="utf-8")
    assert target in text, f"call_id={target} 未出现在 successful_patterns.md"


async def test_rate_invalid_rating(client, _seed_tool_calls):
    target = _seed_tool_calls[2]
    resp = await client.post(
        f"/api/v1/mcp/tool-calls/{target}/rate",
        json={"rating": "awesome"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_rating"


async def test_rate_call_not_found(client):
    bogus = uuid.uuid4()
    resp = await client.post(
        f"/api/v1/mcp/tool-calls/{bogus}/rate",
        json={"rating": "good"},
    )
    assert resp.status_code == 404
