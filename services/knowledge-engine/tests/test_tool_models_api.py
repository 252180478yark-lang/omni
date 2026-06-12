"""工具模型配置 API 测试（真服务 http，照 test_mcp_catalog 风格）。

流程：GET 列表含 generate_selling_points_matrix 且 overridden=False
→ PUT 改 provider=openai model=gpt-5.4-mini → GET 见 overridden=True 且生效值变
→ 容器内 get_model_for_tool 直查确认热生效（local overlay mtime 重读，不用重启）
→ DELETE 恢复 → GET overridden=False。结束必恢复原状（finally DELETE）。
"""
from __future__ import annotations

import httpx

BASE = "http://localhost:8002/api/v1/mcp/catalog"
TOOL = "generate_selling_points_matrix"


def _get_tool(payload: dict, name: str) -> dict | None:
    return next((t for t in payload["tools"] if t["name"] == name), None)


def _fetch() -> dict:
    r = httpx.get(f"{BASE}/tool-models", timeout=15)
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is True
    return j


def test_tool_models_get_shape():
    j = _fetch()
    # __default__ 单独给
    assert j["default"].get("provider")
    assert j["default"].get("model")
    # keyed 工具在列且字段齐
    t = _get_tool(j, TOOL)
    assert t is not None
    assert t["provider"] and t["model"]
    assert isinstance(t["overridden"], bool)
    # providers 从 hub 拉（不可达时为空 + warning，不挂）
    assert isinstance(j["providers"], list)
    if j["providers"]:
        p = j["providers"][0]
        assert "name" in p and "api_key_set" in p and "default_chat_model" in p
    else:
        assert j.get("warning")


def test_tool_models_put_override_hot_reload_then_delete_restore():
    base_t = _get_tool(_fetch(), TOOL)
    assert base_t is not None
    assert base_t["overridden"] is False, "测试前提：该 tool 没有残留 override（残留先 DELETE）"
    base_provider, base_model = base_t["provider"], base_t["model"]

    try:
        # PUT 改 provider/model → 写 local overlay
        r = httpx.put(
            f"{BASE}/tool-models",
            json={"tool_name": TOOL, "provider": "openai", "model": "gpt-5.4-mini"},
            timeout=15,
        )
        assert r.status_code == 200
        j = r.json()
        assert j["ok"] is True
        assert j["effective"]["provider"] == "openai"
        assert j["effective"]["model"] == "gpt-5.4-mini"

        # GET 见 overridden=True 且生效值变
        t = _get_tool(_fetch(), TOOL)
        assert t["overridden"] is True
        assert t["provider"] == "openai"
        assert t["model"] == "gpt-5.4-mini"
        # local 只盖 provider/model：base 的 max_tokens 等键保留（逐 key 浅合并）
        assert t.get("max_tokens") == base_t.get("max_tokens")

        # 容器内 get_model_for_tool 直查确认热生效（pytest 与服务读同一份 overlay 文件）
        from app.mcp.model_config import get_model_for_tool

        cfg = get_model_for_tool(TOOL)
        assert cfg["provider"] == "openai"
        assert cfg["model"] == "gpt-5.4-mini"
    finally:
        # 测试结束必须恢复原状
        rd = httpx.delete(f"{BASE}/tool-models/{TOOL}", timeout=15)
        assert rd.status_code == 200
        assert rd.json()["ok"] is True

    # DELETE 后恢复 base 生效值
    t2 = _get_tool(_fetch(), TOOL)
    assert t2["overridden"] is False
    assert t2["provider"] == base_provider
    assert t2["model"] == base_model

    from app.mcp import model_config as mc
    from app.mcp.model_config import get_model_for_tool

    # pytest 进程自己的 mtime 缓存可能跟 DELETE 重写同秒，清掉再直查（服务进程写时自清，不受影响）
    mc._cache.clear()
    cfg2 = get_model_for_tool(TOOL)
    assert cfg2["provider"] == base_provider
    assert cfg2["model"] == base_model


def test_tool_models_put_rejects_unknown_provider_when_hub_up():
    j = _fetch()
    if not j["providers"]:
        return  # hub 不可达 → 校验跳过放行，本断言不适用
    r = httpx.put(
        f"{BASE}/tool-models",
        json={"tool_name": "(测试)不存在的工具", "provider": "no_such_provider_xyz", "model": "m"},
        timeout=15,
    )
    assert r.status_code == 422
    assert "unknown_provider" in r.json()["error"]
