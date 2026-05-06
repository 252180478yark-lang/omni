"""Tests for /api/v1/mcp/human-gates REST router (W4-B 切片 2 T1)."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.database import close_pool, get_pool, init_pool
from app.main import app


pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture(scope="module", autouse=True)
async def _seed_gates():
    """T1 测试前清表 + 塞 3 条 pending + 1 条 already-decided。"""
    await init_pool()
    pool = get_pool()
    # 清旧测试数据
    await pool.execute(
        "DELETE FROM mcp.human_gates WHERE summary LIKE '__t1_slice2_seed_%'"
    )
    await pool.execute(
        "DELETE FROM mcp.tool_calls WHERE tool_name LIKE '__t1_slice2_seed_%'"
    )

    now = datetime.now(timezone.utc)
    # 先建 4 条 tool_calls
    tc_ids = [str(uuid.uuid4()) for _ in range(4)]
    for i, tc_id in enumerate(tc_ids):
        await pool.execute(
            """INSERT INTO mcp.tool_calls
               (id, tool_name, args, status, require_approval, created_at)
               VALUES ($1, $2, $3::jsonb, 'pending', TRUE, $4)""",
            uuid.UUID(tc_id),
            f"__t1_slice2_seed_record_cost_{i}",
            json.dumps({"sku_id": "SKU-T1S2", "category": "logistics"}),
            now - timedelta(minutes=i * 5),
        )

    # 建 4 条 gates: 3 pending + 1 already approved
    gate_ids = [str(uuid.uuid4()) for _ in range(4)]
    for i, (gid, tc_id) in enumerate(zip(gate_ids, tc_ids)):
        decision = None if i < 3 else "approved"
        await pool.execute(
            """INSERT INTO mcp.human_gates
               (id, tool_call_id, summary, timeout_seconds, decision,
                decision_note, decided_at, created_at)
               VALUES ($1, $2, $3, 3600, $4, $5, $6, $7)""",
            uuid.UUID(gid),
            uuid.UUID(tc_id),
            f"__t1_slice2_seed_summary_{i}",
            decision,
            "测试 seed" if decision else None,
            now if decision else None,
            now - timedelta(minutes=i * 5),
        )

    yield {"pending": gate_ids[:3], "decided": gate_ids[3], "tc_ids": tc_ids}

    # teardown
    await pool.execute(
        "DELETE FROM mcp.human_gates WHERE summary LIKE '__t1_slice2_seed_%'"
    )
    await pool.execute(
        "DELETE FROM mcp.tool_calls WHERE tool_name LIKE '__t1_slice2_seed_%'"
    )
    await close_pool()


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


# ─── list endpoint ────────────────────────────────────────────────────────


async def test_list_returns_pending_only(client, _seed_gates):
    """GET /api/v1/mcp/human-gates 只返 pending（decision IS NULL）。"""
    resp = await client.get("/api/v1/mcp/human-gates")
    assert resp.status_code == 200
    body = resp.json()
    seed_rows = [r for r in body["data"] if r["summary"].startswith("__t1_slice2_seed_")]
    assert len(seed_rows) == 3  # 只 3 条 pending
    # 确认字段齐全
    row = seed_rows[0]
    assert "short_id" in row
    assert len(row["short_id"]) == 8
    assert "tool_name" in row
    assert "args_preview" in row
    assert "age_seconds" in row
    assert row["age_seconds"] >= 0


async def test_list_excludes_decided(client, _seed_gates):
    """已批的 gate 不在 list 里。"""
    resp = await client.get("/api/v1/mcp/human-gates")
    body = resp.json()
    decided_id = _seed_gates["decided"]
    ids = [r["id"] for r in body["data"]]
    assert decided_id not in ids


# ─── approve endpoint ─────────────────────────────────────────────────────


async def test_approve_with_full_uuid(client, _seed_gates):
    """POST /api/v1/mcp/human-gates/{full_uuid}/approve."""
    target = _seed_gates["pending"][0]
    resp = await client.post(
        f"/api/v1/mcp/human-gates/{target}/approve",
        json={"note": "OK"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["result"]["decision"] == "approved"
    # 验 DB 真写
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT decision, decision_note FROM mcp.human_gates WHERE id=$1",
        uuid.UUID(target),
    )
    assert row["decision"] == "approved"
    assert row["decision_note"] == "OK"


async def test_approve_with_short_id(client, _seed_gates):
    """short_id (8 char) 走前缀匹配。"""
    target_full = _seed_gates["pending"][1]
    short = target_full[:8]
    resp = await client.post(
        f"/api/v1/mcp/human-gates/{short}/approve",
        json={"note": ""},
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


async def test_approve_already_decided_returns_409(client, _seed_gates):
    """二次批返 409 already_decided。"""
    target = _seed_gates["decided"]  # 这条已 approved
    resp = await client.post(
        f"/api/v1/mcp/human-gates/{target}/approve",
        json={"note": "重批"},
    )
    assert resp.status_code == 409
    body = resp.json()
    assert body["ok"] is False
    assert body["error"] == "already_decided"


async def test_approve_not_found_returns_404(client):
    """完全不存在的 uuid 返 404."""
    bogus = str(uuid.uuid4())
    resp = await client.post(
        f"/api/v1/mcp/human-gates/{bogus}/approve",
        json={"note": ""},
    )
    assert resp.status_code == 404
    assert resp.json()["error"] == "gate_not_found"


async def test_approve_invalid_id_format(client):
    """非 uuid 非合法 short_id 返 404 gate_not_found（不是 422，service 层兜）."""
    resp = await client.post(
        "/api/v1/mcp/human-gates/zzz/approve",
        json={"note": ""},
    )
    # short_id 'zzz' 没匹配任何 pending，返 gate_not_found 404
    assert resp.status_code == 404


# ─── reject endpoint ──────────────────────────────────────────────────────


async def test_reject_with_full_uuid(client, _seed_gates):
    target = _seed_gates["pending"][2]
    resp = await client.post(
        f"/api/v1/mcp/human-gates/{target}/reject",
        json={"note": "不行，参数不对"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["result"]["decision"] == "rejected"
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT decision, decision_note FROM mcp.human_gates WHERE id=$1",
        uuid.UUID(target),
    )
    assert row["decision"] == "rejected"
    assert row["decision_note"] == "不行，参数不对"
