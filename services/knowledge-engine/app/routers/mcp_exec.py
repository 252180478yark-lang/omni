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


class PipelineGetSkuLineageRequest(BaseModel):
    sku_id: str
    limit_per_table: int = 100
    include_archived: bool = False
    hide_draft_videos: bool = True


@router.post("/exec/pipeline_get_sku_lineage")
async def exec_pipeline_get_sku_lineage(
    payload: PipelineGetSkuLineageRequest,
) -> Any:
    """SKU 全血缘嵌套树：matrix → audience_run → record → pack → script → asset。

    给前端血缘图组件用，含 status='draft' 的（前端按状态着色）；
    默认隐藏 status='archived'，include_archived=True 时全返；
    默认隐藏 status='draft' 的 video asset（草稿视频段不挤血缘）。
    """
    from app.services.pipeline_lineage import get_sku_lineage
    try:
        return await get_sku_lineage(
            sku_id=payload.sku_id,
            limit_per_table=payload.limit_per_table,
            include_archived=payload.include_archived,
            hide_draft_videos=payload.hide_draft_videos,
        )
    except Exception as exc:
        logger.exception("pipeline_get_sku_lineage REST 异常")
        return JSONResponse(status_code=500, content={"ok": False, "error": f"{type(exc).__name__}: {exc}"})


class PipelineArchiveNodeRequest(BaseModel):
    table: str  # matrix_runs / audience_runs / audience_records / audience_packs / scripts / assets / keyword_packs
    run_id: str


@router.post("/exec/pipeline_archive_node")
async def exec_pipeline_archive_node(
    payload: PipelineArchiveNodeRequest,
) -> Any:
    """归档血缘节点：status='archived'。从血缘图默认视图隐藏（可恢复，data 保留）。

    适用场景：脚本跑出多版分镜图都采纳后想丢一批 / 不要某一版圈包 / 早期人群匹配
    误圈想清理。data 不删，只是 status 变 archived 让 UI 不显示。
    """
    from app.services.pipeline_lineage import archive_node
    try:
        return await archive_node(table=payload.table, run_id=payload.run_id)
    except Exception as exc:
        logger.exception("pipeline_archive_node REST 异常")
        return JSONResponse(status_code=500, content={"ok": False, "error": f"{type(exc).__name__}: {exc}"})


# ───────────────────────────────────────────────────────────────
# W4-B 切片 14.4 phase D：分镜图生成 + 资产管理
# ───────────────────────────────────────────────────────────────

class GenerateCharacterSheetsRequest(BaseModel):
    script_id: str
    role_ids: list[str] | None = None
    aspect_ratio: str = "1:1"


@router.post("/exec/generate_character_sheets")
async def exec_generate_character_sheets(
    payload: GenerateCharacterSheetsRequest,
) -> Any:
    """step 6.5：从 script.character_sheets 出每个角色的白底正面像（chatgpt-image-2）。"""
    from app.mcp.tools.media import generate_character_sheets
    try:
        return await generate_character_sheets(
            script_id=payload.script_id,
            role_ids=payload.role_ids,
            aspect_ratio=payload.aspect_ratio,
        )
    except Exception as exc:
        logger.exception("generate_character_sheets REST 异常")
        return JSONResponse(status_code=500, content={"ok": False, "error": f"{type(exc).__name__}: {exc}"})


class GenerateStoryboardImagesRequest(BaseModel):
    script_id: str
    scene_nums: list[int] | None = None
    face_refs: list[str] | None = None
    product_refs: list[str] | None = None
    style_refs: list[str] | None = None
    aspect_ratio: str = "9:16"
    extra_prompt_suffix: str | None = None
    deidentify_faces: bool = False


