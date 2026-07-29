"""W4-B 切片 5：W4 加分 5 个 tool（design doc §3.2 W4 加分）。

| tool | 描述 | appr |
|---|---|---|
| save_decision | 写一行决策日志到 mcp.decisions | F |
| schedule_observation | 登记主动巡检任务到 mcp.observations | T |
| generate_image_compare | 多 model A/B 对比生图 | T |
| send_wecom_message | 企微 webhook 通知 | T |
| dy_publish_creative | 抖店发布商品/创意（stub） | T 高危 |

实现取舍：
- save_decision / schedule_observation：纯 DB 写，不调 LLM
- generate_image_compare：复用 ai_hub_client.generate_image，循环 N 个 model
- send_wecom_message：webhook URL 由 .env 提供 channel→url 映射
  （WECOM_WEBHOOKS='alert=https://...,daily=https://...'）；空配置返 hint
- dy_publish_creative：MVP stub。返 would_publish=True，不调真抖店 API；
  Gate 批后才走，老板后续接 SDK。
"""
from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from app.database import get_pool
from app.mcp.audit import tool_with_audit
from app.mcp.approval_audit import approval_tool_with_audit
from app.mcp.server import mcp
from app.mcp.trace import build_trace
from app.services.ai_hub_client import AIHubClient

logger = logging.getLogger(__name__)


# ─── save_decision (F) ─────────────────────────────────────────────────────


