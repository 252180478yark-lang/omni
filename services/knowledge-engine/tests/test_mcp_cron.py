"""W4-B 切片 4：weekly_self_review cron 后台任务测试。

只测纯函数 + _run_one_cycle 的分支，不测 forever loop。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


def test_should_run_now_first_time():
    from app.mcp.cron import _should_run_now
    now = datetime(2026, 5, 7, tzinfo=timezone.utc)
    assert _should_run_now(None, now) is True


def test_should_run_now_too_recent():
    from app.mcp.cron import _should_run_now
    now = datetime(2026, 5, 7, tzinfo=timezone.utc)
    last = now - timedelta(days=3)
    assert _should_run_now(last, now) is False


def test_should_run_now_just_due():
    from app.mcp.cron import _should_run_now
    now = datetime(2026, 5, 14, tzinfo=timezone.utc)
    last = now - timedelta(days=7, seconds=1)
    assert _should_run_now(last, now) is True


def test_should_run_now_at_boundary():
    from app.mcp.cron import _should_run_now
    now = datetime(2026, 5, 14, tzinfo=timezone.utc)
    last = now - timedelta(days=7)
    assert _should_run_now(last, now) is True  # 闭区间：恰好 7 天可跑


def test_render_weekly_markdown_full():
    from app.mcp.cron import _render_weekly_markdown

    fake_review = {
        "ok": True,
        "result": {
            "period_days": 7,
            "total_calls": 42,
            "by_tool": {"list_skus": 10, "compute_margin": 8, "search_kb": 6},
            "by_status": {"completed": 38, "error": 4},
            "by_rating": {"good": 5, "null": 37},
            "candidate_patterns": [
                {"sequence": ["list_skus", "query_costs", "compute_margin"], "occurrences": 4},
                {"sequence": ["search_kb", "generate_brief", "generate_image"], "occurrences": 3},
            ],
        },
    }
    ts = datetime(2026, 5, 7, 12, 0, 0, tzinfo=timezone.utc)
    md = _render_weekly_markdown(fake_review, ts)

    assert "# Weekly Self Review · 2026-05-07 12:00:00Z" in md
    assert "总调用 **42** 次" in md
    assert "`list_skus`: 10" in md
    assert "`completed`: 38" in md
    assert "`good`: 5" in md
    assert "list_skus → query_costs → compute_margin（4 次）" in md


def test_render_weekly_markdown_empty():
    """无数据时不崩，每节都有 _无_ 占位。"""
    from app.mcp.cron import _render_weekly_markdown

    fake_review = {
        "ok": True,
        "result": {
            "period_days": 7, "total_calls": 0,
            "by_tool": {}, "by_status": {}, "by_rating": {},
            "candidate_patterns": [],
        },
    }
    ts = datetime(2026, 5, 7, tzinfo=timezone.utc)
    md = _render_weekly_markdown(fake_review, ts)
    assert "总调用 **0** 次" in md
    assert "_无_" in md


@pytest.mark.asyncio
async def test_run_one_cycle_skips_when_not_due(monkeypatch, tmp_path):
    """last_run 太近时跳过：不调 agent_self_review，不写文件。"""
    from app.mcp import cron

    monkeypatch.setattr(cron, "AGENT_STATE_DIR", tmp_path)
    monkeypatch.setattr(cron, "LAST_RUN_FILE", tmp_path / "last_weekly_review.txt")
    monkeypatch.setattr(cron, "WEEKLY_REPORT_FILE", tmp_path / "weekly_review.md")

    now = datetime(2026, 5, 7, tzinfo=timezone.utc)
    last = now - timedelta(days=2)
    cron._write_last_run(last)

    called = {"n": 0}

    async def fake_review(period_days: int = 7):
        called["n"] += 1
        return {"ok": True, "result": {}}

    # patch 在 agent_meta 模块上（cron 里 from app.mcp.tools.agent_meta import）
    import app.mcp.tools.agent_meta as agent_meta
    monkeypatch.setattr(agent_meta, "agent_self_review", fake_review)

    res = await cron._run_one_cycle(now=now)

    assert res["ran"] is False
    assert called["n"] == 0
    assert not (tmp_path / "weekly_review.md").exists()


@pytest.mark.asyncio
async def test_run_one_cycle_runs_when_due(monkeypatch, tmp_path):
    """last_run 7 天前时跑：调 agent_self_review + 写 weekly_review.md + 更新 last_run。"""
    from app.mcp import cron

    monkeypatch.setattr(cron, "AGENT_STATE_DIR", tmp_path)
    monkeypatch.setattr(cron, "LAST_RUN_FILE", tmp_path / "last_weekly_review.txt")
    monkeypatch.setattr(cron, "WEEKLY_REPORT_FILE", tmp_path / "weekly_review.md")

    now = datetime(2026, 5, 14, tzinfo=timezone.utc)
    last = now - timedelta(days=8)  # 超过 7 天
    cron._write_last_run(last)

    async def fake_review(period_days: int = 7):
        return {
            "ok": True,
            "result": {
                "period_days": period_days,
                "total_calls": 17,
                "by_tool": {"list_skus": 10, "search_kb": 7},
                "by_status": {"completed": 17},
                "by_rating": {"null": 17},
                "candidate_patterns": [],
            },
        }

    import app.mcp.tools.agent_meta as agent_meta
    monkeypatch.setattr(agent_meta, "agent_self_review", fake_review)

    res = await cron._run_one_cycle(now=now)

    assert res["ran"] is True
    assert res["report_path"].endswith("weekly_review.md")
    md = (tmp_path / "weekly_review.md").read_text(encoding="utf-8")
    assert "总调用 **17** 次" in md
    assert "`list_skus`: 10" in md

    # last_run 已更新为 now
    new_last = cron._read_last_run()
    assert new_last == now


@pytest.mark.asyncio
async def test_run_one_cycle_first_time_runs(monkeypatch, tmp_path):
    """无 last_run 文件 → 视为从未跑过 → 立即跑。"""
    from app.mcp import cron

    monkeypatch.setattr(cron, "AGENT_STATE_DIR", tmp_path)
    monkeypatch.setattr(cron, "LAST_RUN_FILE", tmp_path / "last_weekly_review.txt")
    monkeypatch.setattr(cron, "WEEKLY_REPORT_FILE", tmp_path / "weekly_review.md")

    async def fake_review(period_days: int = 7):
        return {"ok": True, "result": {"period_days": 7, "total_calls": 0,
                                       "by_tool": {}, "by_status": {},
                                       "by_rating": {}, "candidate_patterns": []}}

    import app.mcp.tools.agent_meta as agent_meta
    monkeypatch.setattr(agent_meta, "agent_self_review", fake_review)

    now = datetime(2026, 5, 7, tzinfo=timezone.utc)
    res = await cron._run_one_cycle(now=now)

    assert res["ran"] is True
    assert (tmp_path / "weekly_review.md").exists()
    assert (tmp_path / "last_weekly_review.txt").exists()


@pytest.mark.asyncio
async def test_run_one_cycle_swallows_review_failure(monkeypatch, tmp_path):
    """agent_self_review 抛异常时不挂、返 ran=False reason 含 failed。"""
    from app.mcp import cron

    monkeypatch.setattr(cron, "AGENT_STATE_DIR", tmp_path)
    monkeypatch.setattr(cron, "LAST_RUN_FILE", tmp_path / "last_weekly_review.txt")
    monkeypatch.setattr(cron, "WEEKLY_REPORT_FILE", tmp_path / "weekly_review.md")

    async def boom(period_days: int = 7):
        raise RuntimeError("DB 抽风")

    import app.mcp.tools.agent_meta as agent_meta
    monkeypatch.setattr(agent_meta, "agent_self_review", boom)

    res = await cron._run_one_cycle(now=datetime(2026, 5, 7, tzinfo=timezone.utc))
    assert res["ran"] is False
    assert "failed" in res["reason"]
    # 报告文件 + last_run 都不应被写
    assert not (tmp_path / "weekly_review.md").exists()
    assert not (tmp_path / "last_weekly_review.txt").exists()


def test_read_last_run_handles_z_suffix(monkeypatch, tmp_path):
    """老板手动写 'Z' 后缀也兼容（fromisoformat 不识别）。"""
    from app.mcp import cron
    monkeypatch.setattr(cron, "LAST_RUN_FILE", tmp_path / "last_weekly_review.txt")
    (tmp_path / "last_weekly_review.txt").write_text(
        "2026-05-01T00:00:00Z", encoding="utf-8"
    )
    last = cron._read_last_run()
    assert last == datetime(2026, 5, 1, tzinfo=timezone.utc)


def test_read_last_run_garbage_returns_none(monkeypatch, tmp_path):
    from app.mcp import cron
    monkeypatch.setattr(cron, "LAST_RUN_FILE", tmp_path / "last_weekly_review.txt")
    (tmp_path / "last_weekly_review.txt").write_text("not a date", encoding="utf-8")
    assert cron._read_last_run() is None


# ============================================================
# 切片 11：daily_pulse cron 测试
# ============================================================


def test_render_daily_pulse_markdown_full():
    from app.mcp.cron import _render_daily_pulse_markdown

    store_daily = {
        "ok": True,
        "result": {
            "date": "2026-05-06",
            "metrics": [
                {"metric_name": "gmv_paid", "value": "3120.50"},
                {"metric_name": "visit_uv", "value": "1245"},
                {"metric_name": "conversion_rate", "value": "0.0305"},
            ],
            "count": 3,
        },
    }
    brand_mind = {
        "ok": True,
        "result": {
            "date": "2026-05-06",
            "rows": [
                {
                    "brand_id": "B001",
                    "sku_id": "SKU-X",
                    "reputation": 78,
                    "preference": 65,
                    "connection": 82,
                },
            ],
            "count": 1,
        },
    }
    md = _render_daily_pulse_markdown(
        store_daily, brand_mind, datetime(2026, 5, 7, 9, 0, tzinfo=timezone.utc)
    )
    assert "# Daily Pulse · 2026-05-07 09:00:00Z" in md
    assert "## 罗盘全店日报" in md
    assert "`gmv_paid`: 3120.50" in md
    assert "## 云图品牌心智" in md
    assert "brand=`B001`" in md
    assert "reputation=78" in md


def test_render_daily_pulse_markdown_handles_failures():
    from app.mcp.cron import _render_daily_pulse_markdown

    store_daily = {"ok": False, "error": "no_data", "hint": "去 scout 跑 runbook A"}
    brand_mind = {"ok": False, "error": "no_data", "hint": "yuntu runbook 没数据"}

    md = _render_daily_pulse_markdown(
        store_daily, brand_mind, datetime(2026, 5, 7, 9, 0, tzinfo=timezone.utc)
    )
    assert "拉取失败" in md
    assert "`no_data`" in md
    assert "scout 跑 runbook A" in md
    assert "yuntu runbook 没数据" in md


def test_render_daily_pulse_markdown_truncates_long_brand_rows():
    from app.mcp.cron import _render_daily_pulse_markdown

    store_daily = {"ok": False, "error": "no_data", "hint": ""}
    brand_mind = {
        "ok": True,
        "result": {
            "date": "2026-05-06",
            "rows": [
                {"brand_id": f"B{i}", "sku_id": f"S{i}",
                 "reputation": i, "preference": i, "connection": i}
                for i in range(8)
            ],
            "count": 8,
        },
    }
    md = _render_daily_pulse_markdown(
        store_daily, brand_mind, datetime(2026, 5, 7, 9, 0, tzinfo=timezone.utc)
    )
    # 只列前 5 + 一行省略提示
    assert "brand=`B4`" in md
    assert "brand=`B5`" not in md
    assert "省略 3 行" in md


@pytest.mark.asyncio
async def test_run_daily_pulse_cycle_skips_when_recent(monkeypatch, tmp_path):
    from app.mcp import cron

    monkeypatch.setattr(cron, "AGENT_STATE_DIR", tmp_path)
    monkeypatch.setattr(cron, "DAILY_PULSE_LAST_FILE", tmp_path / "last_daily_pulse.txt")
    monkeypatch.setattr(cron, "DAILY_PULSE_REPORT_FILE", tmp_path / "daily_pulse.md")

    now = datetime(2026, 5, 7, 9, 0, tzinfo=timezone.utc)
    cron._write_last_run(now - timedelta(hours=12), tmp_path / "last_daily_pulse.txt")

    called = {"n": 0}

    async def fake_store(date=None):
        called["n"] += 1
        return {"ok": True, "result": {"date": "x", "metrics": [], "count": 0}}

    async def fake_brand(date=None):
        called["n"] += 1
        return {"ok": True, "result": {"date": "x", "rows": [], "count": 0}}

    import app.mcp.tools.scout as scout
    monkeypatch.setattr(scout, "fetch_compass_store_daily", fake_store)
    monkeypatch.setattr(scout, "fetch_yuntu_brand_mind", fake_brand)

    res = await cron._run_daily_pulse_cycle(now=now)
    assert res["ran"] is False
    assert called["n"] == 0
    assert not (tmp_path / "daily_pulse.md").exists()


@pytest.mark.asyncio
async def test_run_daily_pulse_cycle_runs_when_due(monkeypatch, tmp_path):
    from app.mcp import cron

    monkeypatch.setattr(cron, "AGENT_STATE_DIR", tmp_path)
    monkeypatch.setattr(cron, "DAILY_PULSE_LAST_FILE", tmp_path / "last_daily_pulse.txt")
    monkeypatch.setattr(cron, "DAILY_PULSE_REPORT_FILE", tmp_path / "daily_pulse.md")

    async def fake_store(date=None):
        return {
            "ok": True,
            "result": {
                "date": "2026-05-06",
                "metrics": [{"metric_name": "gmv_paid", "value": "100"}],
                "count": 1,
            },
        }

    async def fake_brand(date=None):
        return {"ok": True, "result": {"date": "2026-05-06", "rows": [], "count": 0}}

    import app.mcp.tools.scout as scout
    monkeypatch.setattr(scout, "fetch_compass_store_daily", fake_store)
    monkeypatch.setattr(scout, "fetch_yuntu_brand_mind", fake_brand)

    now = datetime(2026, 5, 7, 9, 0, tzinfo=timezone.utc)
    res = await cron._run_daily_pulse_cycle(now=now)
    assert res["ran"] is True
    assert (tmp_path / "daily_pulse.md").exists()
    md = (tmp_path / "daily_pulse.md").read_text(encoding="utf-8")
    assert "gmv_paid" in md

    # last_run 已写
    new_last = cron._read_last_run(tmp_path / "last_daily_pulse.txt")
    assert new_last == now


@pytest.mark.asyncio
async def test_run_daily_pulse_cycle_swallows_exceptions(monkeypatch, tmp_path):
    """fetch_* 抛异常时 cycle 不挂、md 写"拉取失败" + last_run 仍更新（避免疯狂重试）。"""
    from app.mcp import cron

    monkeypatch.setattr(cron, "AGENT_STATE_DIR", tmp_path)
    monkeypatch.setattr(cron, "DAILY_PULSE_LAST_FILE", tmp_path / "last_daily_pulse.txt")
    monkeypatch.setattr(cron, "DAILY_PULSE_REPORT_FILE", tmp_path / "daily_pulse.md")

    async def boom_store(date=None):
        raise RuntimeError("DB 抽风")

    async def boom_brand(date=None):
        raise RuntimeError("yuntu 抽风")

    import app.mcp.tools.scout as scout
    monkeypatch.setattr(scout, "fetch_compass_store_daily", boom_store)
    monkeypatch.setattr(scout, "fetch_yuntu_brand_mind", boom_brand)

    now = datetime(2026, 5, 7, 9, 0, tzinfo=timezone.utc)
    res = await cron._run_daily_pulse_cycle(now=now)
    assert res["ran"] is True  # 仍然算"跑过"，避免疯狂重试
    md = (tmp_path / "daily_pulse.md").read_text(encoding="utf-8")
    assert "拉取失败" in md
    assert "exception" in md


# ============================================================
# 切片 11：dynamic_block_refresh cron 测试
# ============================================================


@pytest.mark.asyncio
async def test_run_dynamic_refresh_cycle_skips_when_recent(monkeypatch, tmp_path):
    from app.mcp import cron

    monkeypatch.setattr(cron, "DYNAMIC_REFRESH_LAST_FILE", tmp_path / "last_dynamic_refresh.txt")

    now = datetime(2026, 5, 7, tzinfo=timezone.utc)
    cron._write_last_run(now - timedelta(days=3), tmp_path / "last_dynamic_refresh.txt")

    called = {"n": 0}

    async def fake_refresh():
        called["n"] += 1
        return {"ok": True, "result": {"stats": {}}}

    import app.mcp.tools.agent_meta as agent_meta
    monkeypatch.setattr(agent_meta, "_refresh_impl", fake_refresh)

    res = await cron._run_dynamic_refresh_cycle(now=now)
    assert res["ran"] is False
    assert called["n"] == 0


@pytest.mark.asyncio
async def test_run_dynamic_refresh_cycle_runs_when_due(monkeypatch, tmp_path):
    from app.mcp import cron

    monkeypatch.setattr(cron, "DYNAMIC_REFRESH_LAST_FILE", tmp_path / "last_dynamic_refresh.txt")

    async def fake_refresh():
        return {
            "ok": True,
            "result": {
                "stats": {"active_skus": 14, "missing_cost": 10, "pending_gates": 0},
            },
        }

    import app.mcp.tools.agent_meta as agent_meta
    monkeypatch.setattr(agent_meta, "_refresh_impl", fake_refresh)

    now = datetime(2026, 5, 14, tzinfo=timezone.utc)
    res = await cron._run_dynamic_refresh_cycle(now=now)
    assert res["ran"] is True
    assert res["stats"]["active_skus"] == 14

    # last_run 已写
    new_last = cron._read_last_run(tmp_path / "last_dynamic_refresh.txt")
    assert new_last == now


@pytest.mark.asyncio
async def test_run_dynamic_refresh_cycle_swallows_exception(monkeypatch, tmp_path):
    from app.mcp import cron

    monkeypatch.setattr(cron, "DYNAMIC_REFRESH_LAST_FILE", tmp_path / "last_dynamic_refresh.txt")

    async def boom():
        raise RuntimeError("DB 抽风")

    import app.mcp.tools.agent_meta as agent_meta
    monkeypatch.setattr(agent_meta, "_refresh_impl", boom)

    res = await cron._run_dynamic_refresh_cycle(
        now=datetime(2026, 5, 7, tzinfo=timezone.utc)
    )
    assert res["ran"] is False
    assert res["reason"] == "refresh_failed"
    assert not (tmp_path / "last_dynamic_refresh.txt").exists()