@router.post("/exec/generate_storyboard_images")
async def exec_generate_storyboard_images(
    payload: GenerateStoryboardImagesRequest,
) -> Any:
    """从 script.scenes 拆分镜，并发出图，落 pipeline.assets。"""
    from app.mcp.tools.media import generate_storyboard_images
    try:
        return await generate_storyboard_images(
            script_id=payload.script_id,
            scene_nums=payload.scene_nums,
            face_refs=payload.face_refs,
            product_refs=payload.product_refs,
            style_refs=payload.style_refs,
            aspect_ratio=payload.aspect_ratio,
            extra_prompt_suffix=payload.extra_prompt_suffix,
            deidentify_faces=payload.deidentify_faces,
        )
    except Exception as exc:
        logger.exception("generate_storyboard_images REST 异常")
        return JSONResponse(status_code=500, content={"ok": False, "error": f"{type(exc).__name__}: {exc}"})


class GenerateVideoSegmentsRequest(BaseModel):
    script_id: str
    scene_nums: list[int] | None = None
    face_refs: list[str] | None = None
    product_refs: list[str] | None = None
    aspect_ratio: str = "9:16"
    duration_s: int = 8
    use_last_frame: bool = False
    extra_prompt_suffix: str | None = None
    dry_run: bool = False
    force_t2v: bool = False
    character_anchor: str | None = None
    model_override: str | None = None
    skip_first_frame_scene_nums: list[int] | None = None


@router.post("/exec/generate_video_segments")
async def exec_generate_video_segments(
    payload: GenerateVideoSegmentsRequest,
) -> Any:
    """W4-B 14.4 phase D step 7：拉 script.scenes，用 step 6 出的分镜图当 first_frame
    + character_sheet 锁脸，并发调 seedance-2-0 出每段视频，落 pipeline.assets(asset_type='video')。

    dry_run=True 时只拼 prompt 不调 seedance（调 prompt 调试用，零费用）。
    """
    from app.mcp.tools.media import generate_video_segments
    try:
        return await generate_video_segments(
            script_id=payload.script_id,
            scene_nums=payload.scene_nums,
            face_refs=payload.face_refs,
            product_refs=payload.product_refs,
            aspect_ratio=payload.aspect_ratio,
            duration_s=payload.duration_s,
            use_last_frame=payload.use_last_frame,
            extra_prompt_suffix=payload.extra_prompt_suffix,
            dry_run=payload.dry_run,
            force_t2v=payload.force_t2v,
            character_anchor=payload.character_anchor,
            model_override=payload.model_override,
            skip_first_frame_scene_nums=payload.skip_first_frame_scene_nums,
        )
    except Exception as exc:
        logger.exception("generate_video_segments REST 异常")
        return JSONResponse(status_code=500, content={"ok": False, "error": f"{type(exc).__name__}: {exc}"})


@router.post("/exec/pipeline_backfill_scenes")
async def exec_pipeline_backfill_scenes() -> Any:
    """一次性回填：扫所有 scenes=[] 的 scripts 按 kind 重解析填回。"""
    from app.services.pipeline_lineage import backfill_scenes_for_existing_scripts
    try:
        return await backfill_scenes_for_existing_scripts()
    except Exception as exc:
        logger.exception("pipeline_backfill_scenes REST 异常")
        return JSONResponse(status_code=500, content={"ok": False, "error": f"{type(exc).__name__}: {exc}"})


class PipelineListAssetsRequest(BaseModel):
    sku_id: str | None = None
    script_id: str | None = None
    asset_type: str | None = None
    limit: int = 50


@router.post("/exec/pipeline_list_assets")
async def exec_pipeline_list_assets(
    payload: PipelineListAssetsRequest,
) -> Any:
    """列 pipeline.assets，可按 sku/script/asset_type 过滤。"""
    from app.services.pipeline_lineage import list_assets
    try:
        rows = await list_assets(
            sku_id=payload.sku_id,
            script_id=payload.script_id,
            asset_type=payload.asset_type,
            limit=payload.limit,
        )
        return {"ok": True, "assets": rows, "count": len(rows)}
    except Exception as exc:
        logger.exception("pipeline_list_assets REST 异常")
        return JSONResponse(status_code=500, content={"ok": False, "error": f"{type(exc).__name__}: {exc}"})


