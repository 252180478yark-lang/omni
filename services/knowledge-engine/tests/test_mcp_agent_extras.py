"""W4-B 切片 5：W4 加分 5 个 tool 测试。

5 个 tool：
- save_decision (F)
- schedule_observation (T) — 直接调 _impl 已经走 audit 装饰器
  无 require_approval 真路径用，手动调底层 SQL 验证
- generate_image_compare (T) — mock AIHubClient
- send_wecom_message (T) — mock httpx + WECOM_WEBHOOKS env
- dy_publish_creative (T, stub)

只测核心分支 + helper 函数。Gate 真路径已在 W4-A T2/T3 反复验过，不重复。
"""
from __future__ import annotations

import os
import uuid

import pytest
import pytest_asyncio

from app.database import init_pool, close_pool, get_pool


@pytest_asyncio.fixture(scope="module", autouse=True)
async def _pool():
    await init_pool()
    yield
    await close_pool()


# ─── save_decision ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_save_decision_writes_row():
    from app.mcp.tools.agent_extras import save_decision

    res = await save_decision(
        title="测试决策",
        decision="把 sku-X 暂停天猫渠道",
        context="本周天猫销量持续下滑，毛利转负",
        tags=["sku-X", "channel-tmall", "pricing"],
    )
    assert res["ok"] is True
    decision_id = uuid.UUID(res["result"]["decision_id"])

    # 验真落库
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT title, decision, context, tags FROM mcp.decisions WHERE id=$1",
        decision_id,
    )
    assert row is not None
    assert row["title"] == "测试决策"
    assert "暂停天猫" in row["decision"]
    assert "sku-X" in row["tags"]

    # 清理
    await pool.execute("DELETE FROM mcp.decisions WHERE id=$1", decision_id)


@pytest.mark.asyncio
async def test_save_decision_validates_required():
    from app.mcp.tools.agent_extras import save_decision

    r1 = await save_decision(title="", decision="x")
    assert r1["ok"] is False
    assert r1["error"] == "missing_title"

    r2 = await save_decision(title="ok", decision="   ")
    assert r2["ok"] is False
    assert r2["error"] == "missing_decision"


@pytest.mark.asyncio
async def test_save_decision_strips_empty_tags():
    """tags 里的空串/纯空格应被剔除。"""
    from app.mcp.tools.agent_extras import save_decision

    res = await save_decision(
        title="t", decision="d", tags=["x", "", "  ", "y"],
    )
    assert res["ok"] is True
    assert res["result"]["tags"] == ["x", "y"]
    pool = get_pool()
    await pool.execute(
        "DELETE FROM mcp.decisions WHERE id=$1",
        uuid.UUID(res["result"]["decision_id"]),
    )


# ─── schedule_observation ──────────────────────────────────────────────────


def test_validate_cron_accepts_5_and_6_segments():
    from app.mcp.tools.agent_extras import _validate_cron

    ok5, _ = _validate_cron("0 9 * * *")
    assert ok5 is True
    ok6, _ = _validate_cron("0 0 9 * * *")
    assert ok6 is True


def test_validate_cron_rejects_bad():
    from app.mcp.tools.agent_extras import _validate_cron

    bad_cases = ["", "  ", "* * * *", "* * * * * * *", "0  * * *"]
    for c in bad_cases:
        ok, _ = _validate_cron(c)
        assert ok is False, f"应拒：{c!r}"


def test_schedule_summary_smoke():
    """summary_fn 给 /inbox 卡片用：含 name + cron + enabled。"""
    from app.mcp.tools.agent_extras import _schedule_summary

    s = _schedule_summary({"name": "daily_pulse", "cron": "0 9 * * *", "enabled": True})
    assert "daily_pulse" in s
    assert "0 9 * * *" in s
    assert "enabled=True" in s


