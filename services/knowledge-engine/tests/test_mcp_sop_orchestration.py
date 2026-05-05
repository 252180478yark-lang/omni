"""W3a T10：gather_brief_context tool 集成测（mock search_kb / list_kbs）。"""
from __future__ import annotations

import pytest
import pytest_asyncio

from app.database import init_pool, close_pool
from app.mcp.tools import sop as _sop


@pytest_asyncio.fixture(scope="module", autouse=True)
async def _pool():
    await init_pool()
    yield
    await close_pool()


@pytest_asyncio.fixture
async def _mock_kb_search(monkeypatch):
    """让 list_kbs 返 3 个 KB（每 role 一个），search 返固定 chunks。"""
    fake_kbs = [
        {"id": "kb-auth-1", "name": "抖店运营手册", "kb_role": "authoritative"},
        {"id": "kb-tpl-1", "name": "调味品爆款拆解", "kb_role": "template"},
        {"id": "kb-priv-1", "name": "公司产品介绍", "kb_role": "private_doc"},
    ]
    fake_chunks = [
        {"kb_id": "kb-tpl-1", "title": "酱油爆款拆解 #3",
         "content": "钩子结构：先抛痛点 → 给反差 → 报价格", "score": 0.92},
        {"kb_id": "kb-auth-1", "title": "抖店运营 - 钩子规范",
         "content": "前 3 秒必须有具体数字", "score": 0.88},
    ]

    async def fake_list_kbs():
        return fake_kbs

    async def fake_retrieve(query, kb_ids, **kw):
        # 只返从被传入 kb_ids 中的 chunks
        return [c for c in fake_chunks if c["kb_id"] in kb_ids]

    monkeypatch.setattr("app.services.ingestion.list_kbs", fake_list_kbs)
    monkeypatch.setattr("app.services.rag_chain.retrieve_multi_kb", fake_retrieve)
    yield


@pytest.mark.asyncio
async def test_smoke_gather_brief_context_basic(_mock_kb_search):
    resp = await _sop.gather_brief_context(
        sku_id="SKU-TEST-1",
        channel="douyin",
    )
    assert resp["ok"] is True
    ctx = resp["result"]["kb_context"]
    # 有分区标题
    assert "爆款拆解" in ctx or "template" in ctx.lower()
    assert "运营手册" in ctx or "authoritative" in ctx.lower()
    # sources 列表非空
    assert len(resp["result"]["sources"]) >= 2

    # next_step_hint 指向 generate_brief
    assert resp["next_step_hint"]["suggested_tool"] == "generate_brief"
    sa = resp["next_step_hint"]["suggested_args"]
    assert sa["sku_id"] == "SKU-TEST-1"
    assert sa["channel"] == "douyin"
    assert "kb_context" in sa
    assert sa["kb_context"] == ctx


@pytest.mark.asyncio
async def test_smoke_gather_brief_context_no_kb_match(monkeypatch):
    """没匹配到任何 chunk → kb_context 是个友好空提示，仍然 ok=True。"""
    async def fake_list_kbs():
        return []
    async def fake_retrieve(query, kb_ids, **kw):
        return []
    monkeypatch.setattr("app.services.ingestion.list_kbs", fake_list_kbs)
    monkeypatch.setattr("app.services.rag_chain.retrieve_multi_kb", fake_retrieve)

    resp = await _sop.gather_brief_context(sku_id="SKU-X", channel="douyin")
    assert resp["ok"] is True
    assert "无 KB 命中" in resp["result"]["kb_context"] or resp["result"]["kb_context"] == "（KB 检索无命中）"
    assert resp["result"]["sources"] == []
