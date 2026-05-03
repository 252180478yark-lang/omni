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


def test_anti_ai_human_voice_contains_three_pillars():
    """常量必须三块都齐：说人话 / 反幻觉 / 去 AI 化。"""
    from app.mcp.prompt_constraints import ANTI_AI_HUMAN_VOICE
    assert "说人话" in ANTI_AI_HUMAN_VOICE
    assert "反幻觉" in ANTI_AI_HUMAN_VOICE
    assert "去 AI 化" in ANTI_AI_HUMAN_VOICE


def test_anti_ai_human_voice_lists_specific_bans():
    """关键禁词样本必须出现，否则 prompt 失效。"""
    from app.mcp.prompt_constraints import ANTI_AI_HUMAN_VOICE
    for word in ["作为 AI", "希望对您有帮助", "综上", "以下是"]:
        assert word in ANTI_AI_HUMAN_VOICE, f"missing forbidden phrase: {word}"


def test_ai_hub_client_importable():
    from app.services.ai_hub_client import AIHubClient
    c = AIHubClient(base_url="http://example.invalid")
    # 三个核心方法都存在
    assert callable(c.chat)
    assert callable(c.generate_image)
    assert callable(c.generate_video)
    assert c.base_url == "http://example.invalid"