class PipelineListCreativePacksRequest(BaseModel):
    sku_id: str | None = None
    kind: str | None = None
    audience_record_id: str | None = None
    limit: int = 30


@router.post("/exec/pipeline_list_creative_packs")
async def exec_pipeline_list_creative_packs(
    payload: PipelineListCreativePacksRequest,
) -> Any:
    """列 pipeline.scripts（按 sku/kind/record 过滤）— step 6 选 script 用。"""
    from app.services.pipeline_lineage import list_creative_packs
    try:
        rows = await list_creative_packs(
            sku_id=payload.sku_id,
            kind=payload.kind,
            audience_record_id=payload.audience_record_id,
            limit=payload.limit,
        )
        # 转 created_at 为 isoformat
        for r in rows:
            if r.get("created_at"):
                r["created_at"] = r["created_at"].isoformat()
        return {"ok": True, "scripts": rows, "count": len(rows)}
    except Exception as exc:
        logger.exception("pipeline_list_creative_packs REST 异常")
        return JSONResponse(status_code=500, content={"ok": False, "error": f"{type(exc).__name__}: {exc}"})


class PipelineGetAudiencePackRequest(BaseModel):
    pack_id: str


@router.post("/exec/pipeline_get_audience_pack")
async def exec_pipeline_get_audience_pack(
    payload: PipelineGetAudiencePackRequest,
) -> Any:
    """单条圈包全字段（含 pack_md / dmp_tags / budget_suggestion）— step 5 pack 模式选完后预览用。"""
    from app.services.pipeline_lineage import get_audience_pack
    try:
        d = await get_audience_pack(payload.pack_id)
        if not d:
            return {"ok": False, "error": "not_found", "pack_id": payload.pack_id}
        if d.get("created_at"):
            d["created_at"] = d["created_at"].isoformat()
        if d.get("updated_at"):
            d["updated_at"] = d["updated_at"].isoformat()
        return {"ok": True, "pack": d}
    except Exception as exc:
        logger.exception("pipeline_get_audience_pack REST 异常")
        return JSONResponse(status_code=500, content={"ok": False, "error": f"{type(exc).__name__}: {exc}"})


class PipelineGetCreativePackRequest(BaseModel):
    script_id: str


@router.post("/exec/pipeline_get_creative_pack")
async def exec_pipeline_get_creative_pack(
    payload: PipelineGetCreativePackRequest,
) -> Any:
    """单条脚本全字段（含 scenes/hooks JSONB）— step 6 选 script 后展示分镜清单用。"""
    from app.services.pipeline_lineage import get_creative_pack
    try:
        d = await get_creative_pack(payload.script_id)
        if not d:
            return {"ok": False, "error": "not_found", "script_id": payload.script_id}
        if d.get("created_at"):
            d["created_at"] = d["created_at"].isoformat()
        if d.get("updated_at"):
            d["updated_at"] = d["updated_at"].isoformat()
        return {"ok": True, "script": d}
    except Exception as exc:
        logger.exception("pipeline_get_creative_pack REST 异常")
        return JSONResponse(status_code=500, content={"ok": False, "error": f"{type(exc).__name__}: {exc}"})


class GenerateVideoAnchorRequest(BaseModel):
    script_id: str


@router.post("/exec/generate_video_anchor")
async def exec_generate_video_anchor(
    payload: GenerateVideoAnchorRequest,
) -> Any:
    """W4-B 14.4 phase D step 7（t2v 模式）：从 script 拉人群/卖点/场景，LLM 生成
    Seedance t2v 三行关键词锚点（[人物][场景][风格]）。
    """
    from app.mcp.tools.media import generate_video_anchor
    try:
        return await generate_video_anchor(script_id=payload.script_id)
    except Exception as exc:
        logger.exception("generate_video_anchor REST 异常")
        return JSONResponse(status_code=500, content={"ok": False, "error": f"{type(exc).__name__}: {exc}"})
