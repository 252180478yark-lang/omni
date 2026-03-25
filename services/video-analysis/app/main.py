from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from queue import Queue
from threading import Thread
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.config import settings
from app.services.analysis import (
    analyze_video,
    build_placeholder_report,
    pack_report_bundle,
    render_markdown,
    render_text,
)
from app.services.emotion_curve import save_curve_image
from app.services.inputs import build_analysis_inputs
from app.storage import (
    CURVE_DIR,
    REPORT_DIR,
    UPLOAD_DIR,
    add_knowledge_entry,
    create_video_record,
    delete_video,
    get_daily_costs,
    get_video,
    increment_retry,
    init_db,
    list_videos,
    load_settings,
    log_cost,
    mark_video_failed,
    retry_failed_kb_pushes,
    save_settings,
    search_knowledge,
    set_video_status,
    update_video_report,
)

BASE_PREFIX = "/api/v1/video-analysis"

app = FastAPI(title=settings.service_name, version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount(f"{BASE_PREFIX}/assets", StaticFiles(directory=str(Path(settings.data_dir))), name="video-assets")

WORK_QUEUE: "Queue[dict[str, Any]]" = Queue()
WORKER_STARTED = False
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "2"))
PARALLEL_WORKERS = int(os.getenv("PARALLEL_WORKERS", "3"))


class GeminiConfig(BaseModel):
    api_key: str
    model: str | None = None
    cost_per_1k: float | None = None


class DeleteVideosBody(BaseModel):
    video_ids: list[str]


class PackBundleRequest(BaseModel):
    output_dir: str | None = None


def _mask_key(key: str) -> str:
    value = key.strip()
    if len(value) <= 6:
        return "*" * len(value)
    return f"{value[:2]}****{value[-4:]}"


def _get_gemini_model(config_model: str | None = None) -> str:
    return (config_model or os.getenv("GEMINI_MODEL") or "gemini-2.0-flash").strip()


def _set_gemini_env(config: GeminiConfig) -> str:
    api_key = config.api_key.strip()
    if not api_key:
        raise HTTPException(status_code=400, detail="API Key 不能为空")
    os.environ["GEMINI_API_KEY"] = api_key
    model = _get_gemini_model(config.model)
    os.environ["GEMINI_MODEL"] = model
    if config.cost_per_1k is not None:
        os.environ["GEMINI_COST_PER_1K"] = str(config.cost_per_1k)
    return model


def _load_persisted_settings() -> None:
    data = load_settings()
    api_key = str(data.get("gemini_api_key", "")).strip()
    model = str(data.get("gemini_model", "")).strip()
    cost = data.get("gemini_cost_per_1k")
    if api_key:
        os.environ["GEMINI_API_KEY"] = api_key
    if model:
        os.environ["GEMINI_MODEL"] = model
    if cost is not None:
        os.environ["GEMINI_COST_PER_1K"] = str(cost)


def _test_gemini_connection(api_key: str, model: str) -> dict[str, Any]:
    try:
        import google.generativeai as genai
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"未安装 google-generativeai：{exc}") from exc
    genai.configure(api_key=api_key, transport="rest")
    try:
        models = list(genai.list_models())
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Gemini 连接失败：{exc}") from exc
    available = any(model in getattr(item, "name", "") for item in models)
    return {"available": available, "model": model}


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    _load_persisted_settings()
    _start_worker()
    Thread(target=retry_failed_kb_pushes, daemon=True).start()


def _start_worker() -> None:
    global WORKER_STARTED
    if WORKER_STARTED:
        return
    WORKER_STARTED = True
    thread = Thread(target=_dispatcher_loop, daemon=True)
    thread.start()


def _enqueue(video_id: str, original_name: str, upload_path: Path) -> None:
    WORK_QUEUE.put({"id": video_id, "name": original_name, "path": upload_path})
    set_video_status(video_id, "queued", progress=0.05, status_message="排队中")


