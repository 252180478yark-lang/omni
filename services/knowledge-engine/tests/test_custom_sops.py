"""自建 SOP 存储三 tool 测试（真 DB，照 test_portrait_lineage 风格）。

流程：save 新建 → list 查到 → 同名再 save 为 updated v2 → archive 后默认不含。
清理：name LIKE '(测试)%'。
"""
from __future__ import annotations

import pytest
import pytest_asyncio

from app.database import init_pool, close_pool, get_pool
from app.mcp.tools.custom_sops import (
    sop_archive_custom,
    sop_list_custom,
    sop_save_custom,
)

NAME = "(测试)自建SOP-单测"
_STEPS = [
    {"tool": "query_costs", "note": "先拿成本"},
    {"tool": "compute_margin", "note": "再算利润"},
]

# 跨 test 共享状态（pytest 按文件内顺序跑）
_state: dict = {}


@pytest_asyncio.fixture(scope="module", autouse=True)
async def setup_pool():
    await init_pool()
    pool = get_pool()
    await pool.execute("DELETE FROM mcp.custom_sops WHERE name LIKE '(测试)%'")
    yield
    await pool.execute("DELETE FROM mcp.custom_sops WHERE name LIKE '(测试)%'")
    await close_pool()


@pytest.mark.asyncio
async def test_save_new_creates_v1():
    out = await sop_save_custom(
        name=NAME,
        sop_md="# 测试 SOP\n1. 查成本\n2. 算利润",
        description="单测用 SOP",
        steps=_STEPS,
    )
    assert out["ok"] is True
    assert out["mode"] == "created"
    assert out["version"] == 1
    assert out["sop_id"]
    _state["sop_id"] = out["sop_id"]


@pytest.mark.asyncio
async def test_list_contains_full_fields():
    out = await sop_list_custom()
    assert out["ok"] is True
    mine = next((s for s in out["sops"] if s["name"] == NAME), None)
    assert mine is not None
    assert mine["sop_id"] == _state["sop_id"]
    assert "查成本" in mine["sop_md"]          # 全字段含 sop_md
    assert mine["steps"] == _STEPS              # jsonb 往返不变形
    assert mine["domain"] == "🧩 我的 SOP"
    assert mine["status"] == "active"
    assert mine["version"] == 1
    assert mine["updated_at"]


@pytest.mark.asyncio
async def test_same_name_save_updates_v2():
    out = await sop_save_custom(
        name=NAME,
        sop_md="# 测试 SOP v2（全量覆盖）",
        description="改过的描述",
        steps=[{"tool": "list_skus"}],
    )
    assert out["ok"] is True
    assert out["mode"] == "updated"
    assert out["version"] == 2
    assert out["sop_id"] == _state["sop_id"]    # 同名 active → 更新同一行
    # 全量覆盖验证
    got = await sop_list_custom()
    mine = next(s for s in got["sops"] if s["sop_id"] == _state["sop_id"])
    assert "v2" in mine["sop_md"]
    assert mine["description"] == "改过的描述"
    assert mine["steps"] == [{"tool": "list_skus"}]


@pytest.mark.asyncio
async def test_archive_then_default_list_excludes():
    out = await sop_archive_custom(sop_id=_state["sop_id"])
    assert out["ok"] is True
    assert out["status"] == "archived"
    # 默认 list 不含
    active = await sop_list_custom()
    assert all(s["sop_id"] != _state["sop_id"] for s in active["sops"])
    # include_archived=True 能看到
    full = await sop_list_custom(include_archived=True)
    mine = next((s for s in full["sops"] if s["sop_id"] == _state["sop_id"]), None)
    assert mine is not None
    assert mine["status"] == "archived"


@pytest.mark.asyncio
async def test_validation_errors():
    # name 空
    out = await sop_save_custom(name="  ", sop_md="x")
    assert out["ok"] is False
    assert out["error"] == "name_required"
    # sop_md 空
    out = await sop_save_custom(name="(测试)空正文", sop_md="")
    assert out["ok"] is False
    assert out["error"] == "sop_md_required"
    # steps 项缺 tool 字段
    out = await sop_save_custom(
        name="(测试)坏steps", sop_md="x", steps=[{"note": "没有 tool"}],
    )
    assert out["ok"] is False
    assert out["error"] == "steps_invalid"
    # archive 不存在的 id
    out = await sop_archive_custom(sop_id="00000000-0000-0000-0000-000000000000")
    assert out["ok"] is False
    assert out["error"] == "sop_not_found"
