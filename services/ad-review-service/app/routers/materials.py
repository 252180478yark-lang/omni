from __future__ import annotations

import json
import uuid
from typing import Any

import httpx
from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.config import settings
from app.database import get_pool
from app.schemas import MaterialBatchGroup, MaterialLinkParent, MaterialLinkVideo, MaterialUpdate
from app.services.csv_parser import parse_tabular_file
from app.services.metrics_calculator import enrich_material_metrics

router = APIRouter(prefix="/api/v1/ad-review", tags=["ad-review-materials"])

VA_BASE = settings.video_analysis_url.rstrip("/")


async def _video_scores_snapshot(video_id: str) -> dict[str, Any] | None:
    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            r = await client.get(f"{VA_BASE}/api/v1/video-analysis/videos/{video_id}")
            if r.status_code != 200:
                return None
            report = r.json().get("report") or {}
            scores = report.get("scores")
            return scores if isinstance(scores, dict) else None
    except Exception:
        return None


async def _refresh_campaign_total_cost(conn, campaign_id: str) -> None:
    total = await conn.fetchval(
        "SELECT COALESCE(SUM(cost), 0) FROM ad_review.materials WHERE campaign_id = $1::uuid",
        campaign_id,
    )
    await conn.execute(
        "UPDATE ad_review.campaigns SET total_cost = $2, updated_at = NOW() WHERE id = $1::uuid",
        campaign_id,
        total,
    )


@router.get("/campaigns/{campaign_id}/materials")
async def list_materials(campaign_id: str, audience_pack_id: str | None = None):
    pool = await get_pool()
    async with pool.acquire() as conn:
        camp = await conn.fetchrow("SELECT id FROM ad_review.campaigns WHERE id = $1::uuid", campaign_id)
        if not camp:
            raise HTTPException(status_code=404, detail="批次不存在")
        if audience_pack_id:
            rows = await conn.fetch(
                """
                SELECT * FROM ad_review.materials
                WHERE campaign_id = $1::uuid AND audience_pack_id = $2::uuid
                ORDER BY created_at
                """,
                campaign_id,
                audience_pack_id,
            )
        else:
            rows = await conn.fetch(
                "SELECT * FROM ad_review.materials WHERE campaign_id = $1::uuid ORDER BY created_at",
                campaign_id,
            )
    return {"items": [dict(r) for r in rows]}