def _dispatcher_loop() -> None:
    pool = ThreadPoolExecutor(max_workers=PARALLEL_WORKERS, thread_name_prefix="analyzer")
    while True:
        job = WORK_QUEUE.get()
        pool.submit(_process_job_safe, job)


def _process_job_safe(job: dict[str, Any]) -> None:
    try:
        _process_job(job)
    finally:
        WORK_QUEUE.task_done()


def _process_job(job: dict[str, Any]) -> None:
    video_id = str(job["id"])
    original_name = str(job["name"])
    upload_path = Path(job["path"])
    if not get_video(video_id):
        return

    try:
        set_video_status(video_id, "processing", progress=0.1, status_message="解析输入")
        try:
            analysis_inputs = build_analysis_inputs(upload_path)
        except Exception as exc:
            analysis_inputs = {"input_error": str(exc)}

        set_video_status(video_id, "processing", progress=0.25, status_message="生成分析")
        video_record = get_video(video_id)
        metrics_raw = (video_record or {}).get("metrics_json")
        metrics_data = None
        if metrics_raw:
            try:
                metrics_data = json.loads(metrics_raw)
            except Exception:
                pass
        report, usage, used_gemini = analyze_video(video_id, original_name, upload_path, analysis_inputs, metrics=metrics_data)
        report["analysis_inputs"] = analysis_inputs
        report.setdefault("meta", {})["used_gemini"] = used_gemini

        set_video_status(video_id, "processing", progress=0.6, status_message="生成曲线")
        curve = report.get("ai_insights", {}).get("emotion_curve", [])
        if not isinstance(curve, list):
            curve = []
        report.setdefault("ai_insights", {})["emotion_curve"] = curve
        curve_path = CURVE_DIR / f"{video_id}.png"
        if curve:
            try:
                save_curve_image(curve, curve_path)
            except Exception as exc:
                report.setdefault("analysis_warnings", []).append(f"curve_image_failed: {exc}")
                curve_path = Path("")
        else:
            curve_path = Path("")

        set_video_status(video_id, "processing", progress=0.75, status_message="渲染报告")
        try:
            md_text = render_markdown(report, curve)
        except Exception as render_exc:
            report.setdefault("analysis_warnings", []).append(f"render_markdown_failed: {render_exc}")
            md_text = f"# 报告渲染失败\n\n{render_exc}\n\n```json\n{json.dumps(report.get('summary', ''), ensure_ascii=False)}\n```"
        try:
            txt_text = render_text(report)
        except Exception as render_exc:
            report.setdefault("analysis_warnings", []).append(f"render_text_failed: {render_exc}")
            txt_text = f"报告渲染失败：{render_exc}\n概览：{report.get('summary', '')}"
        md_path = REPORT_DIR / f"{video_id}.md"
        txt_path = REPORT_DIR / f"{video_id}.txt"
        json_path = REPORT_DIR / f"{video_id}.json"
        md_path.write_text(md_text, encoding="utf-8")
        txt_path.write_text(txt_text, encoding="utf-8")
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

        set_video_status(video_id, "processing", progress=0.9, status_message="写入文件")
        update_video_report(video_id, str(md_path), str(json_path), str(txt_path), str(curve_path))
        if usage:
            log_cost(video_id, usage)
        tags = report.get("ai_insights", {}).get("semantic_tags", [])
        add_knowledge_entry(video_id, str(report.get("summary", "")), tags if isinstance(tags, list) else [])

        set_video_status(video_id, "processing", progress=0.95, status_message="打包报告")
        try:
            bundle_output_path = pack_report_bundle(
                original_name=original_name,
                json_path=json_path,
                md_path=md_path,
                txt_path=txt_path,
                curve_path=curve_path,
            )
            if bundle_output_path:
                report.setdefault("meta", {})["bundle_path"] = str(bundle_output_path)
        except Exception as pack_exc:
            report.setdefault("analysis_warnings", []).append(f"pack_bundle_failed: {pack_exc}")
        set_video_status(video_id, "done", progress=1.0, status_message="完成")
    except Exception as exc:
        retries = increment_retry(video_id)
        error = str(exc)
        if retries <= MAX_RETRIES:
            set_video_status(video_id, "queued", error=error)
            WORK_QUEUE.put(job)
        else:
            mark_video_failed(video_id, error)


