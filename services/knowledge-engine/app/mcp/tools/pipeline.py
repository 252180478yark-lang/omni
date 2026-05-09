"""W4-B 切片 14.3 phase A：pipeline lineage 查询 / 采纳 tool。

5 个 tool：
- pipeline_list_matrix_runs：列某 sku 跑过的 step 2 卖点矩阵历史
- pipeline_get_matrix_run：拉单条 matrix_run 的 matrix_md + 入参备份
- pipeline_list_audience_records：列某 audience_run 拆出的所有人群（或 sku 维度过滤）
- pipeline_get_audience_record：拉单条人群记录（含 KB 原文 chunk + 匹配理由）
- pipeline_adopt：把某 run 从 draft 改 adopted（audience_records 可顺便选中挂下游）

Tool 都不走 Human Gate（纯查询 + 状态翻转，不烧钱不动 LLM）。
"""
from __future__ import annotations

from app.mcp.audit import tool_with_audit
from app.mcp.server import mcp
from app.services import pipeline_lineage


@tool_with_audit(mcp, require_approval=False)
async def pipeline_list_matrix_runs(sku_id: str | None = None, limit: int = 30) -> dict:
    """列 step 2 卖点矩阵的历史跑次。

    Args:
        sku_id: 过滤某个 SKU；None=全表
        limit: 取最近 N 条（默认 30）

    Returns:
        {"ok": True, "count": N, "runs": [{id, sku_id, version, status, model_provider, model, created_at, parent_run_id}, ...]}
    """
    runs = await pipeline_lineage.list_matrix_runs(sku_id=sku_id, limit=limit)
    return {"ok": True, "count": len(runs), "runs": runs}


@tool_with_audit(mcp, require_approval=False)
async def pipeline_get_matrix_run(matrix_run_id: str) -> dict:
    """拉单条 matrix_run 全字段（含 matrix_md + 入参备份）。

    Args:
        matrix_run_id: pipeline.matrix_runs.id (uuid 字符串)

    Returns:
        成功 {"ok": True, "run": {全字段}}
        失败 {"ok": False, "error": "not_found"}
    """
    run = await pipeline_lineage.get_matrix_run(matrix_run_id)
    if not run:
        return {"ok": False, "error": "not_found", "matrix_run_id": matrix_run_id}
    return {"ok": True, "run": run}


@tool_with_audit(mcp, require_approval=False)
async def pipeline_list_audience_runs(
    sku_id: str | None = None, limit: int = 30
) -> dict:
    """列 step 3 人群匹配的历史跑次（按 sku_id 过滤或全表）。

    Args:
        sku_id: 过滤某个 SKU；None=全表
        limit: 取最近 N 条（默认 30）

    Returns:
        {"ok": True, "count": N, "runs": [{id, matrix_run_id, sku_id, version,
            status, record_count, model_provider, model, created_at, parent_run_id}, ...]}
    """
    runs = await pipeline_lineage.list_audience_runs(sku_id=sku_id, limit=limit)
    return {"ok": True, "count": len(runs), "runs": runs}


@tool_with_audit(mcp, require_approval=False)
async def pipeline_get_audience_run(audience_run_id: str) -> dict:
    """拉单条 audience_run 全字段 + 关联 N 条 audience_records（按 ordinal）。

    Args:
        audience_run_id: pipeline.audience_runs.id (uuid 字符串)

    Returns:
        成功 {"ok": True, "run": {全字段}, "records": [{id, ordinal, name, ...}, ...]}
        失败 {"ok": False, "error": "not_found"}
    """
    bundle = await pipeline_lineage.get_audience_run(audience_run_id)
    if not bundle:
        return {"ok": False, "error": "not_found", "audience_run_id": audience_run_id}
    return {"ok": True, **bundle}


@tool_with_audit(mcp, require_approval=False)
async def pipeline_list_audience_records(
    audience_run_id: str | None = None,
    sku_id: str | None = None,
    selected_only: bool = False,
    limit: int = 50,
) -> dict:
    """列某 audience_run 拆出的所有人群记录（或 sku 维度过滤）。

    Args:
        audience_run_id: 拉这一次 step 3 跑出的所有人群（最常用）
        sku_id: 拉 sku 维度的所有人群（跨多次跑）
        selected_only: 只看老板已选（selected_for_pack=TRUE）的
        limit: 取最近 N 条（默认 50）

    Returns:
        {"ok": True, "count": N, "records": [{id, ordinal, name, kb_doc, layer_tags,
            match_reasons, status, selected_for_pack, ...}, ...]}
    """
    records = await pipeline_lineage.list_audience_records(
        audience_run_id=audience_run_id,
        sku_id=sku_id,
        selected_only=selected_only,
        limit=limit,
    )
    return {"ok": True, "count": len(records), "records": records}


@tool_with_audit(mcp, require_approval=False)
async def pipeline_get_audience_record(record_id: str) -> dict:
    """拉单条人群记录全字段（含 KB chunk 原文 + 匹配理由完整列表）。

    Args:
        record_id: pipeline.audience_records.id (uuid 字符串)

    Returns:
        成功 {"ok": True, "record": {全字段}}
        失败 {"ok": False, "error": "not_found"}
    """
    rec = await pipeline_lineage.get_audience_record(record_id)
    if not rec:
        return {"ok": False, "error": "not_found", "record_id": record_id}
    return {"ok": True, "record": rec}


@tool_with_audit(mcp, require_approval=False)
async def pipeline_adopt(
    table: str,
    run_id: str,
    set_selected: bool = False,
) -> dict:
    """把某 run 从 status='draft' 改 'adopted'。下游链路只跟 adopted 的走。

    Args:
        table: matrix_runs / audience_runs / audience_records / audience_packs / scripts 之一
        run_id: 对应表的 id (uuid)
        set_selected: 仅 audience_records 生效；同步把 selected_for_pack 改 TRUE
                      （= 老板"我选这个人群挂 step 4"的语义动作）

    Returns:
        {"ok": True, "id": ..., "status": "adopted", ...}
        失败 {"ok": False, "error": "not_found_or_archived" / "未知 table"}
    """
    return await pipeline_lineage.adopt_run(table, run_id, set_selected=set_selected)
