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
    matrix_run_id: str | None = None


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
            matrix_run_id=payload.matrix_run_id,
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


# ════════════════════════════════════════════════════════════════
# W4-B 切片 14.3 phase B：sku-pipeline step 4 圈包 SOP
# ════════════════════════════════════════════════════════════════


class GenerateKeywordPackRequest(BaseModel):
    seed_keywords: str
    target_count: int = 500
    sku_id: str | None = None
    audience_record_id: str | None = None
    audience_pack_id: str | None = None
    extra_context: str | None = None


@router.post("/exec/generate_keyword_pack")
async def exec_generate_keyword_pack(
    payload: GenerateKeywordPackRequest,
) -> Any:
    from app.mcp.tools.media import generate_keyword_pack
    try:
        return await generate_keyword_pack(
            seed_keywords=payload.seed_keywords,
            target_count=payload.target_count,
            sku_id=payload.sku_id,
            audience_record_id=payload.audience_record_id,
            audience_pack_id=payload.audience_pack_id,
            extra_context=payload.extra_context,
        )
    except Exception as exc:
        logger.exception("generate_keyword_pack REST 异常")
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": f"{type(exc).__name__}: {exc}"},
        )


class GenerateAudiencePackRequest(BaseModel):
    audience_record_id: str
    extra_context: str | None = None


@router.post("/exec/generate_audience_pack")
async def exec_generate_audience_pack(
    payload: GenerateAudiencePackRequest,
) -> Any:
    from app.mcp.tools.media import generate_audience_pack

    try:
        return await generate_audience_pack(
            audience_record_id=payload.audience_record_id,
            extra_context=payload.extra_context,
        )
    except Exception as exc:
        logger.exception("generate_audience_pack REST 异常")
        return JSONResponse(
            status_code=500,
            content={
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "hint": "看 KE 日志（docker logs omni-knowledge-engine | tail）",
            },
        )


# ════════════════════════════════════════════════════════════════
# W4-B 切片 14.4 phase C：generate_creative_pack 6 类素材
# ════════════════════════════════════════════════════════════════


class GenerateCreativePackRequest(BaseModel):
    kind: str
    sku_id: str | None = None
    audience_record_id: str | None = None
    audience_pack_id: str | None = None
    extra_context: str | None = None


@router.post("/exec/generate_creative_pack")
async def exec_generate_creative_pack(
    payload: GenerateCreativePackRequest,
) -> Any:
    from app.mcp.tools.media import generate_creative_pack
    try:
        return await generate_creative_pack(
            kind=payload.kind,
            sku_id=payload.sku_id,
            audience_record_id=payload.audience_record_id,
            audience_pack_id=payload.audience_pack_id,
            extra_context=payload.extra_context,
        )
    except Exception as exc:
        logger.exception("generate_creative_pack REST 异常")
        return JSONResponse(
            status_code=500,
            content={
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "hint": "看 KE 日志（docker logs omni-knowledge-engine | tail）",
            },
        )


# ════════════════════════════════════════════════════════════════
# W4-B 切片 14.3 phase A：pipeline lineage 查询/采纳 endpoint
# ════════════════════════════════════════════════════════════════


class PipelineListMatrixRunsRequest(BaseModel):
    sku_id: str | None = None
    limit: int = 30


@router.post("/exec/pipeline_list_matrix_runs")
async def exec_pipeline_list_matrix_runs(
    payload: PipelineListMatrixRunsRequest,
) -> Any:
    from app.mcp.tools.pipeline import pipeline_list_matrix_runs
    try:
        return await pipeline_list_matrix_runs(sku_id=payload.sku_id, limit=payload.limit)
    except Exception as exc:
        logger.exception("pipeline_list_matrix_runs REST 异常")
        return JSONResponse(status_code=500, content={"ok": False, "error": f"{type(exc).__name__}: {exc}"})


class PipelineGetMatrixRunRequest(BaseModel):
    matrix_run_id: str


