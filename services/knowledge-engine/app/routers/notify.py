"""W6 multi-device: 长任务完成 / human gate 触发时自动推企业微信.

Frontend ws-handler 在收到 Claude Code task_done 时 fetch 这个 endpoint,
KE 内部直接 POST 企微 webhook (不走 send_wecom_message 那个 Human Gate wrapper).

老板出差时用 — 任务跑完手机收到推送, 直接打开链接看结果.

依赖 .env 配置:
  WECOM_WEBHOOKS='task_done=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx'

没配则 endpoint 返 {ok: false, skipped: true} — 不报错, 不打断 frontend 流程.
"""

import logging
import os
from typing import Optional

import httpx
from fastapi import APIRouter
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/notify", tags=["notify"])


class TaskDoneNotify(BaseModel):
    session_id: str
    session_title: Optional[str] = None
    duration_ms: int = 0
    total_cost_usd: float = 0.0
    summary: Optional[str] = Field(default=None, description="任务最后一条消息摘要 (前 200 字)")
    channel: str = Field(default="task_done", description="WECOM_WEBHOOKS 里的 channel 名")


class HumanGateNotify(BaseModel):
    gate_id: str
    tool_name: str
    summary: str
    channel: str = Field(default="human_gate")


def _load_wecom_webhooks() -> dict[str, str]:
    """读 .env 里的 WECOM_WEBHOOKS, 格式: 'a=url1,b=url2'."""
    raw = os.environ.get("WECOM_WEBHOOKS", "").strip()
    if not raw:
        return {}
    out = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if "=" not in pair:
            continue
        k, v = pair.split("=", 1)
        k, v = k.strip(), v.strip()
        if k and v:
            out[k] = v
    return out


async def _post_wecom(channel: str, content: str) -> dict:
    webhooks = _load_wecom_webhooks()
    if not webhooks:
        return {"ok": False, "skipped": True, "reason": "WECOM_WEBHOOKS 未配置"}
    url = webhooks.get(channel)
    if not url:
        # fallback: 用第一个可用 channel
        if webhooks:
            url = next(iter(webhooks.values()))
        else:
            return {"ok": False, "skipped": True, "reason": f"channel={channel} 不存在"}
    try:
        payload = {"msgtype": "text", "text": {"content": content}}
        async with httpx.AsyncClient(timeout=10.0) as cli:
            r = await cli.post(url, json=payload)
            r.raise_for_status()
            data = r.json()
    except Exception as exc:
        logger.warning("notify wecom failed: %s", exc)
        return {"ok": False, "skipped": False, "error": str(exc)}
    if data.get("errcode") != 0:
        return {"ok": False, "skipped": False, "errmsg": data.get("errmsg")}
    return {"ok": True}


def _format_duration(ms: int) -> str:
    if ms < 1000:
        return f"{ms}ms"
    s = ms // 1000
    if s < 60:
        return f"{s}s"
    m, s = divmod(s, 60)
    if m < 60:
        return f"{m}m {s}s"
    h, m = divmod(m, 60)
    return f"{h}h {m}m"


@router.post("/task-done")
async def notify_task_done(body: TaskDoneNotify):
    """Frontend ws-handler 在 task_done 时 fire-and-forget 调."""
    title = body.session_title or body.session_id[:8]
    dur = _format_duration(body.duration_ms)
    cost = f"${body.total_cost_usd:.4f}" if body.total_cost_usd else "—"
    lines = [
        "✅ omni 任务完成",
        f"会话: {title}",
        f"用时: {dur}",
        f"花费: {cost}",
    ]
    if body.summary:
        lines.append(f"摘要: {body.summary[:200]}")
    content = "\n".join(lines)
    result = await _post_wecom(body.channel, content)
    return {"ok": result.get("ok", False), "detail": result}


@router.post("/human-gate")
async def notify_human_gate(body: HumanGateNotify):
    """Human Gate 新建时调 (KE 内部 publish 完 redis 再额外 fetch 这个)."""
    content = (
        "⚠️ 需要你点头\n"
        f"工具: {body.tool_name}\n"
        f"摘要: {body.summary[:300]}\n"
        f"gate_id: {body.gate_id[:8]}"
    )
    result = await _post_wecom(body.channel, content)
    return {"ok": result.get("ok", False), "detail": result}


@router.get("/health")
async def notify_health():
    webhooks = _load_wecom_webhooks()
    return {
        "ok": True,
        "channels_configured": sorted(webhooks.keys()),
        "hint": (
            "在 .env 配 WECOM_WEBHOOKS='task_done=https://...,human_gate=https://...' 开启推送; "
            "未配时 notify endpoint 返 skipped=true 不影响业务"
        ),
    }