@app.get("/health")
@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/settings/gemini/status")
@app.get(f"{BASE_PREFIX}/settings/gemini/status")
def gemini_status() -> dict[str, Any]:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    model = _get_gemini_model()
    return {"configured": bool(api_key), "model": model, "masked_key": _mask_key(api_key) if api_key else None}


@app.post("/api/settings/gemini/test")
@app.post(f"{BASE_PREFIX}/settings/gemini/test")
def gemini_test(config: GeminiConfig) -> dict[str, Any]:
    model = _set_gemini_env(config)
    existing = load_settings()
    existing.update(
        {"gemini_api_key": config.api_key.strip(), "gemini_model": model, "gemini_cost_per_1k": config.cost_per_1k}
    )
    save_settings(existing)
    result = _test_gemini_connection(config.api_key.strip(), model)
    return {"ok": True, "available": result["available"], "model": model, "masked_key": _mask_key(config.api_key)}


@app.post("/api/videos")
@app.post(f"{BASE_PREFIX}/videos")
async def upload_video(file: UploadFile = File(...), metrics: str | None = None) -> dict[str, Any]:
    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing filename")
    metrics_json = None
    if metrics:
        try:
            json.loads(metrics)
            metrics_json = metrics
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="metrics 必须是合法的 JSON 字符串")
    video_id = uuid4().hex
    upload_path = UPLOAD_DIR / f"{video_id}_{file.filename}"
    upload_path.parent.mkdir(parents=True, exist_ok=True)
    create_video_record(video_id, file.filename, str(upload_path), metrics_json=metrics_json)
    try:
        with upload_path.open("wb") as f:
            f.write(await file.read())
    except Exception as exc:
        mark_video_failed(video_id, str(exc))
        raise HTTPException(status_code=500, detail=f"Upload failed: {exc}") from exc
    _enqueue(video_id, file.filename, upload_path)
    return {
        "id": video_id,
        "task_id": video_id,
        "original_name": file.filename,
        "status": "queued",
        "report_markdown_url": f"{BASE_PREFIX}/videos/{video_id}/report.md",
        "report_json_url": f"{BASE_PREFIX}/videos/{video_id}/report.json",
        "report_txt_url": f"{BASE_PREFIX}/videos/{video_id}/report.txt",
        "emotion_png_url": f"{BASE_PREFIX}/videos/{video_id}/emotion.png",
        "bundle_url": f"{BASE_PREFIX}/videos/{video_id}/bundle.zip",
        "original_video_url": f"{BASE_PREFIX}/videos/{video_id}/original",
    }


@app.post("/api/videos/batch")
@app.post(f"{BASE_PREFIX}/videos/batch")
async def upload_batch(files: list[UploadFile] = File(...)) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for file in files:
        video_id = uuid4().hex
        upload_path = UPLOAD_DIR / f"{video_id}_{file.filename}"
        upload_path.parent.mkdir(parents=True, exist_ok=True)
        create_video_record(video_id, file.filename, str(upload_path))
        try:
            with upload_path.open("wb") as f:
                f.write(await file.read())
        except Exception as exc:
            mark_video_failed(video_id, str(exc))
            continue
        _enqueue(video_id, file.filename, upload_path)
        items.append({"id": video_id, "task_id": video_id, "original_name": file.filename, "status": "queued"})
    return {"items": items}


@app.get("/api/videos")
@app.get(f"{BASE_PREFIX}/videos")
def list_all_videos() -> list[dict[str, Any]]:
    return list_videos()


