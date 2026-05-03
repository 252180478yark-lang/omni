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


def test_model_config_default_lookup():
    from app.mcp.model_config import get_model_for_tool
    cfg = get_model_for_tool("any_unknown_tool")
    assert cfg["provider"] == "anthropic"
    assert cfg["model"] == "claude-sonnet-4-6"
    assert cfg["temperature"] == 0.3


def test_model_config_explicit_override():
    """加一个虚构条目验证按名查询生效。"""
    from app.mcp.model_config import _load_yaml, get_model_for_tool
    raw = _load_yaml()
    raw["_test_tool"] = {"provider": "x", "model": "y", "temperature": 0.0}
    # get_model_for_tool 内部也读同一份缓存，验证 override 命中
    cfg = get_model_for_tool("_test_tool", _override_yaml=raw)
    assert cfg["provider"] == "x"
    assert cfg["model"] == "y"
