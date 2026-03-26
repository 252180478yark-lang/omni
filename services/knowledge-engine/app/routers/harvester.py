"""Harvester API — crawl external help centers and ingest selected chapters."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.services.harvester import (
    crawl_articles, crawl_feishu_doc, fetch_nav_tree, get_job, IMAGE_DIR,
    list_job_images, get_chapter_images, analyze_images, merge_image_descriptions,
    start_browser_login, get_login_session, _is_feishu_url,
    ingest_extracted_page, get_last_upload_job_id,
)
from app.services.ingestion import submit_ingestion_task
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/knowledge/harvester", tags=["harvester"])


# ═══ Schemas ═══

class SelectedArticle(BaseModel):
    title: str
    mapping_id: str | int
    graph_path: str
    target_id: str | int | None = None


class CrawlRequest(BaseModel):
    url: str = Field(min_length=10)
    max_pages: int | None = Field(default=None, ge=1, le=200)
    selected_articles: list[SelectedArticle] | None = None


class CookieItem(BaseModel):
    name: str
    value: str
    domain: str
    path: str = "/"


class SaveAuthRequest(BaseModel):
    cookies: list[CookieItem] = Field(min_length=1)


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
    path = Path(settings.harvester_auth_state)
    return {
        "success": True,
        "data": {"has_auth": path.exists(), "path": str(path)},
    }


@router.post("/save-auth")
async def save_auth(req: SaveAuthRequest):
    """Convert browser cookies to Playwright storage state and persist."""
    pw_cookies = []
    for c in req.cookies:
        pw_cookies.append({
            "name": c.name,
            "value": c.value,
            "domain": c.domain,
            "path": c.path,
            "httpOnly": False,
            "secure": True,
            "sameSite": "None",
        })

    state = {"cookies": pw_cookies, "origins": []}
    path = Path(settings.harvester_auth_state)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2))
    logger.info("Saved %d cookies to %s", len(pw_cookies), path)
    return {"success": True, "data": {"saved_cookies": len(pw_cookies)}}


@router.delete("/auth")
async def clear_auth():
    path = Path(settings.harvester_auth_state)
    if path.exists():
        path.unlink()
    return {"success": True}


class UploadLoginCookiesRequest(BaseModel):
    login_type: str = Field(..., pattern="^(oceanengine|feishu)$")
    cookies: list[dict]


@router.post("/upload-login-cookies")
async def upload_login_cookies(req: UploadLoginCookiesRequest):
    """Accept cookies captured by the local browser_login.py script."""
    auth_path = Path(
        settings.feishu_auth_state
        if req.login_type == "feishu"
        else settings.harvester_auth_state
    )
    state = {"cookies": req.cookies, "origins": []}
    auth_path.parent.mkdir(parents=True, exist_ok=True)
    auth_path.write_text(json.dumps(state, ensure_ascii=False, indent=2))
    logger.info(
        "upload-login-cookies [%s]: saved %d cookies to %s",
        req.login_type, len(req.cookies), auth_path,
    )
    return {"success": True, "data": {"cookies_saved": len(req.cookies)}}


class BrowserLoginRequest(BaseModel):
    url: str = Field(default="https://yuntu.oceanengine.com", min_length=5)


@router.post("/browser-login")
async def browser_login(req: BrowserLoginRequest):
    """Launch a visible browser for interactive login and auto-capture cookies."""
    auth_path = str(Path(settings.harvester_auth_state))
    result = await start_browser_login(
        target_url=req.url,
        auth_state_path=auth_path,
        login_type="oceanengine",
    )
    return {"success": True, "data": result}


class FeishuBrowserLoginRequest(BaseModel):
    url: str = Field(default="https://bytedance.larkoffice.com", min_length=5)


@router.post("/feishu-browser-login")
async def feishu_browser_login(req: FeishuBrowserLoginRequest):
    """Launch a visible browser for Feishu/Lark login and auto-capture cookies."""
    auth_path = str(Path(settings.feishu_auth_state))
    result = await start_browser_login(
        target_url=req.url,
        auth_state_path=auth_path,
        login_type="feishu",
    )
    return {"success": True, "data": result}


@router.get("/feishu-auth-status")
async def feishu_auth_status():
    path = Path(settings.feishu_auth_state)
    return {
        "success": True,
        "data": {"has_auth": path.exists(), "path": str(path)},
    }


@router.delete("/feishu-auth")
async def clear_feishu_auth():
    path = Path(settings.feishu_auth_state)
    if path.exists():
        path.unlink()
    return {"success": True}


@router.get("/browser-login/{session_id}")
async def browser_login_status(session_id: str):
    session = get_login_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Login session not found")
    return {"success": True, "data": session}


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
    job_id = str(uuid4())

    if _is_feishu_url(req.url):
        feishu_path = Path(settings.feishu_auth_state)
        auth_state: str | None = str(feishu_path) if feishu_path.exists() else None
        if not auth_state:
            logger.warning("Feishu auth not found at %s — attempting without auth", feishu_path)
        asyncio.create_task(
            crawl_feishu_doc(url=req.url, auth_state_path=auth_state, job_id=job_id)
        )
        return {"success": True, "data": {"job_id": job_id, "has_auth": auth_state is not None, "type": "feishu"}}

    auth_path = Path(settings.harvester_auth_state)
    auth_state = str(auth_path) if auth_path.exists() else None
    if not auth_state:
        logger.warning("Auth state file not found at %s — crawling without auth (some pages may fail)", auth_path)

    sel_articles = None
    if req.selected_articles:
        sel_articles = [
            {"title": a.title, "mapping_id": a.mapping_id, "graph_path": a.graph_path,
             "target_id": a.target_id or a.mapping_id}
            for a in req.selected_articles
        ]

    asyncio.create_task(
        crawl_articles(
            url=req.url, auth_state_path=auth_state,
            max_pages=req.max_pages, job_id=job_id,
            selected_articles=sel_articles,
        )
    )
    return {"success": True, "data": {"job_id": job_id, "has_auth": auth_state is not None, "type": "yuntu"}}


@router.get("/latest-upload")
async def latest_upload():
    """Return the job_id of the most recent upload from browser_extract.py."""
    jid = get_last_upload_job_id()
    if not jid:
        return {"success": True, "data": None}
    job = get_job(jid)
    return {"success": True, "data": {"job_id": jid, "status": job["status"] if job else "unknown"}}


@router.get("/jobs/{job_id}")
async def job_status(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"success": True, "data": job}


@router.get("/images/{job_id}/{filename}")
async def serve_image(job_id: str, filename: str):
    """Serve a downloaded image file."""
    safe_name = Path(filename).name
    filepath = IMAGE_DIR / job_id / safe_name
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Image not found")
    suffix = filepath.suffix.lower()
    media_types = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                   ".gif": "image/gif", ".webp": "image/webp"}
    return FileResponse(filepath, media_type=media_types.get(suffix, "image/png"))


class AnalyzeImagesRequest(BaseModel):
    job_id: str
    chapter_index: int
    filenames: list[str] = Field(default_factory=list)
    prompt: str = ""
    merge: bool = True


@router.get("/jobs/{job_id}/images")
async def job_images(job_id: str, chapter_index: int | None = None):
    """List images for a job, optionally filtered by chapter index."""
    if chapter_index is not None:
        images = get_chapter_images(job_id, chapter_index)
    else:
        images = list_job_images(job_id)
    return {"success": True, "data": images}


@router.post("/analyze-images")
async def analyze_images_endpoint(req: AnalyzeImagesRequest):
    """Analyze selected images via LLM and optionally merge descriptions into chapter."""
    job = get_job(req.job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if not req.filenames:
        images = get_chapter_images(req.job_id, req.chapter_index)
        filenames = [img["filename"] for img in images if img.get("exists")]
    else:
        filenames = req.filenames

    if not filenames:
        return {"success": True, "data": {"results": [], "message": "No images to analyze"}}

    results = await analyze_images(req.job_id, filenames, req.prompt)

    if req.merge:
        descriptions = {r["filename"]: r["description"] for r in results if "description" in r}
        if descriptions:
            updated = merge_image_descriptions(req.job_id, req.chapter_index, descriptions)
            return {
                "success": True,
                "data": {
                    "results": results,
                    "chapter": updated,
                    "merged": len(descriptions),
                },
            }

    return {"success": True, "data": {"results": results}}


class UploadExtractedPageRequest(BaseModel):
    url: str
    title: str = ""
    markdown: str = ""
    images: list[dict] = Field(default_factory=list)
    block_map: dict | None = None


@router.post("/upload-extracted-page")
async def upload_extracted_page(req: UploadExtractedPageRequest):
    """Receive content extracted by the local browser_extract.py script."""
    try:
        result = await ingest_extracted_page(
            url=req.url,
            title=req.title,
            markdown=req.markdown,
            images=req.images,
            block_map=req.block_map,
        )
        return {"success": True, "data": result}
    except Exception as e:
        logger.exception("upload-extracted-page failed")
        raise HTTPException(status_code=500, detail=str(e))


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
