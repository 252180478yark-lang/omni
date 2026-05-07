"""REST router for omni MCP tool exec (W4-B 切片 14).

让前端能直接触发 omni MCP tool（绕过 Claude Code）做"prompt + 数据"的快速测试。

当前暴露：
- POST /api/v1/mcp/exec/generate_selling_points_matrix  — sku-pipeline step 2 卖点矩阵
- POST /api/v1/mcp/exec/generate_audience_match         — sku-pipeline step 3 人群匹配

后续切片加更多（audience_sop_pack / video_script / storyboard_descriptions 等），
也可改成通用 dispatch endpoint。

设计取舍：
- 直接 import + 调用 tool 函数（包过 tool_with_audit 装饰器，会自动走 audit log
  + Gate 如果 require_approval=True）
- 不另起会话，直接同步返回 tool result
- 错误格式：tool 返 ok:false 时透传；HTTP 异常时返 5xx
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/mcp", tags=["mcp-exec"])


class GenerateSellingPointsMatrixRequest(BaseModel):
    sku_id: str
    user_initial_points: str = ""
    user_reviews: str = ""
    kb_context: str | None = None
    extra_context: str | None = None


@router.post("/exec/generate_selling_points_matrix")
async def exec_generate_selling_points_matrix(
    payload: GenerateSellingPointsMatrixRequest,
) -> Any:
    from app.mcp.tools.media import generate_selling_points_matrix

    try:
        result = await generate_selling_points_matrix(
            sku_id=payload.sku_id,
            user_initial_points=payload.user_initial_points,
            user_reviews=payload.user_reviews,
            kb_context=payload.kb_context,
            extra_context=payload.extra_context,
        )
        return result
    except Exception as exc:
        logger.exception("generate_selling_points_matrix REST 异常")
        return JSONResponse(
            status_code=500,
            content={
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "hint": "看 KE 日志定位（docker logs omni-knowledge-engine | tail）",
            },
        )


class GenerateAudienceMatchRequest(BaseModel):
    sku_id: str
    matrix_md: str
    extra_context: str | None = None
    kb_recall_override: str | None = None


@router.post("/exec/generate_audience_match")
async def exec_generate_audience_match(
    payload: GenerateAudienceMatchRequest,
) -> Any:
    from app.mcp.tools.media import generate_audience_match

    try:
        result = await generate_audience_match(
            sku_id=payload.sku_id,
            matrix_md=payload.matrix_md,
            extra_context=payload.extra_context,
            kb_recall_override=payload.kb_recall_override,
        )
        return result
    except Exception as exc:
        logger.exception("generate_audience_match REST 异常")
        return JSONResponse(
            status_code=500,
            content={
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "hint": "看 KE 日志定位（docker logs omni-knowledge-engine | tail）",
            },
        )
