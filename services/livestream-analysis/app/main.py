"""直播切片分析 — FastAPI 服务入口"""

import json
import logging
import os
import sqlite3
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import quote

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
DB_PATH = DATA_DIR / "livestream.db"
VIDEOS_DIR = DATA_DIR / "videos"
VIDEOS_DIR.mkdir(parents=True, exist_ok=True)

# ── SQLite ──────────────────────────────────────────────────────────
_local = threading.local()


def _get_conn() -> sqlite3.Connection:
    if not hasattr(_local, "conn"):
        _local.conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
    return _local.conn


@contextmanager
def get_db():
    conn = _get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def _init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                original_name TEXT NOT NULL,
                display_name TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                phase TEXT DEFAULT 'queued',
                message TEXT DEFAULT '',
                progress_current INTEGER DEFAULT 0,
                progress_total INTEGER DEFAULT 4,
                video_path TEXT,
                excel_path TEXT,
                json_path TEXT,
                error TEXT,
                summary_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        try:
            conn.execute("ALTER TABLE tasks ADD COLUMN display_name TEXT DEFAULT ''")
        except Exception:
            pass


_init_db()

# ── App ─────────────────────────────────────────────────────────────
app = FastAPI(title="直播切片分析", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])

executor = ThreadPoolExecutor(max_workers=settings.parallel_workers)
_job_lock = threading.Lock()
_active_jobs: set[str] = set()


def _update_task(task_id: str, **kw):
    kw["updated_at"] = datetime.now(timezone.utc).isoformat()
    cols = ", ".join(f"{k}=?" for k in kw)
    vals = list(kw.values()) + [task_id]
    with get_db() as conn:
        conn.execute(f"UPDATE tasks SET {cols} WHERE id=?", vals)


def _get_task(task_id: str) -> Optional[dict]:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    return dict(row) if row else None


def _backfill_display_names():
    """For existing done tasks without display_name, generate one from their JSON report."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, json_path, created_at FROM tasks WHERE status='done' AND (display_name IS NULL OR display_name='')"
        ).fetchall()
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
            dt = datetime.fromisoformat(cat.replace("Z", "+00:00"))
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

    now = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        conn.execute(
            "INSERT INTO tasks (id, original_name, status, phase, message, video_path, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (task_id, file.filename, "queued", "queued", "排队中...", str(video_path), now, now),
        )

    with _job_lock:
        _active_jobs.add(task_id)
    executor.submit(_run_analysis, task_id, str(video_path), str(task_dir))

    return {"task_id": task_id, "original_name": file.filename, "status": "queued"}


@app.get(f"{BASE_PREFIX}/videos")
def list_videos():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, original_name, display_name, status, created_at FROM tasks ORDER BY created_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


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
        "created_at": t["created_at"],
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
            "created_at": t["created_at"],
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
        conn.execute("DELETE FROM tasks WHERE id=?", (video_id,))
    return {"deleted": True}