@app.get(f"{BASE_PREFIX}/tasks/{{task_id}}")
def get_task(task_id: str) -> dict[str, Any]:
    video = get_video(task_id)
    if not video:
        raise HTTPException(status_code=404, detail="task not found")
    return {
        "task_id": task_id,
        "video_id": task_id,
        "status": video.get("status"),
        "current_stage": video.get("status"),
        "retry_count": video.get("retries", 0),
        "last_error": video.get("last_error"),
        "created_at": video.get("created_at"),
        "updated_at": video.get("updated_at"),
    }


@app.delete("/api/videos/{video_id}")
@app.delete(f"{BASE_PREFIX}/videos/{{video_id}}")
def delete_one_video(video_id: str) -> dict[str, Any]:
    if not delete_video(video_id):
        raise HTTPException(status_code=404, detail="Video not found")
    return {"ok": True, "id": video_id}


@app.delete("/api/videos")
@app.delete(f"{BASE_PREFIX}/videos")
def delete_videos_batch(body: DeleteVideosBody) -> dict[str, Any]:
    deleted: list[str] = []
    for video_id in body.video_ids:
        if delete_video(video_id):
            deleted.append(video_id)
    return {"ok": True, "deleted": deleted}


@app.get("/api/videos/{video_id}")
@app.get(f"{BASE_PREFIX}/videos/{{video_id}}")
def get_video_detail(video_id: str) -> JSONResponse:
    video = get_video(video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    report = None
    report_json_path = video.get("report_json_path")
    if report_json_path and Path(str(report_json_path)).exists():
        try:
            report = json.loads(Path(str(report_json_path)).read_text(encoding="utf-8"))
        except Exception:
            report = None
    if report is None and video.get("status") in {"failed", "done"}:
        report = build_placeholder_report(video_id, str(video.get("original_name", "")))
    return JSONResponse(
        {
            "video": video,
            "report": report,
            "report_markdown_url": f"{BASE_PREFIX}/videos/{video_id}/report.md",
            "report_json_url": f"{BASE_PREFIX}/videos/{video_id}/report.json",
            "report_txt_url": f"{BASE_PREFIX}/videos/{video_id}/report.txt",
            "emotion_png_url": f"{BASE_PREFIX}/videos/{video_id}/emotion.png",
            "bundle_url": f"{BASE_PREFIX}/videos/{video_id}/bundle.zip",
            "original_video_url": f"{BASE_PREFIX}/videos/{video_id}/original",
        }
    )


@app.get("/api/videos/{video_id}/report.md")
@app.get(f"{BASE_PREFIX}/videos/{{video_id}}/report.md")
def download_markdown(video_id: str) -> FileResponse:
    video = get_video(video_id)
    if not video or not video.get("report_md_path"):
        raise HTTPException(status_code=404, detail="Report not found")
    return FileResponse(path=str(video["report_md_path"]), filename=f"{video_id}.md")


@app.get("/api/videos/{video_id}/report.json")
@app.get(f"{BASE_PREFIX}/videos/{{video_id}}/report.json")
def download_json(video_id: str) -> FileResponse:
    video = get_video(video_id)
    if not video or not video.get("report_json_path"):
        raise HTTPException(status_code=404, detail="Report not found")
    return FileResponse(path=str(video["report_json_path"]), filename=f"{video_id}.json")


@app.get("/api/videos/{video_id}/report.txt")
@app.get(f"{BASE_PREFIX}/videos/{{video_id}}/report.txt")
def download_text(video_id: str) -> FileResponse:
    video = get_video(video_id)
    if not video or not video.get("report_txt_path"):
        raise HTTPException(status_code=404, detail="Report not found")
    return FileResponse(path=str(video["report_txt_path"]), filename=f"{video_id}.txt")


@app.get("/api/videos/{video_id}/emotion.png")
@app.get(f"{BASE_PREFIX}/videos/{{video_id}}/emotion.png")
def download_emotion_curve(video_id: str) -> FileResponse:
    video = get_video(video_id)
    if not video or not video.get("curve_path"):
        raise HTTPException(status_code=404, detail="Curve not found")
    return FileResponse(path=str(video["curve_path"]), filename=f"{video_id}.png")


@app.get("/api/videos/{video_id}/original")
@app.get(f"{BASE_PREFIX}/videos/{{video_id}}/original")
def download_original(video_id: str) -> FileResponse:
    video = get_video(video_id)
    if not video or not video.get("file_path"):
        raise HTTPException(status_code=404, detail="Video not found")
    return FileResponse(path=str(video["file_path"]), filename=Path(str(video["file_path"])).name)


@app.get("/api/videos/{video_id}/bundle.zip")
@app.get(f"{BASE_PREFIX}/videos/{{video_id}}/bundle.zip")
def download_bundle(video_id: str) -> FileResponse:
    video = get_video(video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    bundle_path = REPORT_DIR / f"{video_id}_bundle.zip"
    if not bundle_path.exists():
        import zipfile

        with zipfile.ZipFile(bundle_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for key in ["file_path", "report_md_path", "report_json_path", "report_txt_path", "curve_path"]:
                path = video.get(key)
                if path and Path(str(path)).exists():
                    zf.write(str(path), arcname=Path(str(path)).name)
    return FileResponse(path=bundle_path, filename=f"{video_id}_bundle.zip")


@app.post("/api/videos/{video_id}/pack")
@app.post(f"{BASE_PREFIX}/videos/{{video_id}}/pack")
def pack_video_bundle(video_id: str, request: PackBundleRequest | None = None) -> dict[str, Any]:
    video = get_video(video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    if video.get("status") != "done":
        raise HTTPException(status_code=400, detail="Video analysis not completed")
    output_dir = Path(request.output_dir) if request and request.output_dir else None
    bundle_path = pack_report_bundle(
        original_name=str(video.get("original_name", "video")),
        json_path=video.get("report_json_path"),
        md_path=video.get("report_md_path"),
        txt_path=video.get("report_txt_path"),
        curve_path=video.get("curve_path"),
        output_dir=output_dir,
    )
    if not bundle_path:
        raise HTTPException(status_code=500, detail="Failed to create bundle")
    return {"ok": True, "video_id": video_id, "bundle_path": str(bundle_path), "filename": bundle_path.name}


@app.post("/api/videos/pack-all")
@app.post(f"{BASE_PREFIX}/videos/pack-all")
def pack_all_videos(request: PackBundleRequest | None = None) -> dict[str, Any]:
    videos = list_videos()
    output_dir = Path(request.output_dir) if request and request.output_dir else None
    results: list[dict[str, Any]] = []
    for video in videos:
        if video.get("status") != "done":
            continue
        detail = get_video(str(video["id"]))
        if not detail:
            continue
        bundle_path = pack_report_bundle(
            original_name=str(detail.get("original_name", "video")),
            json_path=detail.get("report_json_path"),
            md_path=detail.get("report_md_path"),
            txt_path=detail.get("report_txt_path"),
            curve_path=detail.get("curve_path"),
            output_dir=output_dir,
        )
        if bundle_path:
            results.append(
                {"video_id": video["id"], "original_name": video.get("original_name"), "bundle_path": str(bundle_path)}
            )
    return {"ok": True, "packed_count": len(results), "results": results}


@app.get("/api/costs/daily")
@app.get(f"{BASE_PREFIX}/costs/daily")
def get_costs_daily() -> list[dict[str, Any]]:
    return get_daily_costs()


@app.get("/api/knowledge-base")
@app.get(f"{BASE_PREFIX}/knowledge-base")
def knowledge_base(query: str | None = None, day: str | None = None) -> list[dict[str, Any]]:
    return search_knowledge(query, day)


@app.post("/api/knowledge-base/retry")
@app.post(f"{BASE_PREFIX}/knowledge-base/retry")
def kb_retry_push() -> dict[str, Any]:
    """Retry all previously failed knowledge-engine pushes."""
    return retry_failed_kb_pushes()