@tool_with_audit(mcp, require_approval=False)
async def save_decision(
    title: str,
    decision: str,
    context: str = "",
    tags: list[str] | None = None,
) -> dict:
    """记录一条决策到 mcp.decisions。

    老板说"刚拍板了 X"时随手存。F 类不走 Gate（high-volume）。

    Args:
        title: 一行总结（如"sku-X 暂停天猫渠道"）
        decision: 实际决定（多行 markdown 也行）
        context: 当时背景/数据/对话摘要（可空）
        tags: 自由 tag 数组（如 ['sku-X', 'pricing']）

    Returns:
        {ok, result: {decision_id, created_at}}
    """
    title = (title or "").strip()
    decision = (decision or "").strip()
    if not title:
        return {"ok": False, "error": "missing_title", "hint": "title 不能为空"}
    if not decision:
        return {"ok": False, "error": "missing_decision", "hint": "decision 不能为空"}

    tags_list = [t.strip() for t in (tags or []) if t and t.strip()]

    pool = get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO mcp.decisions (title, decision, context, tags)
        VALUES ($1, $2, $3, $4)
        RETURNING id, created_at
        """,
        title,
        decision,
        context.strip() or None,
        tags_list,
    )
    return {
        "ok": True,
        "result": {
            "decision_id": str(row["id"]),
            "created_at": row["created_at"].isoformat(),
            "title": title,
            "tags": tags_list,
            "next_step_hint": (
                "已落 mcp.decisions。老板可在 /agent-log 或 SQL 反查；"
                "后续 list_decisions tool 出来再补 query。"
            ),
        },
    }


# ─── schedule_observation (T) ──────────────────────────────────────────────


def _schedule_summary(args: dict) -> str:
    name = args.get("name") or "<noname>"
    cron = args.get("cron") or "<nocron>"
    enabled = args.get("enabled", True)
    return f"schedule_observation: name={name} cron={cron} enabled={enabled}"


def _validate_cron(expr: str) -> tuple[bool, str]:
    """最简 cron 校验：5 段或 6 段，每段非空。不接 croniter（避免新依赖）。

    严格性：能挡明显错误（空字符串/段数不对）；具体语义不验，老板自己写对。
    """
    if not expr or not expr.strip():
        return False, "cron 表达式为空"
    parts = expr.strip().split()
    if len(parts) not in (5, 6):
        return False, f"cron 段数应为 5 或 6，实际 {len(parts)}"
    if any(not p for p in parts):
        return False, "cron 表达式含空段"
    return True, ""


@approval_tool_with_audit(
    mcp,
    summary_fn=_schedule_summary,
)
async def schedule_observation(
    name: str,
    cron: str,
    prompt: str,
    enabled: bool = True,
) -> dict:
    """登记一个主动巡检任务到 mcp.observations（require_approval=True）。

    本 tool 只做"登记"——cron 真触发由老板侧 Windows Task Scheduler 调
    `python -m app.observation.run_one --name <X>` 完成（design doc §4.4）。
    name 唯一，二次调同名做 upsert 更新 cron/prompt/enabled。

    Args:
        name: 唯一名（如 daily_store_pulse）
        cron: 5/6 段 cron 表达式（如 "0 9 * * *"）
        prompt: Claude headless 拉起来后的 prompt 或 skill 触发词
        enabled: 是否启用（默认 True；False 即软停）

    Returns:
        {ok, result: {observation_id, name, cron, enabled, action: created|updated}}
    """
    name = (name or "").strip()
    cron = (cron or "").strip()
    prompt = (prompt or "").strip()
    if not name:
        return {"ok": False, "error": "missing_name", "hint": "name 不能为空"}
    if not prompt:
        return {"ok": False, "error": "missing_prompt", "hint": "prompt 不能为空"}

    ok_cron, cron_err = _validate_cron(cron)
    if not ok_cron:
        return {"ok": False, "error": "invalid_cron", "hint": cron_err}

    pool = get_pool()
    existing = await pool.fetchrow(
        "SELECT id FROM mcp.observations WHERE name=$1", name,
    )
    if existing:
        row = await pool.fetchrow(
            """
            UPDATE mcp.observations
               SET cron=$2, prompt=$3, enabled=$4, updated_at=NOW()
             WHERE name=$1
            RETURNING id, name, cron, enabled
            """,
            name, cron, prompt, enabled,
        )
        action = "updated"
    else:
        row = await pool.fetchrow(
            """
            INSERT INTO mcp.observations (name, cron, prompt, enabled)
            VALUES ($1, $2, $3, $4)
            RETURNING id, name, cron, enabled
            """,
            name, cron, prompt, enabled,
        )
        action = "created"

    return {
        "ok": True,
        "result": {
            "observation_id": str(row["id"]),
            "name": row["name"],
            "cron": row["cron"],
            "enabled": row["enabled"],
            "action": action,
            "next_step_hint": (
                f"已{action}。真触发需在老板 Windows Task Scheduler 配 cron "
                f"调 `python -m app.observation.run_one --name {name}` "
                "（或后续切片接入 KE 内部 cron loop）。"
            ),
        },
    }


# ─── generate_image_compare (T) ────────────────────────────────────────────


def _img_compare_summary(args: dict) -> str:
    n = len(args.get("models") or [])
    return (
        f"generate_image_compare: {n} 个 model 各跑 "
        f"{args.get('n_per_model', 1)} 张 — '{(args.get('prompt') or '')[:60]}...'"
    )


@approval_tool_with_audit(
    mcp,
    summary_fn=_img_compare_summary,
)
async def generate_image_compare(
    prompt: str,
    models: list[str],
    n_per_model: int = 1,
    aspect: str = "9:16",
) -> dict:
    """同 prompt 在 N 个 model 上各出 n_per_model 张图，方便横向选模型。

    require_approval=True（多调一次 hub 多花一次钱）。

    Args:
        prompt: 共用 prompt 文本
        models: 要对比的 model 列表（如 ['gpt-image-2', 'gemini-3.1-flash-image-preview']）
        n_per_model: 每个 model 跑几张（默认 1）
        aspect: 画幅（hub ImageGenerateRequest 用 size，传 aspect_ratio 也接受）

    Returns:
        {ok, result: {prompt, by_model: [{model, images:[url], error?}]}, trace}
    """
    prompt = (prompt or "").strip()
    if not prompt:
        return {"ok": False, "error": "missing_prompt", "hint": "prompt 不能为空"}
    if not models or not isinstance(models, list):
        return {"ok": False, "error": "missing_models",
                "hint": "models 必须是非空 list[str]"}
    if n_per_model < 1 or n_per_model > 4:
        return {"ok": False, "error": "invalid_n_per_model",
                "hint": "n_per_model ∈ [1, 4]"}

    client = AIHubClient()
    by_model: list[dict[str, Any]] = []
    for model in models:
        try:
            resp = await client.generate_image(
                prompt=prompt,
                model=model,
                n=n_per_model,
                aspect=aspect,
            )
            urls = [
                img.get("url") for img in (resp.get("images") or [])
                if img.get("url")
            ]
            by_model.append({"model": model, "images": urls})
        except Exception as exc:
            logger.exception("generate_image_compare model=%s 失败", model)
            by_model.append({
                "model": model,
                "images": [],
                "error": f"{type(exc).__name__}: {exc}",
            })

    succeeded = sum(1 for m in by_model if not m.get("error"))
    trace = build_trace(
        provider="multi",
        model="|".join(models),
        prompt=prompt[:300],
        params={"n_per_model": n_per_model, "aspect": aspect, "models_count": len(models)},
        cost_estimate=f"~{len(models) * n_per_model} image cost units",
    )
    return {
        "ok": True,
        "result": {
            "prompt": prompt,
            "by_model": by_model,
            "succeeded": succeeded,
            "total": len(models),
            "next_step_hint": (
                f"{succeeded}/{len(models)} model 出图成功。挑一张 url 给老板审；"
                "选定后用单 model generate_image 重跑确定版。"
            ),
        },
        "trace": trace,
    }


# ─── send_wecom_message (T) ────────────────────────────────────────────────


def _wecom_summary(args: dict) -> str:
    ch = args.get("channel") or "<noch>"
    return f"send_wecom_message: channel={ch} content='{(args.get('content') or '')[:60]}...'"


def _load_wecom_webhooks() -> dict[str, str]:
    """读 .env 的 WECOM_WEBHOOKS='alert=<url>,daily=<url>'。

    格式：channel=url,channel=url（逗号分隔，等号绑定）。空/未配置返 {}。
    """
    raw = os.environ.get("WECOM_WEBHOOKS", "").strip()
    if not raw:
        return {}
    out: dict[str, str] = {}
    for kv in raw.split(","):
        if "=" not in kv:
            continue
        k, v = kv.split("=", 1)
        k, v = k.strip(), v.strip()
        if k and v:
            out[k] = v
    return out


@approval_tool_with_audit(
    mcp,
    summary_fn=_wecom_summary,
)
async def send_wecom_message(
    channel: str,
    content: str,
) -> dict:
    """通过企微 webhook 发文本消息。

    require_approval=True（"发动作到平台前"4 类签字之一）。

    需在 .env 配 `WECOM_WEBHOOKS='alert=https://qyapi.weixin.qq.com/...,daily=...'`。
    channel 必须在配置中存在。

    Args:
        channel: webhook 名（如 alert / daily），由 WECOM_WEBHOOKS 映射
        content: 文本内容（markdown 也行，企微会按 text 渲染）

    Returns:
        {ok, result: {channel, errcode, errmsg, msgid?}}
    """
    channel = (channel or "").strip()
    content = (content or "").strip()
    if not channel:
        return {"ok": False, "error": "missing_channel", "hint": "channel 不能为空"}
    if not content:
        return {"ok": False, "error": "missing_content", "hint": "content 不能为空"}

    webhooks = _load_wecom_webhooks()
    if not webhooks:
        return {
            "ok": False,
            "error": "no_webhooks_configured",
            "hint": (
                ".env 未配 WECOM_WEBHOOKS。格式："
                "WECOM_WEBHOOKS='alert=https://qyapi.weixin.qq.com/...,daily=...'"
            ),
        }
    url = webhooks.get(channel)
    if not url:
        return {
            "ok": False,
            "error": "channel_not_found",
            "hint": f"channel={channel} 不在 WECOM_WEBHOOKS 配置；"
                    f"可用：{sorted(webhooks.keys())}",
        }

    payload = {"msgtype": "text", "text": {"content": content}}
    try:
        async with httpx.AsyncClient(timeout=15.0) as cli:
            resp = await cli.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        logger.exception("send_wecom_message webhook 调用失败")
        return {
            "ok": False,
            "error": "webhook_failed",
            "hint": f"调企微 webhook 失败: {type(exc).__name__}: {exc}",
        }

    errcode = data.get("errcode", -1)
    errmsg = data.get("errmsg", "")
    if errcode != 0:
        return {
            "ok": False,
            "error": "wecom_error",
            "hint": f"企微返非 0：errcode={errcode} errmsg={errmsg}",
            "result": data,
        }
    return {
        "ok": True,
        "result": {
            "channel": channel,
            "errcode": errcode,
            "errmsg": errmsg,
            "msgid": data.get("msgid"),
            "next_step_hint": "已发；老板看企微 group 是否真到。",
        },
    }


# ─── dy_publish_creative (T 高危, MVP stub) ────────────────────────────────


def _dypub_summary(args: dict) -> str:
    return (f"dy_publish_creative: sku_id={args.get('sku_id')} "
            f"draft_id={args.get('draft_id')} (MVP stub 不真发)")


@approval_tool_with_audit(
    mcp,
    summary_fn=_dypub_summary,
)
async def dy_publish_creative(
    sku_id: str,
    draft_id: str,
    dry_run: bool = True,
) -> dict:
    """抖店发布商品/创意（MVP stub，不真调抖店 OpenAPI）。

    require_approval=True（高危 4 类签字之一）。

    本 MVP 仅返 would_publish=True 的占位响应；批后老板手动用抖店 SDK 真发布。
    后续接入抖店 OpenAPI 直发由 W5+ 切片完成。

    Args:
        sku_id: omni mvp_sku.id
        draft_id: 创意/草稿 id（抖店侧或 omni briefs.id）
        dry_run: True 时只返 stub（默认 True；MVP 阶段不允许 False）

    Returns:
        {ok, result: {sku_id, draft_id, would_publish, mode}}
    """
    sku_id = (sku_id or "").strip()
    draft_id = (draft_id or "").strip()
    if not sku_id:
        return {"ok": False, "error": "missing_sku_id", "hint": "sku_id 不能为空"}
    if not draft_id:
        return {"ok": False, "error": "missing_draft_id", "hint": "draft_id 不能为空"}

    if not dry_run:
        return {
            "ok": False,
            "error": "real_publish_not_implemented",
            "hint": "抖店 OpenAPI 接入在后续切片；当前仅支持 dry_run=True。",
        }

    return {
        "ok": True,
        "result": {
            "sku_id": sku_id,
            "draft_id": draft_id,
            "mode": "dry_run",
            "would_publish": True,
            "next_step_hint": (
                "MVP stub。Gate 批通后，老板用抖店后台或自有 SDK 真发布；"
                "后续切片接入 OpenAPI 直发后本 tool 真生效。"
            ),
        },
    }
