"""阶段0 wiring 集成测（hits dev DB · 2026-06-02）。

覆盖本次新增/修复的关键运行时路径，纳入 L0-7 回归网，防将来改动回归：
- 月度成本：record_spend → get_month_total → check_over_cap（+ 负值拒收）
- ad_metrics 读-合并-全量重校验（审查 #7 修复：多次回传 roi 的 suspect 标记不丢）
- 诊断官提议三态生命周期（resolve accept/ignore/snooze + 非法 action）
- _expire_stale：过期 snooze 自动复活（审查 #11 修复）
- tool_use_id 焊链回填（按 tool_name 回填最近未焊接 tool_calls 行）

全部用 __itest 前缀标记 + finally 清理，不留脏数据。
"""
from __future__ import annotations

import datetime as _dt

import pytest
import pytest_asyncio

from app.database import get_pool, init_pool, close_pool
from app.services import cost_ledger_service as spend_svc
from app.services import diagnose_service as diag_svc
from app.services import pipeline_lineage as lineage_svc


@pytest_asyncio.fixture(scope="module", autouse=True)
async def _pool():
    await init_pool()
    yield
    await close_pool()


# ───────────────────────── 月度成本闭环 ─────────────────────────

@pytest.mark.asyncio
async def test_spend_record_total_and_cap():
    note = "__itest_spend__"
    pool = get_pool()
    try:
        r = await spend_svc.record_spend(cost_usd=1.5, note=note, source="manual")
        assert r["ok"], r
        tot = await spend_svc.get_month_total()
        assert tot["ok"] and tot["total_cost_usd"] >= 1.5
        cap = await spend_svc.check_over_cap()
        assert cap["ok"] and cap["cap_usd"] > 0
        # precomputed_total 路径与直查一致
        cap2 = await spend_svc.check_over_cap(precomputed_total=tot["total_cost_usd"])
        assert cap2["total_cost_usd"] == pytest.approx(tot["total_cost_usd"])
        # 负值/NaN 拒收
        bad = await spend_svc.record_spend(cost_usd=-5)
        assert not bad["ok"]
    finally:
        await pool.execute("DELETE FROM mcp.monthly_spend WHERE note = $1", note)


# ───────────────────── ad_metrics 读-合并-全量重校验 ─────────────────────

@pytest.mark.asyncio
async def test_ad_metrics_merge_preserves_suspect_flag():
    pool = get_pool()
    aid = await pool.fetchval(
        "INSERT INTO pipeline.assets (sku_id, asset_type, ad_metrics, status) "
        "VALUES ('__ITEST_SKU__', 'video', '{}'::jsonb, 'draft') RETURNING id"
    )
    try:
        await lineage_svc.record_ad_metrics(asset_id=str(aid), metrics={"roi": 2.0, "gmv": 1000})
        r = await lineage_svc.record_ad_metrics(asset_id=str(aid), metrics={"plays": 5000})
        am = r["ad_metrics"]
        # 累积合并：三个 key 都在
        assert am.get("roi") == 2.0 and "gmv" in am and "plays" in am
        # 关键：第二次回传没带 roi，roi 的 suspect 标记仍保留（#7 修复）
        assert "roi" in am.get("_validation", {}).get("suspect", {})
    finally:
        await pool.execute("DELETE FROM pipeline.assets WHERE id = $1", aid)


# ───────────────────── 诊断官提议三态生命周期 ─────────────────────

async def _insert_proposal(pool, dedupe_key, status="open", snooze_until=None):
    return await pool.fetchval(
        """
        INSERT INTO mcp.improvement_proposals
            (mode, source, title, observation, dedupe_key, status, priority, snooze_until)
        VALUES ('content','itest','t','o',$1,$2,1,$3) RETURNING id
        """,
        dedupe_key, status, snooze_until,
    )


@pytest.mark.asyncio
async def test_proposal_resolve_three_states():
    pool = get_pool()
    try:
        pid = await _insert_proposal(pool, "__itest:resolve")
        r1 = await diag_svc.resolve_proposal(str(pid), "snooze", snooze_days=7)
        assert r1["ok"] and r1["status"] == "snoozed"
        r2 = await diag_svc.resolve_proposal(str(pid), "accept")
        assert r2["status"] == "accepted"
        r3 = await diag_svc.resolve_proposal(str(pid), "bogus")
        assert not r3["ok"] and r3["error"] == "invalid_action"
        r4 = await diag_svc.resolve_proposal("00000000-0000-0000-0000-000000000000", "accept")
        assert not r4["ok"] and r4["error"] == "not_found"
    finally:
        await pool.execute("DELETE FROM mcp.improvement_proposals WHERE dedupe_key LIKE '__itest:%'")


