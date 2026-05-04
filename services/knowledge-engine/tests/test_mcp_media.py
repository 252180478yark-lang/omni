"""T6/T8/T9：media tools 集成测。T7：ai_hub_client v2 mock 测。"""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from app.database import get_pool, init_pool, close_pool
from app.mcp.tools.media import generate_brief
from app.services.ai_hub_client import AIHubClient


@pytest_asyncio.fixture(scope="module", autouse=True)
async def _pool():
    await init_pool()
    yield
    await close_pool()


@pytest_asyncio.fixture(scope="module", autouse=True)
async def _seed_sku():
    """插测试 sku；module teardown 清。

    mvp_sku schema：id (PK) / name / category / price_min / price_max /
    specifications / douyin_product_id (NOT NULL UNIQUE)。
    generate_brief 用 id / name / category / price_min / specifications。
    """
    pool = get_pool()
    await pool.execute(
        """
        INSERT INTO mvp_sku (id, name, category, douyin_product_id,
                             price_min, price_max, specifications)
        VALUES ('_smoke_sku_001', '_smoke 测试酱油', '调味品',
                '_smoke_dy_001', 29.90, 29.90, '500ml * 1 瓶')
        ON CONFLICT (id) DO NOTHING
        """
    )
    yield
    await pool.execute("DELETE FROM mvp_sku WHERE id='_smoke_sku_001'")


@pytest.mark.asyncio
async def test_smoke_generate_brief_returns_brief_and_trace():
    """mock hub.chat 验 brief tool 链路：调 → 解析 → trace + hint。"""
    fake_hub_resp = {
        "content": "# 抖音渠道 Brief\n\n卖点：...\n场景：...\n分镜 1：xxx\n分镜 2：yyy\n分镜 3：zzz",
        "provider": "gemini",
        "model": "gemini-3-flash-preview",
    }
    with patch("app.mcp.tools.media.AIHubClient") as MC:
        MC.return_value.chat = AsyncMock(return_value=fake_hub_resp)
        r = await generate_brief(sku_id="_smoke_sku_001", channel="douyin")

    assert r["ok"] is True
    assert "Brief" in r["result"]["brief_md"] or "brief" in r["result"]["brief_md"].lower()
    assert r["trace"]["model"]
    assert r["trace"]["final_prompt"]
    assert r["next_step_hint"]["suggested_tool"] == "generate_image"
    # 建议 args 含 prompts list 让老板出分镜
    assert "prompts" in r["next_step_hint"]["suggested_args"]


@pytest.mark.asyncio
async def test_smoke_generate_brief_handles_hub_failure():
    with patch("app.mcp.tools.media.AIHubClient") as MC:
        MC.return_value.chat = AsyncMock(side_effect=RuntimeError("hub down"))
        r = await generate_brief(sku_id="_smoke_sku_001", channel="douyin")
    # tool_with_audit 的 BaseException 路径会接住 → ok=False
    assert r["ok"] is False
    assert "hub down" in r["error"]


# ── T7：ai_hub_client v2 mock 测 ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_smoke_generate_image_v2_passes_face_and_product_refs():
    captured = {}

    class FakeResp:
        def raise_for_status(self): return None
        def json(self): return {"images": [{"url": "https://fake/1.png"}]}

    class FakeClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return None
        async def post(self, url, json=None, **kw):
            captured["url"] = url
            captured["body"] = json
            return FakeResp()

    with patch("app.services.ai_hub_client.httpx.AsyncClient", return_value=FakeClient()):
        client = AIHubClient()
        r = await client.generate_image_v2(
            prompt="产品图",
            face_refs=["https://face/a.png"],
            product_refs=["https://prod/b.png"],
            style_refs=None,
            aspect="9:16",
            n=1,
            model="gpt-image-2",
            provider="openai",
        )
    assert r["images"][0]["url"] == "https://fake/1.png"
    body = captured["body"]
    # face / product 都要在 body 里某种形式表达
    flat = json.dumps(body, ensure_ascii=False)
    assert "face/a.png" in flat
    assert "prod/b.png" in flat


@pytest.mark.asyncio
async def test_smoke_generate_video_v2_passes_first_last_frame():
    captured = {}

    class FakeResp:
        def raise_for_status(self): return None
        def json(self): return {"task_id": "t-001", "status": "pending"}

    class FakeClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return None
        async def post(self, url, json=None, **kw):
            captured["body"] = json
            return FakeResp()

    with patch("app.services.ai_hub_client.httpx.AsyncClient", return_value=FakeClient()):
        client = AIHubClient()
        r = await client.generate_video_v2(
            prompt="慢镜头",
            first_frame="https://x/a.png",
            last_frame="https://x/b.png",
            duration_sec=8,
            face_refs=["https://face/m.png"],
            product_refs=None,
            aspect="9:16",
            model="seedance-2-0",
            provider="seedance",
        )
    assert r["task_id"] == "t-001"
    flat = json.dumps(captured["body"], ensure_ascii=False)
    assert "x/a.png" in flat
    assert "x/b.png" in flat


# ── T8：generate_image tool（多 prompt 并发 + 4 类 refs）──────────────────


from app.mcp.tools.media import generate_image


@pytest.mark.asyncio
async def test_smoke_generate_image_runs_multiple_prompts_concurrently():
    """3 个 prompt 一次返 3 张图。"""
    fake_responses = [
        {"images": [{"url": f"https://fake/img{i}.png"}]} for i in range(3)
    ]

    async def fake_v2(prompt, **kw):
        # 用 prompt 末位匹配返回
        for i in range(3):
            if str(i) in prompt:
                return fake_responses[i]
        return fake_responses[0]

    with patch("app.mcp.tools.media.AIHubClient") as MC:
        MC.return_value.generate_image_v2 = AsyncMock(side_effect=fake_v2)
        r = await generate_image(
            prompts=["分镜 0", "分镜 1", "分镜 2"],
            face_refs=None,
            product_refs=["https://prod.png"],
            style_refs=None,
        )
    assert r["ok"] is True
    images = r["result"]["images"]
    assert len(images) == 3
    urls = [i["url"] for i in images]
    assert all("fake/img" in u for u in urls)
    assert r["next_step_hint"]["suggested_tool"] == "generate_video"


@pytest.mark.asyncio
async def test_smoke_generate_image_partial_failure_returns_error_marker():
    async def fake_v2(prompt, **kw):
        if "fail" in prompt:
            raise RuntimeError("hub 5xx")
        return {"images": [{"url": "https://ok.png"}]}

    with patch("app.mcp.tools.media.AIHubClient") as MC:
        MC.return_value.generate_image_v2 = AsyncMock(side_effect=fake_v2)
        r = await generate_image(prompts=["ok 1", "fail 2", "ok 3"])

    assert r["ok"] is True   # 整体不挂；逐 prompt 看
    images = r["result"]["images"]
    assert len(images) == 3
    err_idx = [i for i, x in enumerate(images) if x.get("error")]
    assert err_idx == [1]
