"""tool_models.yaml 加载 + 按 tool 名查模型配置（design doc §2.5）。

调用方式：
    from app.mcp.model_config import get_model_for_tool
    cfg = get_model_for_tool("compute_margin")
    # cfg = {"provider": "anthropic", "model": "claude-opus-4-7", "temperature": 0.0}
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml  # PyYAML; FastMCP 顺带带进来，未带则需 pip install pyyaml

CONFIG_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "tool_models.yaml"
)


@lru_cache(maxsize=1)
def _load_yaml() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return {"__default__": {"provider": "anthropic", "model": "claude-sonnet-4-6", "temperature": 0.3}}
    with CONFIG_PATH.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def get_model_for_tool(
    tool_name: str,
    *,
    _override_yaml: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """按 tool 名取模型配置；查不到 fallback 到 __default__。

    `_override_yaml` 仅供测试注入。
    """
    raw = _override_yaml if _override_yaml is not None else _load_yaml()
    if tool_name in raw:
        return dict(raw[tool_name])
    default = raw.get("__default__") or {
        "provider": "anthropic",
        "model": "claude-sonnet-4-6",
        "temperature": 0.3,
    }
    return dict(default)
