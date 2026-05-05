"""W3c: general 3 tool 测试。"""
from __future__ import annotations

import os
import tempfile

import pytest
import pytest_asyncio

from app.database import init_pool, close_pool
from app.mcp.tools.general import summarize_text, parse_long_doc_with_gemini


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


@pytest.mark.asyncio
async def test_parse_long_doc_file_not_found():
    """文件不存在 → file_not_found。"""
    result = await parse_long_doc_with_gemini(file_path="/nonexistent/path.pdf")
    assert result["ok"] is False
    assert result["error"] == "file_not_found"


@pytest.mark.asyncio
async def test_parse_long_doc_is_directory():
    """传目录 → is_directory。"""
    result = await parse_long_doc_with_gemini(file_path="/tmp")
    assert result["ok"] is False
    assert result["error"] == "is_directory"


@pytest.mark.asyncio
async def test_parse_long_doc_basic_txt():
    """普通 .txt 文件应解析成功。"""
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False, mode="w", encoding="utf-8") as f:
        f.write(
            "## 第一章 产品概况\n这是一段产品描述。营收 1000 万。\n\n"
            "## 第二章 用户画像\n核心用户 25-35 岁女性。\n"
        )
        tmp = f.name

    try:
        result = await parse_long_doc_with_gemini(file_path=tmp)
        assert result["ok"] is True
        outline = result["result"]["markdown_outline"]
        assert isinstance(outline, str)
        assert len(outline) > 0
        assert result["result"]["source_type"] == "text"
        assert result["result"]["truncated"] is False
        assert "model" in result["trace"]
    finally:
        os.unlink(tmp)


@pytest.mark.asyncio
async def test_parse_long_doc_with_instruction():
    """带 instruction 应正常返回（不验内容，仅验流程跑通）。"""
    with tempfile.NamedTemporaryFile(suffix=".md", delete=False, mode="w", encoding="utf-8") as f:
        f.write("# 标题\n卖点 1: 价格便宜\n卖点 2: 质量好\n卖点 3: 配送快\n")
        tmp = f.name

    try:
        result = await parse_long_doc_with_gemini(
            file_path=tmp,
            instruction="只抽取卖点列表",
        )
        assert result["ok"] is True
        assert len(result["result"]["markdown_outline"]) > 0
    finally:
        os.unlink(tmp)
