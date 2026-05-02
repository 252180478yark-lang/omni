"""跨服务调用 knowledge-engine 的 prompt 飞轮端点。

提供两个能力：
  - render_rules_suffix(node_id, scope)  — 生成前拼规则到 prompt 末尾
  - log_feedback(node_id, ...)           — 生成后留痕供后续追溯

两个函数都做了失败降级：任何异常都返回空字符串/None，不阻塞主业务。
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_KE_BASE = settings.knowledge_engine_url.rstrip("/")
_RENDER_URL = f"{_KE_BASE}/api/v1/prompt/render-rules"
_FEEDBACK_URL = f"{_KE_BASE}/api/v1/prompt/feedback"


async def render_rules_suffix(node_id: str, scope: dict | None = None) -> str:
    """从 knowledge-engine 拉取指定节点的规则 suffix。失败返回空字符串。"""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                _RENDER_URL,
                json={"node_id": node_id, "scope": scope},
            )
            if resp.status_code != 200:
                return ""
            data = (resp.json() or {}).get("data") or {}
            return data.get("suffix") or ""
    except Exception as exc:
        logger.debug("render_rules_suffix fail node=%s: %s", node_id, exc)
        return ""


async def log_feedback(
    node_id: str,
    *,
    input_ref: dict | None = None,
    full_prompt: str | None = None,
    output: str | None = None,
) -> str | None:
    """在 knowledge-engine 记录一次生成的留痕（rating=None 表示待反馈）。"""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                _FEEDBACK_URL,
                json={
                    "node_id": node_id,
                    "input_ref": input_ref,
                    "full_prompt": (full_prompt or "")[:50000],
                    "output": (output or "")[:20000],
                },
            )
            if resp.status_code != 200:
                return None
            data = (resp.json() or {}).get("data") or {}
            return data.get("id")
    except Exception as exc:
        logger.debug("log_feedback fail node=%s: %s", node_id, exc)
        return None