@router.post("/exec/pipeline_get_matrix_run")
async def exec_pipeline_get_matrix_run(
    payload: PipelineGetMatrixRunRequest,
) -> Any:
    from app.mcp.tools.pipeline import pipeline_get_matrix_run
    try:
        return await pipeline_get_matrix_run(matrix_run_id=payload.matrix_run_id)
    except Exception as exc:
        logger.exception("pipeline_get_matrix_run REST 异常")
        return JSONResponse(status_code=500, content={"ok": False, "error": f"{type(exc).__name__}: {exc}"})


class PipelineListAudienceRunsRequest(BaseModel):
    sku_id: str | None = None
    limit: int = 30


@router.post("/exec/pipeline_list_audience_runs")
async def exec_pipeline_list_audience_runs(
    payload: PipelineListAudienceRunsRequest,
) -> Any:
    from app.mcp.tools.pipeline import pipeline_list_audience_runs
    try:
        return await pipeline_list_audience_runs(sku_id=payload.sku_id, limit=payload.limit)
    except Exception as exc:
        logger.exception("pipeline_list_audience_runs REST 异常")
        return JSONResponse(status_code=500, content={"ok": False, "error": f"{type(exc).__name__}: {exc}"})


class PipelineGetAudienceRunRequest(BaseModel):
    audience_run_id: str


@router.post("/exec/pipeline_get_audience_run")
async def exec_pipeline_get_audience_run(
    payload: PipelineGetAudienceRunRequest,
) -> Any:
    from app.mcp.tools.pipeline import pipeline_get_audience_run
    try:
        return await pipeline_get_audience_run(audience_run_id=payload.audience_run_id)
    except Exception as exc:
        logger.exception("pipeline_get_audience_run REST 异常")
        return JSONResponse(status_code=500, content={"ok": False, "error": f"{type(exc).__name__}: {exc}"})


class PipelineListAudienceRecordsRequest(BaseModel):
    audience_run_id: str | None = None
    sku_id: str | None = None
    selected_only: bool = False
    limit: int = 50


@router.post("/exec/pipeline_list_audience_records")
async def exec_pipeline_list_audience_records(
    payload: PipelineListAudienceRecordsRequest,
) -> Any:
    from app.mcp.tools.pipeline import pipeline_list_audience_records
    try:
        return await pipeline_list_audience_records(
            audience_run_id=payload.audience_run_id,
            sku_id=payload.sku_id,
            selected_only=payload.selected_only,
            limit=payload.limit,
        )
    except Exception as exc:
        logger.exception("pipeline_list_audience_records REST 异常")
        return JSONResponse(status_code=500, content={"ok": False, "error": f"{type(exc).__name__}: {exc}"})


class PipelineGetAudienceRecordRequest(BaseModel):
    record_id: str


@router.post("/exec/pipeline_get_audience_record")
async def exec_pipeline_get_audience_record(
    payload: PipelineGetAudienceRecordRequest,
) -> Any:
    from app.mcp.tools.pipeline import pipeline_get_audience_record
    try:
        return await pipeline_get_audience_record(record_id=payload.record_id)
    except Exception as exc:
        logger.exception("pipeline_get_audience_record REST 异常")
        return JSONResponse(status_code=500, content={"ok": False, "error": f"{type(exc).__name__}: {exc}"})


class PipelineAdoptRequest(BaseModel):
    table: str  # matrix_runs / audience_runs / audience_records / audience_packs / scripts
    run_id: str
    set_selected: bool = False


@router.post("/exec/pipeline_adopt")
async def exec_pipeline_adopt(
    payload: PipelineAdoptRequest,
) -> Any:
    from app.mcp.tools.pipeline import pipeline_adopt
    try:
        return await pipeline_adopt(
            table=payload.table,
            run_id=payload.run_id,
            set_selected=payload.set_selected,
        )
    except Exception as exc:
        logger.exception("pipeline_adopt REST 异常")
        return JSONResponse(status_code=500, content={"ok": False, "error": f"{type(exc).__name__}: {exc}"})