@pytest.mark.asyncio
async def test_expire_stale_reactivates_past_snooze():
    pool = get_pool()
    try:
        # snooze_until 在过去 → _expire_stale 应把它复活成 open（#11 修复）
        pid = await _insert_proposal(
            pool, "__itest:snooze_past", status="snoozed",
            snooze_until=_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=1),
        )
        await diag_svc._expire_stale(pool, _dt.datetime.now(_dt.timezone.utc))
        st = await pool.fetchval(
            "SELECT status FROM mcp.improvement_proposals WHERE id = $1", pid
        )
        assert st == "open"
    finally:
        await pool.execute("DELETE FROM mcp.improvement_proposals WHERE dedupe_key LIKE '__itest:%'")


@pytest.mark.asyncio
async def test_upsert_proposal_dedup_and_mute():
    """覆盖 _upsert_proposal 的 ON CONFLICT DO UPDATE 路径（occ 增量）+ ignored 静音。"""
    pool = get_pool()
    p = {
        "mode": "content", "source": "itest", "title": "t", "observation": "o",
        "hypothesis": "h", "evidence": {"x": 1}, "sample_size": 3,
        "confidence": "preliminary", "priority": 3.0, "priority_reason": "r",
        "dedupe_key": "__itest:occ",
    }
    now = _dt.datetime.now(_dt.timezone.utc)
    try:
        o1 = await diag_svc._upsert_proposal(pool, p, now)
        o2 = await diag_svc._upsert_proposal(pool, p, now)
        assert o1 == "created" and o2 == "refreshed"      # ON CONFLICT 命中 DO UPDATE
        occ = await pool.fetchval(
            "SELECT occurrences FROM mcp.improvement_proposals WHERE dedupe_key='__itest:occ'"
        )
        assert occ == 2                                     # 旧行 occurrences 正确 +1
        # 标 ignored 后不再重建（muted，不再提醒同类）
        await pool.execute(
            "UPDATE mcp.improvement_proposals SET status='ignored' WHERE dedupe_key='__itest:occ'"
        )
        o3 = await diag_svc._upsert_proposal(pool, p, now)
        assert o3 == "muted"
    finally:
        await pool.execute("DELETE FROM mcp.improvement_proposals WHERE dedupe_key LIKE '__itest:%'")


@pytest.mark.asyncio
async def test_list_proposals_returns_stats():
    pool = get_pool()
    try:
        await _insert_proposal(pool, "__itest:list")
        res = await diag_svc.list_proposals(status="open")
        assert res["ok"] and isinstance(res["proposals"], list)
        assert res["open_count"] >= 1
        assert "digestion_rate_7d" in res
    finally:
        await pool.execute("DELETE FROM mcp.improvement_proposals WHERE dedupe_key LIKE '__itest:%'")


# ───────────────────── tool_use_id 焊链回填 ─────────────────────

@pytest.mark.asyncio
async def test_tool_use_link_backfills_recent_call():
    pool = get_pool()
    tname = "__itest_tool__"
    cid = await pool.fetchval(
        "INSERT INTO mcp.tool_calls (tool_name, args, status, require_approval) "
        "VALUES ($1, '{}'::jsonb, 'success', false) RETURNING id",
        tname,
    )
    try:
        from app.routers.tool_uses import link_tool_uses, ToolUseLink, ToolUseLinkBatch
        res = await link_tool_uses(ToolUseLinkBatch(items=[
            ToolUseLink(tool_use_id="toolu_itest", tool_name=tname, claude_session_id="sess-itest"),
        ]))
        assert res["ok"] and res["linked"] == 1
        tuid = await pool.fetchval(
            "SELECT tool_use_id FROM mcp.tool_calls WHERE id = $1", cid
        )
        assert tuid == "toolu_itest"
        # 幂等：再焊一次仍 linked（已存在则跳过不报错）
        res2 = await link_tool_uses(ToolUseLinkBatch(items=[
            ToolUseLink(tool_use_id="toolu_itest", tool_name=tname),
        ]))
        assert res2["ok"]
    finally:
        await pool.execute("DELETE FROM mcp.tool_calls WHERE tool_name = $1", tname)
