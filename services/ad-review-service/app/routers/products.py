from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException

from app.database import get_pool
from app.schemas import ProductCreate, ProductUpdate

router = APIRouter(prefix="/api/v1/ad-review/products", tags=["ad-review-products"])


@router.get("")
async def list_products():
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, name, sku, price, margin_rate, category, description, created_at FROM ad_review.products ORDER BY name ASC"
        )
    return {"items": [dict(r) for r in rows]}


@router.post("")
async def create_product(body: ProductCreate):
    pool = await get_pool()
    pid = uuid.uuid4()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO ad_review.products (id, name, sku, price, margin_rate, category, description)
            VALUES ($1::uuid, $2, $3, $4, $5, $6, $7)
            """,
            pid,
            body.name.strip(),
            body.sku,
            body.price,
            body.margin_rate,
            body.category,
            body.description or "",
        )
    return {"id": str(pid)}


@router.put("/{product_id}")
async def update_product(product_id: str, body: ProductUpdate):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT id FROM ad_review.products WHERE id = $1::uuid", product_id)
        if not row:
            raise HTTPException(status_code=404, detail="产品不存在")
        await conn.execute(
            """
            UPDATE ad_review.products SET
              name = COALESCE($2, name),
              sku = COALESCE($3, sku),
              price = COALESCE($4, price),
              margin_rate = COALESCE($5, margin_rate),
              category = COALESCE($6, category),
              description = COALESCE($7, description)
            WHERE id = $1::uuid
            """,
            product_id,
            body.name.strip() if body.name else None,
            body.sku,
            body.price,
            body.margin_rate,
            body.category,
            body.description,
        )
    return {"ok": True}


@router.delete("/{product_id}")
async def delete_product(product_id: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute("DELETE FROM ad_review.products WHERE id = $1::uuid", product_id)
        if result == "DELETE 0":
            raise HTTPException(status_code=404, detail="产品不存在")
    return {"ok": True}
