"""Volcengine Visual API 客户端 — 单图音频驱动 / 数字人视频生成。

Service: cv (图像生成大模型, service 86081)
Endpoint: visual.volcengineapi.com
Auth: Volcengine AK/SK (不同于 ARK Bearer Token)

已开通能力（req_key）:
  realman_avatar_picture_v2           — 形象创建：单张人脸图 → 标准化头像
  realman_avatar_imitator_v2v_gen_video — 视频生成：头像图 + 驱动视频 → 口型对齐视频
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

_REQ_AVATAR_PICTURE = "realman_avatar_picture_v2"
_REQ_PORTRAIT_VIDEO = "realman_avatar_imitator_v2v_gen_video"


def _get_service():
    """惰性初始化 VisualService（singleton），注入当前 AK/SK。"""
    from volcengine.visual.VisualService import VisualService
    svc = VisualService()
    ak = (settings.volcengine_access_key or "").strip()
    sk = (settings.volcengine_secret_key or "").strip()
    if ak:
        svc.set_ak(ak)
    if sk:
        svc.set_sk(sk)
    return svc


def _is_configured() -> bool:
    return bool((settings.volcengine_access_key or "").strip())


# ── 形象创建 ────────────────────────────────────────────────────────────────

async def create_avatar(image_url: str) -> dict:
    """realman_avatar_picture_v2：单张人脸图 → 标准化头像。

    Returns: {ok, avatar_image_url?, raw}
    """
    if not _is_configured():
        return {"ok": False, "error": "unconfigured", "hint": "需要在 .env.example 设置 VOLCENGINE_ACCESS_KEY / SECRET_KEY"}

    form = {"req_key": _REQ_AVATAR_PICTURE, "image_url": image_url}
    try:
        svc = _get_service()
        resp = await asyncio.to_thread(svc.cv_process, form)
        code = (resp or {}).get("code", -1)
        if code != 10000:
            return {"ok": False, "error": f"api_error_{code}", "raw": resp}
        data = (resp or {}).get("data") or {}
        # 返回的图片可能在 resp_data 或 output_image_url 里
        out_url = (
            data.get("output_image_url")
            or (data.get("resp_data") or {}).get("output_image_url")
            or ""
        )
        return {"ok": True, "avatar_image_url": out_url or image_url, "raw": resp}
    except Exception as exc:
        logger.error("realman create_avatar failed: %s", exc)
        return {"ok": False, "error": str(exc)}


# ── 视频生成（驱动视频模式）───────────────────────────────────────────────────

async def generate_portrait_video(
    image_url: str,
    driving_video_url: str,
    *,
    poll_interval: float = 5.0,
    timeout_s: float = 300.0,
) -> dict:
    """realman_avatar_imitator_v2v_gen_video：头像图 + 驱动视频 → 口型对齐视频。

    异步提交 → 轮询 → 返回视频 URL。

    Args:
        image_url: 真实人物头像图（被驱动的目标脸）
        driving_video_url: 驱动视频 URL（动作/口型来源）
        poll_interval: 轮询间隔（秒）
        timeout_s: 最大等待秒数（默认 5 分钟）

    Returns:
        {ok, video_url, task_id, raw}
    """
    if not _is_configured():
        return {"ok": False, "error": "unconfigured", "hint": "需要在 .env.example 设置 VOLCENGINE_ACCESS_KEY / SECRET_KEY"}

    form: dict[str, Any] = {
        "req_key": _REQ_PORTRAIT_VIDEO,
        "image_url": image_url,
        "driving_video_info": {
            "store_type": 0,   # 0 = 外链 URL
            "video_url": driving_video_url,
        },
    }

    try:
        svc = _get_service()

        # 1. 提交任务
        submit_resp = await asyncio.to_thread(svc.cv_sync2async_submit_task, form)
        code = (submit_resp or {}).get("code", -1)
        if code != 10000:
            return {"ok": False, "error": f"submit_error_{code}", "raw": submit_resp,
                    "hint": _classify_error(submit_resp)}
        task_id = ((submit_resp or {}).get("data") or {}).get("task_id", "")
        if not task_id:
            return {"ok": False, "error": "no_task_id", "raw": submit_resp}

        logger.info("realman portrait video task_id=%s", task_id)

        # 2. 轮询结果
        elapsed = 0.0
        while elapsed < timeout_s:
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

            result_resp = await asyncio.to_thread(
                svc.cv_sync2async_get_result, {"task_id": task_id}
            )
            rcode = (result_resp or {}).get("code", -1)
            if rcode != 10000:
                logger.warning("realman poll error code=%s resp=%s", rcode, result_resp)
                continue

            rdata = (result_resp or {}).get("data") or {}
            status = (rdata.get("status") or "").lower()

            if status in {"done", "success", "succeeded", "finished"}:
                # 视频 URL 可能在多个字段里
                resp_data = rdata.get("resp_data") or {}
                video_url = (
                    resp_data.get("video_url")
                    or resp_data.get("output_video_url")
                    or rdata.get("video_url")
                    or ""
                )
                return {"ok": True, "video_url": video_url, "task_id": task_id, "raw": result_resp}

            if status in {"failed", "error"}:
                return {"ok": False, "error": "task_failed", "task_id": task_id, "raw": result_resp}

            # status == "processing" / "pending" → 继续等
            logger.debug("realman task %s status=%s elapsed=%.0fs", task_id, status, elapsed)

        return {"ok": False, "error": "timeout", "task_id": task_id,
                "hint": f"超过 {timeout_s:.0f}s 未完成，稍后用 task_id 手动查"}

    except Exception as exc:
        logger.error("realman generate_portrait_video failed: %s", exc)
        return {"ok": False, "error": str(exc)}


def _classify_error(resp: dict) -> str:
    code = (resp or {}).get("code", -1)
    msg = str((resp or {}).get("message", ""))
    if "auth" in msg.lower() or "access" in msg.lower() or code in (10001, 10002, 10003):
        return "AK/SK 认证失败 — 检查 VOLCENGINE_ACCESS_KEY / SECRET_KEY 是否正确"
    if "quota" in msg.lower() or code == 10006:
        return "配额不足 — 检查 console.volcengine.com 计费余额"
    if "not support" in msg.lower() or "not open" in msg.lower():
        return "功能未开通 — 确认在控制台已激活 单图音频驱动 / 数字人视频生成"
    return f"API 错误（code={code} msg={msg}）"
