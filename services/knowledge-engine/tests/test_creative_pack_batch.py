"""step 5 generate_creative_pack 批量模式（人群 × 类型 交叉）：分发逻辑测试（不调 LLM）。"""
from __future__ import annotations

import pytest
import pytest_asyncio

import app.mcp.server  # noqa: F401  # 先完整加载 server：media 当首入口会触发既有循环导入

from app.database import init_pool, close_pool
from app.mcp.tools import media
from app.mcp.tools.media import generate_creative_pack


@pytest_asyncio.fixture(scope="module", autouse=True)
async def setup_pool():
    await init_pool()
    yield
    await close_pool()


@pytest.mark.asyncio
async def test_exclusive_params():
    out = await generate_creative_pack(kind="video_planting",
                                       audience_record_id="a", audience_record_ids=["b"])
    assert out["ok"] is False and "只能传一个" in out["error"]

    out = await generate_creative_pack(kind="video_planting", kinds=["video_harvest"])
    assert out["ok"] is False and "只能传一个" in out["error"]

    out = await generate_creative_pack(kinds=["video_planting"],
                                       audience_record_ids=["a"], audience_pack_id="p1")
    assert out["ok"] is False and "audience_pack_id" in out["error"]


@pytest.mark.asyncio
async def test_invalid_kind_in_batch():
    out = await generate_creative_pack(kinds=["video_planting", "不存在的类型"],
                                       audience_record_ids=["a"])
    assert out["ok"] is False
    assert "非法 kind" in out["error"]


@pytest.mark.asyncio
async def test_missing_kind_single_mode():
    out = await generate_creative_pack(sku_id="SKU-X")
    assert out["ok"] is False and "缺 kind" in out["error"]


@pytest.mark.asyncio
async def test_cross_product_cap_and_slim_items(monkeypatch):
    """3 人群 × 3 类型 = 9 组合 → 截 6；强制 num_variants=1；items 只带 300 字摘录。"""
    calls: list[tuple] = []

    async def fake_one(*, kind, sku_id=None, audience_record_id=None,
                       audience_pack_id=None, extra_context=None,
                       num_variants=1, target_model="seedance"):
        calls.append((audience_record_id, kind, num_variants))
        if audience_record_id == "r2" and kind == "video_harvest":
            return {"ok": False, "error": "audience_record 未找到", "hint": "x"}
        return {"ok": True, "result": {
            "script_id": f"s-{audience_record_id}-{kind}",
            "script_md": "字" * 1000,
            "kind_label": kind, "sku_id": "SKU-X",
            "validation_warnings": [],
        }}

    monkeypatch.setattr(media, "_creative_pack_one", fake_one)
    out = await generate_creative_pack(
        audience_record_ids=["r1", "r2", "r3"],
        kinds=["video_soft_ad", "video_planting", "video_harvest"],
        num_variants=3,  # 批量强制 1
    )
    assert out["ok"] is True
    res = out["result"]
    assert res["batch"] is True
    assert res["total"] == 6 and res["dropped_over_cap"] == 3
    assert all(nv == 1 for _, _, nv in calls)
    # r2 × video_harvest 不在前 6 个组合里（r1×3 + r2×3 截断），软错误项按组合实际出现与否
    ok_items = [i for i in res["items"] if i["ok"]]
    for it in ok_items:
        assert len(it["excerpt"]) <= 301  # 300 + "…"
        assert "script_md" not in it
    sids = {i["script_id"] for i in ok_items}
    assert "s-r1-video_soft_ad" in sids


@pytest.mark.asyncio
async def test_batch_failure_isolation(monkeypatch):
    async def fake_one(*, kind, audience_record_id=None, **kwargs):
        if audience_record_id == "bad":
            raise TimeoutError("hub down")
        return {"ok": True, "result": {"script_id": f"s-{audience_record_id}",
                                       "script_md": "ok", "kind_label": kind,
                                       "sku_id": "SKU-X", "validation_warnings": []}}

    monkeypatch.setattr(media, "_creative_pack_one", fake_one)
    out = await generate_creative_pack(audience_record_ids=["good", "bad"],
                                       kinds=["video_planting"])
    assert out["ok"] is True
    res = out["result"]
    assert res["succeeded"] == 1 and res["failed"] == 1
    bad = next(i for i in res["items"] if not i["ok"])
    assert bad["audience_record_id"] == "bad"
    assert "TimeoutError" in bad["error"]