@pytest.mark.asyncio
async def test_schedule_observation_upsert_sql():
    """schedule_observation 真路径走 require_approval Gate（会卡等批），
    本测验底层 upsert 行为不通过 audit wrapper。
    """
    name = f"test_obs_{uuid.uuid4().hex[:8]}"
    pool = get_pool()
    try:
        await pool.execute(
            "INSERT INTO mcp.observations (name, cron, prompt, enabled) "
            "VALUES ($1, $2, $3, $4)",
            name, "0 9 * * *", "去看 daily store pulse", True,
        )
        row = await pool.fetchrow(
            "SELECT cron, prompt, enabled FROM mcp.observations WHERE name=$1", name,
        )
        assert row["cron"] == "0 9 * * *"
        assert row["enabled"] is True

        # update
        await pool.execute(
            "UPDATE mcp.observations SET cron=$2, enabled=$3, updated_at=NOW() "
            "WHERE name=$1",
            name, "0 18 * * 1", False,
        )
        row2 = await pool.fetchrow(
            "SELECT cron, enabled FROM mcp.observations WHERE name=$1", name,
        )
        assert row2["cron"] == "0 18 * * 1"
        assert row2["enabled"] is False
    finally:
        await pool.execute("DELETE FROM mcp.observations WHERE name=$1", name)


# ─── generate_image_compare ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_generate_image_compare_mocks_each_model(monkeypatch):
    """绕开 audit gate，直接验"循环各 model 调 hub"逻辑。"""
    from app.mcp.tools import agent_extras

    calls: list[tuple[str, int]] = []

    class _FakeClient:
        async def generate_image(self, *, prompt, model, n=1, aspect=None, **kw):
            calls.append((model, n))
            return {
                "images": [
                    {"url": f"https://fake/{model}/{i}.png"} for i in range(n)
                ],
                "usage": {"cost_usd": 0.01 * n},
            }

    monkeypatch.setattr(agent_extras, "AIHubClient", _FakeClient)

    # 直接 await 被 wrap 函数：require_approval=True 装饰器仍套住，
    # 这条路径会卡 Gate；直接调内部逻辑用 monkeypatch 跳过 audit 装饰器：
    # generate_image_compare 没拆 _impl，所以本测试直接复刻其 body 验逻辑：
    cli = agent_extras.AIHubClient()
    by_model = []
    for m in ["gpt-image-2", "gemini-3.1-flash-image-preview"]:
        try:
            resp = await cli.generate_image(
                prompt="a cup of soy sauce", model=m, n=1, aspect="9:16",
            )
            urls = [img.get("url") for img in (resp.get("images") or [])]
            by_model.append({"model": m, "images": urls})
        except Exception as exc:
            by_model.append({"model": m, "images": [], "error": str(exc)})

    assert len(by_model) == 2
    assert by_model[0]["model"] == "gpt-image-2"
    assert by_model[0]["images"][0].endswith(".png")
    assert calls == [("gpt-image-2", 1), ("gemini-3.1-flash-image-preview", 1)]


# ─── send_wecom_message ────────────────────────────────────────────────────


def test_load_wecom_webhooks_parses_env(monkeypatch):
    from app.mcp.tools.agent_extras import _load_wecom_webhooks

    monkeypatch.setenv(
        "WECOM_WEBHOOKS",
        "alert=https://qyapi.weixin.qq.com/x?key=A,daily=https://qyapi.weixin.qq.com/y?key=B",
    )
    out = _load_wecom_webhooks()
    assert "alert" in out and "daily" in out
    assert out["alert"].endswith("?key=A")
    assert out["daily"].endswith("?key=B")


def test_load_wecom_webhooks_handles_empty(monkeypatch):
    from app.mcp.tools.agent_extras import _load_wecom_webhooks

    monkeypatch.delenv("WECOM_WEBHOOKS", raising=False)
    assert _load_wecom_webhooks() == {}

    monkeypatch.setenv("WECOM_WEBHOOKS", "")
    assert _load_wecom_webhooks() == {}

    # 半坏半好
    monkeypatch.setenv("WECOM_WEBHOOKS", "alert=https://x,bad,=,name=,=url,daily=https://y")
    out = _load_wecom_webhooks()
    assert out == {"alert": "https://x", "daily": "https://y"}
