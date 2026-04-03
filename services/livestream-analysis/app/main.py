"""直播切片分析 — FastAPI 服务入口"""

from dotenv import load_dotenv

load_dotenv()

import json
import logging
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import quote

import psycopg2
import psycopg2.extras

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response

from app.config import Settings
from app.models import AnalysisResult
from app.services.gemini_client import GeminiClient, GeminiAPIError
from app.services.video_processor import VideoProcessor, VideoProcessError
from app.services.prompt_builder import PromptBuilder
from app.services.response_parser import ResponseParser, ParseError
from app.services.excel_writer import ExcelWriter

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s %(message)s")
logger = logging.getLogger("livestream-analysis")

BASE_PREFIX = "/api/v1/livestream-analysis"

settings = Settings()
DATA_DIR = Path(settings.data_dir)
DATA_DIR.mkdir(parents=True, exist_ok=True)
VIDEOS_DIR = DATA_DIR / "videos"
VIDEOS_DIR.mkdir(parents=True, exist_ok=True)

# ── PostgreSQL ───────────────────────────────────────────────────────
_DB_DSN: str | None = None


def _dsn() -> str:
    global _DB_DSN
    if _DB_DSN is None:
        _DB_DSN = os.environ.get("DATABASE_URL", "")
    if not _DB_DSN:
        raise RuntimeError("DATABASE_URL environment variable is not set")
    return _DB_DSN


@contextmanager
def get_db():
    conn = psycopg2.connect(_dsn())
    conn.autocommit = False
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _row_to_dict(cursor, row) -> dict:
    cols = [desc[0] for desc in cursor.description]
    return dict(zip(cols, row))


def _init_db():
    """Tables are created by init.sql at PostgreSQL startup; this is a no-op."""
    logger.info("livestream-analysis using PostgreSQL (schema: livestream)")


