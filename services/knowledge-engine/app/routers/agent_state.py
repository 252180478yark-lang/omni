"""周期报 REST router（蓝图 §6.1 "自动周期报推到 UI/老板眼前，不只写 markdown 文件让老板自己找"）。

cron（weekly_self_review / daily_pulse / feedback_digest / dynamic_block_refresh）把报告
写进 AGENT_STATE_DIR 的 markdown 文件。现状老板得自己去翻文件——本 endpoint 把它们读出来
给前端"周期报"看板渲染。纯读、无副作用。
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/agent-state", tags=["agent-state"])

# 与 cron.py AGENT_STATE_DIR 一致（cron 写、这里读）。
_AGENT_STATE_DIR = Path("/app/agent_state")
_MAX_BYTES = 64 * 1024  # 单份报告读取上限，防超大文件拖垮响应

# 报告清单：文件名 → 展示标题 + 周期说明
_REPORTS = [
    ("daily_pulse.md", "每日店铺脉搏", "daily · fetch_compass + yuntu"),
    ("weekly_review.md", "每周自检", "weekly · agent_self_review"),
    ("feedback_digest.md", "反馈消化草稿", "weekly · 负反馈+投后聚类（只聚类不自动改）"),
    ("dynamic_block.md", "业务底色刷新", "weekly · refresh_project_context"),
]


@router.get("/reports")
async def list_reports() -> dict:
    """列出 cron 生成的周期报（含内容）。文件不存在的跳过；读不出的标错不阻断其他。

    返 {ok, reports: [{name, title, period, content, bytes, mtime}], dir}。
    """
    out = []
    for fname, title, period in _REPORTS:
        fp = _AGENT_STATE_DIR / fname
        if not fp.exists():
            continue
        try:
            stat = fp.stat()
            raw = fp.read_text(encoding="utf-8", errors="ignore")
            truncated = len(raw.encode("utf-8")) > _MAX_BYTES
            content = raw[:_MAX_BYTES] + ("\n\n…（已截断）" if truncated else "")
            out.append({
                "name": fname,
                "title": title,
                "period": period,
                "content": content,
                "bytes": stat.st_size,
                "mtime": stat.st_mtime,
            })
        except Exception as exc:  # pragma: no cover
            logger.warning("读取周期报 %s 失败：%s", fname, exc)
            out.append({"name": fname, "title": title, "period": period,
                        "content": f"（读取失败：{exc}）", "error": True})
    return {"ok": True, "reports": out, "dir": str(_AGENT_STATE_DIR)}
