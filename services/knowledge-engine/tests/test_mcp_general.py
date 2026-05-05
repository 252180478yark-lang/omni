"""W3c: general 3 tool 测试。"""
from __future__ import annotations

import os
import tempfile

import pytest
import pytest_asyncio

from app.database import init_pool, close_pool
from app.mcp.tools.general import summarize_text


@pytest_asyncio.fixture(scope="module", autouse=True)
async def setup_pool():
    await init_pool()
    yield
    await close_pool()


@pytest.mark.asyncio
async def test_summarize_text_empty():
    """空文本 → empty_text 错误。"""
    result = await summarize_text(text="")
    assert result["ok"] is False
    assert result["error"] == "empty_text"


@pytest.mark.asyncio
async def test_summarize_text_whitespace():
    """全空白 → empty_text 错误。"""
    result = await summarize_text(text="   \n\t  ")
    assert result["ok"] is False
    assert result["error"] == "empty_text"


@pytest.mark.asyncio
async def test_summarize_text_basic():
    """普通文本应返回非空摘要。"""
    text = (
        "今天天气不错，我去市场买了 3 斤苹果，每斤 5 块钱共 15 元。"
        "苹果是红富士品牌，老板说今年果园丰收所以便宜。"
        "回家路上下雨了，没带伞，淋了一身。"
    )
    result = await summarize_text(text=text)
    assert result["ok"] is True
    summary = result["result"]["summary"]
    assert isinstance(summary, str)
    assert len(summary) > 0
    assert result["result"]["length_in"] == len(text)
    assert result["result"]["length_out"] == len(summary)
    assert result["result"]["truncated"] is False
    assert "model" in result["trace"]
    assert "provider" in result["trace"]


@pytest.mark.asyncio
async def test_summarize_text_with_instruction():
    """带 instruction 时摘要应按方向走（不验内容，仅验流程跑通）。"""
    text = "苹果 5 块, 香蕉 3 块, 梨 4 块, 三种水果共 12 块。"
    result = await summarize_text(
        text=text,
        instruction="只列出水果名称，不要价格",
    )
    assert result["ok"] is True
    summary = result["result"]["summary"]
    assert len(summary) > 0


@pytest.mark.asyncio
async def test_summarize_text_truncation():
    """超长文本应被截断 + truncated=True。"""
    long_text = "测试 " * 20000
    result = await summarize_text(text=long_text, max_input_chars=1000)
    assert result["ok"] is True
    assert result["result"]["truncated"] is True
    assert result["result"]["length_in"] == len(long_text)