def _sync_key_from_ai_hub() -> None:
    """启动时从 ai-provider-hub 同步 Gemini API Key 和默认模型，hub 配置优先于本地 env。"""
    import httpx
    ai_hub_url = os.environ.get("AI_PROVIDER_HUB_URL", "http://ai-provider-hub:8001")
    try:
        resp = httpx.get(f"{ai_hub_url}/api/v1/ai/provider-secrets/gemini", timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            key = data.get("api_key", "").strip()
            model = data.get("default_chat_model", "").strip()
            if key:
                settings.gemini_api_key = key
                logger.info("Gemini API Key 已从 ai-provider-hub 同步")
            if model:
                settings.gemini_model = model
                logger.info("Gemini 模型已从 ai-provider-hub 同步: %s", model)
            if key:
                return
    except Exception as exc:
        logger.warning("无法从 ai-provider-hub 同步配置: %s，将使用本地环境变量", exc)
    if settings.gemini_api_key:
        logger.info("使用本地环境变量中的 Gemini API Key，模型: %s", settings.gemini_model)
    else:
        logger.warning("未找到 Gemini API Key，请在 ai-provider-hub 模型配置页面设置")


# ── App ─────────────────────────────────────────────────────────────
app = FastAPI(title="直播切片分析", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
def on_startup():
    _sync_key_from_ai_hub()

executor = ThreadPoolExecutor(max_workers=settings.parallel_workers)
_job_lock = threading.Lock()
_active_jobs: set[str] = set()


def _update_task(task_id: str, **kw):
    kw["updated_at"] = datetime.now(timezone.utc)
    cols = ", ".join(f"{k} = %s" for k in kw)
    vals = list(kw.values()) + [task_id]
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE livestream.tasks SET {cols} WHERE id = %s", vals)


def _get_task(task_id: str) -> Optional[dict]:
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM livestream.tasks WHERE id = %s", (task_id,))
            row = cur.fetchone()
            return _row_to_dict(cur, row) if row else None


def _backfill_display_names():
    """For existing done tasks without display_name, generate one from their JSON report."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, json_path, created_at FROM livestream.tasks WHERE status='done' AND (display_name IS NULL OR display_name='')"
            )
            rows = [_row_to_dict(cur, r) for r in cur.fetchall()]
    for row in rows:
        tid = row["id"]
        jp = row["json_path"]
        cat = row["created_at"]
        if not jp or not os.path.exists(jp):
            continue
        try:
            with open(jp, "r", encoding="utf-8") as f:
                data = json.load(f)
            r = AnalysisResult(**data)
            dt = cat if isinstance(cat, datetime) else datetime.fromisoformat(str(cat).replace("Z", "+00:00"))
            date_str = dt.strftime("%m%d_%H%M")
            dur = r.summary.total_duration or "未知"
            parts: list[str] = []
            if r.summary.overall_style:
                parts.append(r.summary.overall_style[:12])
            if r.summary.person_summary:
                parts.append("·".join(p.role for p in r.summary.person_summary[:2]))
            content = "_".join(parts) if parts else "直播分析"
            _update_task(tid, display_name=f"{date_str}_{dur}_{content}")
        except Exception as e:
            logger.warning("Backfill display_name failed for %s: %s", tid, e)


_backfill_display_names()


def _build_display_name(result: AnalysisResult, task_id: str) -> str:
    """Generate a human-readable name: 日期_时长_主要内容."""
    now = datetime.now()
    date_str = now.strftime("%m%d_%H%M")
    duration = result.summary.total_duration or "未知"

    content_parts: list[str] = []
    style = result.summary.overall_style
    if style:
        content_parts.append(style[:12])
    phases = list(result.summary.phase_distribution.keys())
    if phases and not content_parts:
        content_parts.append("+".join(phases[:3]))
    if result.summary.person_summary:
        roles = [p.role for p in result.summary.person_summary[:2]]
        content_parts.append("·".join(roles))
    content = "_".join(content_parts) if content_parts else "直播分析"
    return f"{date_str}_{duration}_{content}"


# ── Analysis worker ─────────────────────────────────────────────────
def _run_analysis(task_id: str, video_path: str, output_dir: str):
    try:
        _update_task(task_id, status="running", phase="metadata", message="读取视频信息...")

        if not settings.gemini_api_key:
            _update_task(task_id, status="failed", error="Gemini API Key 未配置")
            return

        processor = VideoProcessor()
        client = GeminiClient(settings)
        prompt_builder = PromptBuilder()
        parser = ResponseParser()
        writer = ExcelWriter()

        def progress(phase: str, msg: str, cur: int = 0, total: int = 4):
            _update_task(task_id, phase=phase, message=msg, progress_current=cur, progress_total=total)

        metadata = processor.get_metadata(video_path)
        needs_split = processor.needs_split(metadata, settings.segment_duration_minutes)

        if needs_split:
            progress("analyzing", "视频较长，正在分片...", 2, 4)
            segments = processor.split_video(video_path, settings.segment_duration_minutes)
            results = []
            for i, seg in enumerate(segments):
                progress("analyzing", f"分析片段 {i+1}/{len(segments)}", 3, 4)
                fi = client.upload_video(seg.path, display_name=f"segment_{i+1}")
                prompt = prompt_builder.build_segment_prompt(seg)
                raw = client.analyze_video(fi.uri, fi.mime_type, prompt)
                results.append(parser.parse(raw))
                client.delete_file(fi.name)
            processor.cleanup_segments(segments)
            result = parser.merge_segments(results)
        else:
            progress("uploading", "上传视频到 Gemini...", 2, 4)
            fi = client.upload_video(video_path)
            progress("analyzing", "AI 分析中，请稍候...", 3, 4)
            prompt = prompt_builder.build_full_video_prompt(metadata)
            raw = client.analyze_video(fi.uri, fi.mime_type, prompt)
            result = parser.parse(raw)
            client.delete_file(fi.name)

        progress("writing", "生成报告...", 4, 4)
        stem = Path(video_path).stem
        excel_path = os.path.join(output_dir, f"{stem}_analysis.xlsx")
        json_path = os.path.join(output_dir, f"{stem}_analysis.json")
        writer.write(result, excel_path)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(result.model_dump(), f, ensure_ascii=False, indent=2)

        display_name = _build_display_name(result, task_id)
        _update_task(task_id, status="done", phase="done", message="分析完成",
                     progress_current=4, excel_path=excel_path, json_path=json_path,
                     display_name=display_name,
                     summary_json=json.dumps(result.summary.model_dump(), ensure_ascii=False))

    except (GeminiAPIError, VideoProcessError, ParseError, FileNotFoundError) as e:
        _update_task(task_id, status="failed", error=str(e))
    except Exception as e:
        logger.exception("分析异常")
        _update_task(task_id, status="failed", error=str(e))
    finally:
        with _job_lock:
            _active_jobs.discard(task_id)


# ── Routes ──────────────────────────────────────────────────────────
@app.get("/health")
@app.get("/api/health")
def health():
    return {"status": "ok", "service": "livestream-analysis"}


@app.get(f"{BASE_PREFIX}/settings/gemini/status")
def gemini_status():
    return {
        "api_key_set": bool(settings.gemini_api_key),
        "model": settings.gemini_model,
    }


@app.post(f"{BASE_PREFIX}/settings/gemini/test")
async def gemini_test(body: dict):
    api_key = body.get("api_key", "")
    model = body.get("model", "")
    if not api_key:
        raise HTTPException(400, "api_key is required")

    settings.gemini_api_key = api_key
    if model:
        settings.gemini_model = model

    try:
        client = GeminiClient(settings)
        info = client.test_connection()
        return {"success": True, "model_info": info}
    except GeminiAPIError as e:
        raise HTTPException(400, str(e))


CHUNK_SIZE = 4 * 1024 * 1024  # 4MB chunks for streaming upload


@app.post(f"{BASE_PREFIX}/videos")
async def upload_video(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(400, "未选择文件")
    ext = Path(file.filename).suffix.lower()
    if ext not in (".mp4", ".mov"):
        raise HTTPException(400, "仅支持 MP4、MOV 格式")

    task_id = str(uuid.uuid4())
    task_dir = VIDEOS_DIR / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    video_path = task_dir / file.filename

    total = 0
    with open(video_path, "wb") as out:
        while True:
            chunk = await file.read(CHUNK_SIZE)
            if not chunk:
                break
            total += len(chunk)
            if total > 2 * 1024 * 1024 * 1024:
                out.close()
                os.remove(video_path)
                raise HTTPException(400, "文件大小不能超过 2GB")
            out.write(chunk)

    now = datetime.now(timezone.utc)
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO livestream.tasks (id, original_name, status, phase, message, video_path, created_at, updated_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (task_id, file.filename, "queued", "queued", "排队中...", str(video_path), now, now),
            )

    with _job_lock:
        _active_jobs.add(task_id)
    executor.submit(_run_analysis, task_id, str(video_path), str(task_dir))

    return {"task_id": task_id, "original_name": file.filename, "status": "queued"}


@app.get(f"{BASE_PREFIX}/videos")
def list_videos():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, original_name, display_name, status, created_at FROM livestream.tasks ORDER BY created_at DESC"
            )
            rows = cur.fetchall()
            result = []
            for r in rows:
                d = _row_to_dict(cur, r)
                if isinstance(d.get("created_at"), datetime):
                    d["created_at"] = d["created_at"].isoformat()
                result.append(d)
            return result


@app.get(f"{BASE_PREFIX}/tasks/{{task_id}}")
def task_status(task_id: str):
    t = _get_task(task_id)
    if not t:
        raise HTTPException(404, "任务不存在")

    summary = None
    if t.get("summary_json"):
        try:
            summary = json.loads(t["summary_json"])
        except Exception:
            pass

    return {
        "task_id": task_id,
        "original_name": t["original_name"],
        "display_name": t.get("display_name") or t["original_name"],
        "status": t["status"],
        "phase": t["phase"],
        "message": t["message"],
        "progress": {"current": t["progress_current"], "total": t["progress_total"]},
        "excel_url": f"{BASE_PREFIX}/tasks/{task_id}/report.xlsx" if t.get("excel_path") else None,
        "json_url": f"{BASE_PREFIX}/tasks/{task_id}/report.json" if t.get("json_path") else None,
        "error": t.get("error"),
        "summary": summary,
        "created_at": t["created_at"].isoformat() if isinstance(t["created_at"], datetime) else t["created_at"],
    }


@app.get(f"{BASE_PREFIX}/videos/{{video_id}}")
def video_detail(video_id: str):
    t = _get_task(video_id)
    if not t:
        raise HTTPException(404, "视频不存在")

    report = None
    if t.get("json_path") and os.path.exists(t["json_path"]):
        try:
            with open(t["json_path"], "r", encoding="utf-8") as f:
                report = json.load(f)
        except Exception:
            pass

    return {
        "video": {
            "id": t["id"],
            "original_name": t["original_name"],
            "status": t["status"],
            "created_at": t["created_at"].isoformat() if isinstance(t["created_at"], datetime) else t["created_at"],
            "last_error": t.get("error"),
        },
        "report": report,
        "report_json_url": f"{BASE_PREFIX}/tasks/{video_id}/report.json" if t.get("json_path") else None,
        "report_excel_url": f"{BASE_PREFIX}/tasks/{video_id}/report.xlsx" if t.get("excel_path") else None,
    }


@app.get(f"{BASE_PREFIX}/tasks/{{task_id}}/report.xlsx")
def download_excel(task_id: str):
    t = _get_task(task_id)
    if not t or not t.get("excel_path") or not os.path.exists(t["excel_path"]):
        raise HTTPException(404, "报告尚未生成")
    display = t.get("display_name") or Path(t["original_name"]).stem
    fname = f"{display}_report.xlsx"
    ascii_fname = f"report_{task_id[:8]}.xlsx"
    encoded = quote(fname)
    data = Path(t["excel_path"]).read_bytes()
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename=\"{ascii_fname}\"; filename*=UTF-8''{encoded}",
            "Content-Length": str(len(data)),
        },
    )


@app.get(f"{BASE_PREFIX}/tasks/{{task_id}}/report.json")
def download_json(task_id: str):
    t = _get_task(task_id)
    if not t or not t.get("json_path") or not os.path.exists(t["json_path"]):
        raise HTTPException(404, "数据尚未生成")
    display = t.get("display_name") or Path(t["original_name"]).stem
    fname = f"{display}_data.json"
    ascii_fname = f"data_{task_id[:8]}.json"
    encoded = quote(fname)
    data = Path(t["json_path"]).read_bytes()
    return Response(
        content=data,
        media_type="application/json; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename=\"{ascii_fname}\"; filename*=UTF-8''{encoded}",
            "Content-Length": str(len(data)),
        },
    )


DOWNLOADS_DIR = Path(r"e:\agent\omni\downloads\reports")
DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)


@app.post(f"{BASE_PREFIX}/tasks/{{task_id}}/save-local")
def save_local(task_id: str):
    """Copy report files to the project downloads folder with friendly names."""
    t = _get_task(task_id)
    if not t:
        raise HTTPException(404, "任务不存在")
    display = t.get("display_name") or Path(t["original_name"]).stem
    safe = display.replace("/", "_").replace("\\", "_").replace(":", "-")
    saved: list[str] = []

    if t.get("excel_path") and os.path.exists(t["excel_path"]):
        dest = DOWNLOADS_DIR / f"{safe}_分析报告.xlsx"
        import shutil
        shutil.copy2(t["excel_path"], dest)
        saved.append(str(dest))

    if t.get("json_path") and os.path.exists(t["json_path"]):
        dest = DOWNLOADS_DIR / f"{safe}_分析数据.json"
        import shutil
        shutil.copy2(t["json_path"], dest)
        saved.append(str(dest))

    if not saved:
        raise HTTPException(404, "报告文件不存在")

    return {
        "success": True,
        "files": saved,
        "folder": str(DOWNLOADS_DIR),
    }


@app.delete(f"{BASE_PREFIX}/videos/{{video_id}}")
def delete_video(video_id: str):
    t = _get_task(video_id)
    if not t:
        raise HTTPException(404, "视频不存在")
    task_dir = VIDEOS_DIR / video_id
    import shutil
    if task_dir.exists():
        shutil.rmtree(task_dir, ignore_errors=True)
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM livestream.tasks WHERE id = %s", (video_id,))
    return {"deleted": True}
