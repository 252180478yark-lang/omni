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
