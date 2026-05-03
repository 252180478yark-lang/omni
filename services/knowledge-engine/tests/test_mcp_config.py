"""单测：MCP 基础类型 / 模型配置 / prompt 常量。

不依赖 DB，纯模块测试。
"""
from app.mcp.types import ToolSuccess, ToolError


def test_tool_success_minimal():
    s: ToolSuccess = {"ok": True, "data": [1, 2, 3]}
    assert s["ok"] is True
    assert s["data"] == [1, 2, 3]


def test_tool_error_minimal():
    e: ToolError = {"ok": False, "error": "sku_not_found", "hint": "调 list_skus"}
    assert e["ok"] is False
    assert e["error"] == "sku_not_found"
    assert e["hint"] == "调 list_skus"
