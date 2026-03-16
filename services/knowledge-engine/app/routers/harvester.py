"""Harvester API — crawl external help centers and ingest selected chapters."""

from __future__ import annotations

import asyncio
import logging
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.harvester import crawl_articles, fetch_nav_tree, get_job
from app.services.ingestion import submit_ingestion_task
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/knowledge/harvester", tags=["harvester"])


# ═══ Schemas ═══

class CrawlRequest(BaseModel):
    url: str = Field(min_length=10)
    max_pages: int | None = Field(default=None, ge=1, le=200)


class SaveChapter(BaseModel):
    title: str
    markdown: str
    source_url: str | None = None


class SaveRequest(BaseModel):
    kb_id: str
    chapters: list[SaveChapter] = Field(min_length=1)


# ═══ Endpoints ═══

@router.get("/auth-status")
async def auth_status():
    from pathlib import Path
    path = Path(settings.harvester_auth_state)
    return {
        "has_auth": path.exists(),
        "path": str(path),
    }


@router.post("/tree")
async def get_tree(req: CrawlRequest):
    try:
        tree = await fetch_nav_tree(req.url)
        return {"success": True, "data": tree}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/crawl")
async def start_crawl(req: CrawlRequest):
    from pathlib import Path
    auth_path = Path(settings.harvester_auth_state)
    if not auth_path.exists():
        raise HTTPException(
            status_code=400,
            detail=f"Auth state file not found: {auth_path}. Run login first.",
        )

    job_id = str(uuid4())
    asyncio.create_task(
        crawl_articles(
            url=req.url,
            auth_state_path=str(auth_path),
            max_pages=req.max_pages,
            job_id=job_id,
        )
    )
    return {"success": True, "data": {"job_id": job_id}}


@router.get("/jobs/{job_id}")
async def job_status(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"success": True, "data": job}


@router.post("/save")
async def save_chapters(req: SaveRequest):
    task_ids: list[str] = []
    for ch in req.chapters:
        if not ch.markdown.strip():
            continue
        task_id = await submit_ingestion_task(
            kb_id=req.kb_id,
            title=ch.title,
            text=ch.markdown,
            source_url=ch.source_url,
            source_type="harvester",
        )
        task_ids.append(task_id)
    return {
        "success": True,
        "data": {
            "saved_count": len(task_ids),
            "task_ids": task_ids,
        },
    }
