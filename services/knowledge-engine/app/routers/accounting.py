"""算账 REST API（migration 015 配套）.

POST   /api/v1/accounting/cost-items          创建
GET    /api/v1/accounting/cost-items          列表（支持 sku_id/category/active_only 过滤）
GET    /api/v1/accounting/cost-items/{id}     单项
PATCH  /api/v1/accounting/cost-items/{id}     部分更新
DELETE /api/v1/accounting/cost-items/{id}     删除

POST   /api/v1/accounting/margin              计算净利率
POST   /api/v1/accounting/query               自然语言问询（LLM 解析 → 执行）
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile, status

from app.schemas import (
    CostItemBulkCreateRequest,
    CostItemCreateRequest,
    CostItemUpdateRequest,
    CostNLQueryRequest,
    MarginRequest,
)
from app.services.accounting_tool import (
    answer_cost_question,
    bulk_create_cost_items,
    compute_margin,
    create_cost_item,
    delete_cost_item,
    get_cost_item,
    query_costs,
    update_cost_item,
)
from app.services.cost_extractor import extract_cost_items
from app.services.document_parser import SUPPORTED_EXTENSIONS, extract_text

router = APIRouter(prefix="/api/v1/accounting", tags=["accounting"])


# ═══ Cost Items CRUD ═══


@router.post("/cost-items", status_code=status.HTTP_201_CREATED)
async def create_item(payload: CostItemCreateRequest) -> dict:
    try:
        item = await create_cost_item(payload.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"code": 201, "message": "success", "data": item}


@router.get("/cost-items")
async def list_items(
    sku_id: str | None = None,
    category: str | None = None,
    item_name_search: str | None = None,
    active_only: bool = True,
    on_date: date | None = None,
    include_shared: bool = True,
    limit: int = Query(default=200, ge=1, le=1000),
) -> dict:
    try:
        items = await query_costs(
            sku_id=sku_id,
            category=category,
            item_name_search=item_name_search,
            active_only=active_only,
            on_date=on_date,
            include_shared=include_shared,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"code": 200, "message": "success", "data": items}


@router.get("/cost-items/{item_id}")
async def get_item(item_id: str) -> dict:
    item = await get_cost_item(item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="cost item not found")
    return {"code": 200, "message": "success", "data": item}


@router.patch("/cost-items/{item_id}")
async def patch_item(item_id: str, payload: CostItemUpdateRequest) -> dict:
    try:
        item = await update_cost_item(item_id, payload.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="cost item not found")
    return {"code": 200, "message": "success", "data": item}


@router.delete("/cost-items/{item_id}")
async def remove_item(item_id: str) -> dict:
    ok = await delete_cost_item(item_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="cost item not found")
    return {"code": 200, "message": "success", "data": {"deleted": True}}


# ═══ Compute / NL Query ═══


@router.post("/margin")
async def margin(payload: MarginRequest) -> dict:
    try:
        result = await compute_margin(
            sku_id=payload.sku_id,
            sale_price=payload.sale_price,
            quantity=payload.quantity,
            platform_fee_rate=payload.platform_fee_rate,
            include_shared_logistics=payload.include_shared_logistics,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"code": 200, "message": "success", "data": result}


@router.post("/cost-items/bulk", status_code=status.HTTP_201_CREATED)
async def bulk_create(payload: CostItemBulkCreateRequest) -> dict:
    """批量入库（前端预览编辑后调用）."""
    try:
        result = await bulk_create_cost_items(
            [it.model_dump(exclude_none=True) for it in payload.items],
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"code": 201, "message": "success", "data": result}


@router.post("/extract-from-file")
async def extract_from_file(
    file: UploadFile = File(...),
    sku_id: str | None = Form(default=None),
    model: str | None = Form(default=None),
) -> dict:
    """上传报价单 (PDF/DOCX/XLSX/CSV/...) → 文本抽取 + LLM 解析为成本项草稿。

    返回的 `items` 不入库，前端做预览/编辑后再调 /cost-items/bulk 入库。
    """
    filename = file.filename or "unknown.txt"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if f".{ext}" not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"不支持的文件类型: .{ext}。支持：{', '.join(sorted(SUPPORTED_EXTENSIONS))}",
        )
    content = await file.read()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="文件为空")

    text = extract_text(content, filename)
    if not text.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="文件无可解析文本")

    try:
        items = await extract_cost_items(text, model=model)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    # 若上传时指定 SKU，覆盖 LLM 提取的（除非 LLM 提取出更明确的 sku_id）
    if sku_id:
        for it in items:
            if not it.get("sku_id"):
                it["sku_id"] = sku_id

    return {
        "code": 200,
        "message": "success",
        "data": {
            "filename": filename,
            "text_length": len(text),
            "items": items,
            "items_count": len(items),
        },
    }


@router.post("/query")
async def nl_query(payload: CostNLQueryRequest) -> dict:
    """自然语言问询：LLM 解析 → 执行 cost 查询/算净利。"""
    try:
        result = await answer_cost_question(
            payload.query,
            ctx_sku_id=payload.sku_id,
            ctx_sale_price=payload.sale_price,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return {"code": 200, "message": "success", "data": result}