@router.post("/audiences/{audience_id}/import-csv")
async def import_csv(
    audience_id: str,
    file: UploadFile = File(...),
    preview: bool = Form(False),
):
    pool = await get_pool()
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="文件为空")

    name = (file.filename or "").lower()
    if not (name.endswith(".csv") or name.endswith(".xlsx") or name.endswith(".xlsm") or name.endswith(".xls")):
        raise HTTPException(status_code=400, detail="请上传千川数据文件（.csv / .xlsx）")

    try:
        rows, mapping = parse_tabular_file(raw, file.filename or "")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    preview_rows = rows[:3]
    if preview:
        return {
            "column_mapping": mapping,
            "row_count": len(rows),
            "preview": preview_rows,
        }

    async with pool.acquire() as conn:
        aud = await conn.fetchrow(
            "SELECT id, campaign_id FROM ad_review.audience_packs WHERE id = $1::uuid",
            audience_id,
        )
        if not aud:
            raise HTTPException(status_code=404, detail="人群包不存在")
        cid = str(aud["campaign_id"])

        async with conn.transaction():
            existing = await conn.fetch(
                "SELECT id, name FROM ad_review.materials WHERE audience_pack_id = $1::uuid",
                audience_id,
            )
            existing_by_name: dict[str, str] = {
                str(r["name"]).strip(): str(r["id"]) for r in existing
            }

            for row in rows:
                enriched = enrich_material_metrics(row)
                name_val = str(enriched["name"]).strip()
                existing_id = existing_by_name.get(name_val)

                if existing_id:
                    await conn.execute(
                        """
                        UPDATE ad_review.materials SET
                          cost=$2, impressions=$3, clicks=$4, front_impressions=$5, ctr=$6,
                          shares_7d=$7, comments=$8, plays=$9, play_3s=$10,
                          play_25pct=$11, play_50pct=$12, play_75pct=$13,
                          completion_rate=$14, new_a3=$15, cost_per_result=$16, a3_ratio=$17,
                          play_3s_rate=$18, interaction_rate=$19, cpm=$20, cpc=$21, conversion_rate=$22
                        WHERE id = $1::uuid
                        """,
                        existing_id,
                        enriched.get("cost"),
                        enriched.get("impressions"),
                        enriched.get("clicks"),
                        enriched.get("front_impressions"),
                        enriched.get("ctr"),
                        enriched.get("shares_7d"),
                        enriched.get("comments"),
                        enriched.get("plays"),
                        enriched.get("play_3s"),
                        enriched.get("play_25pct"),
                        enriched.get("play_50pct"),
                        enriched.get("play_75pct"),
                        enriched.get("completion_rate"),
                        enriched.get("new_a3"),
                        enriched.get("cost_per_result"),
                        enriched.get("a3_ratio"),
                        enriched.get("play_3s_rate"),
                        enriched.get("interaction_rate"),
                        enriched.get("cpm"),
                        enriched.get("cpc"),
                        enriched.get("conversion_rate"),
                    )
                else:
                    mid = uuid.uuid4()
                    await conn.execute(
                        """
                        INSERT INTO ad_review.materials (
                          id, audience_pack_id, campaign_id, name,
                          cost, impressions, clicks, front_impressions, ctr,
                          shares_7d, comments, plays, play_3s, play_25pct, play_50pct, play_75pct,
                          completion_rate, new_a3, cost_per_result, a3_ratio,
                          play_3s_rate, interaction_rate, cpm, cpc, conversion_rate
                        ) VALUES (
                          $1::uuid, $2::uuid, $3::uuid, $4,
                          $5, $6, $7, $8, $9,
                          $10, $11, $12, $13, $14, $15, $16,
                          $17, $18, $19, $20,
                          $21, $22, $23, $24, $25
                        )
                        """,
                        mid,
                        audience_id,
                        cid,
                        name_val,
                        enriched.get("cost"),
                        enriched.get("impressions"),
                        enriched.get("clicks"),
                        enriched.get("front_impressions"),
                        enriched.get("ctr"),
                        enriched.get("shares_7d"),
                        enriched.get("comments"),
                        enriched.get("plays"),
                        enriched.get("play_3s"),
                        enriched.get("play_25pct"),
                        enriched.get("play_50pct"),
                        enriched.get("play_75pct"),
                        enriched.get("completion_rate"),
                        enriched.get("new_a3"),
                        enriched.get("cost_per_result"),
                        enriched.get("a3_ratio"),
                        enriched.get("play_3s_rate"),
                        enriched.get("interaction_rate"),
                        enriched.get("cpm"),
                        enriched.get("cpc"),
                        enriched.get("conversion_rate"),
                    )

            await conn.execute(
                """
                INSERT INTO ad_review.csv_imports
                  (id, campaign_id, audience_pack_id, original_filename, row_count, column_mapping)
                VALUES ($1::uuid, $2::uuid, $3::uuid, $4, $5, $6::jsonb)
                """,
                uuid.uuid4(),
                cid,
                audience_id,
                file.filename or "import.csv",
                len(rows),
                json.dumps(mapping),
            )

            await conn.execute(
                "UPDATE ad_review.campaigns SET status = 'data_uploaded', updated_at = NOW() WHERE id = $1::uuid",
                cid,
            )
            await _refresh_campaign_total_cost(conn, cid)

        materials = await conn.fetch(
            "SELECT * FROM ad_review.materials WHERE audience_pack_id = $1::uuid ORDER BY created_at",
            audience_id,
        )
    return {"imported": len(rows), "items": [dict(r) for r in materials]}


@router.delete("/materials/{material_id}")
async def delete_material(material_id: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, campaign_id FROM ad_review.materials WHERE id = $1::uuid",
            material_id,
        )
        if not row:
            raise HTTPException(status_code=404, detail="素材不存在")
        cid = str(row["campaign_id"])
        await conn.execute(
            "UPDATE ad_review.materials SET parent_material_id = NULL WHERE parent_material_id = $1::uuid",
            material_id,
        )
        await conn.execute("DELETE FROM ad_review.materials WHERE id = $1::uuid", material_id)
        await _refresh_campaign_total_cost(conn, cid)
    return {"ok": True}


@router.put("/materials/batch-group")
async def batch_group(body: MaterialBatchGroup):
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            for mid in body.material_ids:
                await conn.execute(
                    "UPDATE ad_review.materials SET group_id = $2::uuid WHERE id = $1::uuid",
                    mid,
                    body.group_id,
                )
    return {"ok": True, "count": len(body.material_ids)}


@router.put("/materials/{material_id}")
async def update_material(material_id: str, body: MaterialUpdate):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM ad_review.materials WHERE id = $1::uuid", material_id)
        if not row:
            raise HTTPException(status_code=404, detail="素材不存在")
        vid = body.video_analysis_id
        scores = None
        if vid:
            scores = await _video_scores_snapshot(vid)
        await conn.execute(
            """
            UPDATE ad_review.materials SET
              name = COALESCE($2, name),
              video_analysis_id = COALESCE($3, video_analysis_id),
              video_analysis_scores = COALESCE($4::jsonb, video_analysis_scores),
              iteration_note = COALESCE($5, iteration_note),
              group_id = COALESCE($6::uuid, group_id),
              change_tags = COALESCE($7::jsonb, change_tags)
            WHERE id = $1::uuid
            """,
            material_id,
            body.name.strip() if body.name else None,
            vid,
            json.dumps(scores) if scores is not None else None,
            body.iteration_note,
            body.group_id,
            json.dumps(body.change_tags) if body.change_tags is not None else None,
        )
    return {"ok": True}


@router.put("/materials/{material_id}/link-video")
async def link_video(material_id: str, body: MaterialLinkVideo):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT id FROM ad_review.materials WHERE id = $1::uuid", material_id)
        if not row:
            raise HTTPException(status_code=404, detail="素材不存在")
        vid = body.video_analysis_id
        if vid is None:
            await conn.execute(
                """
                UPDATE ad_review.materials SET
                  video_analysis_id = NULL,
                  video_analysis_scores = NULL
                WHERE id = $1::uuid
                """,
                material_id,
            )
        else:
            scores = await _video_scores_snapshot(vid)
            await conn.execute(
                """
                UPDATE ad_review.materials SET
                  video_analysis_id = $2,
                  video_analysis_scores = $3::jsonb
                WHERE id = $1::uuid
                """,
                material_id,
                vid,
                json.dumps(scores) if scores else None,
            )
    return {"ok": True}


@router.put("/materials/{material_id}/link-parent")
async def link_parent(material_id: str, body: MaterialLinkParent):
    pool = await get_pool()
    async with pool.acquire() as conn:
        child = await conn.fetchrow(
            "SELECT * FROM ad_review.materials WHERE id = $1::uuid",
            material_id,
        )
        parent = await conn.fetchrow(
            "SELECT * FROM ad_review.materials WHERE id = $1::uuid",
            body.parent_material_id,
        )
        if not child or not parent:
            raise HTTPException(status_code=404, detail="素材不存在")
        if str(child["campaign_id"]) != str(parent["campaign_id"]):
            raise HTTPException(status_code=400, detail="仅支持同批次内的迭代关联")
        pv = int(parent["version"] or 1)
        await conn.execute(
            """
            UPDATE ad_review.materials SET
              parent_material_id = $2::uuid,
              version = $3,
              iteration_note = $4,
              change_tags = $5::jsonb
            WHERE id = $1::uuid
            """,
            material_id,
            body.parent_material_id,
            pv + 1,
            body.iteration_note or "",
            json.dumps(body.change_tags) if body.change_tags else "[]",
        )
    return {"ok": True}


@router.get("/materials/{material_id}/iteration-chain")
async def iteration_chain(material_id: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        cur = await conn.fetchrow("SELECT * FROM ad_review.materials WHERE id = $1::uuid", material_id)
        if not cur:
            raise HTTPException(status_code=404, detail="素材不存在")
        chain_up: list[dict[str, Any]] = [dict(cur)]
        seen = {str(cur["id"])}
        while cur.get("parent_material_id"):
            pid = str(cur["parent_material_id"])
            if pid in seen:
                break
            parent = await conn.fetchrow("SELECT * FROM ad_review.materials WHERE id = $1::uuid", pid)
            if not parent:
                break
            chain_up.append(dict(parent))
            seen.add(pid)
            cur = parent
        chain_up.reverse()

        root_id = chain_up[0]["id"]
        children = await conn.fetch(
            """
            WITH RECURSIVE sub AS (
              SELECT * FROM ad_review.materials WHERE parent_material_id = $1::uuid
              UNION ALL
              SELECT m.* FROM ad_review.materials m
              INNER JOIN sub s ON m.parent_material_id = s.id
            )
            SELECT * FROM sub
            """,
            root_id,
        )
        extras = [dict(r) for r in children if str(r["id"]) not in {str(x["id"]) for x in chain_up}]

    ordered = chain_up + sorted(extras, key=lambda x: (x.get("version") or 0, str(x["id"])))
    return {"chain": ordered}
