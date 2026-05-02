from __future__ import annotations

import json
import queue
import threading
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

import cv2
import httpx
from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse

from app.config import settings
from app.storage import (
    DATA_DIR,
    create_material,
    delete_material,
    get_material,
    list_material_units,
    list_materials,
    replace_material_clusters,
    replace_material_units,
    update_material_status,
    update_material_summary,
)

router = APIRouter(prefix="/api/v1/video-analysis/decompose", tags=["reverse-decompose"])

_JOB_QUEUE: "queue.Queue[dict[str, Any]]" = queue.Queue()
_WORKER_STARTED = False


def start_reverse_worker() -> None:
    global _WORKER_STARTED
    if _WORKER_STARTED:
        return
    _WORKER_STARTED = True
    thread = threading.Thread(target=_worker_loop, daemon=True, name="reverse-decompose-worker")
    thread.start()


def _worker_loop() -> None:
    while True:
        job = _JOB_QUEUE.get()
        try:
            _run_job(job)
        finally:
            _JOB_QUEUE.task_done()


def _enqueue(job: dict[str, Any]) -> None:
    _JOB_QUEUE.put(job)


def _safe_file_name(name: str) -> str:
    return name.replace("\\", "_").replace("/", "_")


def _save_upload(file: UploadFile, material_id: str) -> str:
    base_dir = DATA_DIR / "decompose" / material_id
    base_dir.mkdir(parents=True, exist_ok=True)
    target = base_dir / _safe_file_name(file.filename or f"file-{uuid4().hex}")
    with target.open("wb") as f:
        f.write(file.file.read())
    return str(target)


def _video_duration(path: str) -> float:
    cap = cv2.VideoCapture(path)
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 0
        frames = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
        if fps <= 0:
            return 3.0
        return max(0.1, float(frames / fps))
    finally:
        cap.release()


def _dominant_color_hex(path: str) -> str:
    img = cv2.imread(path)
    if img is None:
        return "#FFFFFF"
    small = cv2.resize(img, (32, 32))
    avg = small.mean(axis=(0, 1))
    b, g, r = [int(x) for x in avg]
    return f"#{r:02X}{g:02X}{b:02X}"


def _build_prompt_pack(fields: dict[str, Any], include_video: bool) -> dict[str, str]:
    subject = str(fields.get("subject", "电商产品")).strip()
    scene = str(fields.get("scene", "干净陈列场景")).strip()
    camera = str(fields.get("camera", "中近景")).strip()
    lighting = str(fields.get("lighting", "柔和自然光")).strip()
    mood = str(fields.get("mood", "可信温暖")).strip()
    style = str(fields.get("style", "写实")).strip()
    motion = str(fields.get("motion", "缓慢推镜")).strip()
    zh = f"{subject}，{scene}，{camera}，{lighting}，{style}风格，情绪{mood}"
    en = (
        f"subject: {subject}, scene: {scene}, camera: {camera}, lens: 50mm, lighting: {lighting}, "
        f"color palette: warm neutral, style: {style}, mood: {mood}, photorealistic"
    )
    pack: dict[str, str] = {"image_prompt_zh": zh, "image_prompt_en": en}
    if include_video:
        pack["video_prompt_zh"] = f"{zh}，镜头运动：{motion}"
        pack["video_prompt_en"] = f"{en}, camera movement: {motion}"
    return pack


def _call_knowledge_ingest(
    *,
    kb_id: str,
    title: str,
    text: str,
    source_url: str | None,
    metadata: dict[str, Any],
) -> str:
    payload = {
        "kb_id": kb_id,
        "title": title,
        "text": text,
        "source_url": source_url,
        "source_type": "reverse_storyboard",
        "metadata": metadata,
        "skip_chunking": True,
    }
    url = f"{settings.knowledge_engine_url}/api/v1/knowledge/ingest"
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
    return str((data.get("data") or {}).get("task_id") or "")


def _ingest_unit(material: dict[str, Any], unit: dict[str, Any]) -> list[str]:
    metadata_base = {
        "source_kind": "reverse_storyboard",
        "material_type": material["material_type"],
        "material_id": material["id"],
        "unit_index": unit["unit_index"],
        "unit_type": unit["unit_type"],
        "has_product": bool(unit["fields"].get("has_product", True)),
        "tags": ["爆款拆解", "调味品"],
    }
    semantic_text = "\n".join(
        [
            str(unit["fields"].get("visual_description", "")),
            str(unit["fields"].get("voiceover", "")),
            str(unit["fields"].get("on_screen_text", "")),
            str(unit["fields"].get("module_type", "")),
        ]
    ).strip()
    prompt = unit["prompt_pack"]
    prompt_text = "\n".join(
        [
            prompt.get("image_prompt_zh", ""),
            prompt.get("image_prompt_en", ""),
            prompt.get("video_prompt_zh", ""),
            prompt.get("video_prompt_en", ""),
        ]
    ).strip()
    task_ids = []
    task_ids.append(
        _call_knowledge_ingest(
            kb_id=str(material["target_kb_id"]),
            title=f"[爆款拆解] unit-{unit['unit_index']}-semantic",
            text=semantic_text,
            source_url=material.get("source_url"),
            metadata={**metadata_base, "chunk_kind": "semantic"},
        )
    )
    task_ids.append(
        _call_knowledge_ingest(
            kb_id=str(material["target_kb_id"]),
            title=f"[爆款拆解] unit-{unit['unit_index']}-prompt",
            text=prompt_text,
            source_url=material.get("source_url"),
            metadata={**metadata_base, "chunk_kind": "prompt_pack"},
        )
    )
    return task_ids


def _build_video_units(file_paths: list[str]) -> list[dict[str, Any]]:
    video_path = file_paths[0]
    duration = _video_duration(video_path)
    fields = {
        "shot_type": "中景",
        "camera_motion": "缓推",
        "lighting": "暖调自然光",
        "visual_description": "厨房场景下展示调味品与菜品特写，强调真实烹饪氛围",
        "voiceover": "突出产品工艺与口味层次的解说语句",
        "on_screen_text": "古法酿造180天",
        "has_product": True,
        "subject": "调味品产品特写",
        "scene": "厨房灶台与成品菜",
        "camera": "中景缓推",
        "mood": "温暖真实",
        "style": "写实电商短视频",
        "motion": "push-in",
    }
    return [
        {
            "unit_index": 1,
            "unit_type": "shot",
            "start_sec": 0.0,
            "end_sec": round(duration, 2),
            "image_index": None,
            "keyframe_paths": [],
            "fields": fields,
            "prompt_pack": _build_prompt_pack(fields, include_video=True),
            "chunk_ids": [],
        }
    ]


def _build_detail_units(file_paths: list[str]) -> tuple[list[dict[str, Any]], str]:
    module_cycle = ["hook", "pain_point", "usp", "ingredient", "scene", "promotion", "cta", "footer"]
    units: list[dict[str, Any]] = []
    for idx, _path in enumerate(file_paths, start=1):
        module = module_cycle[(idx - 1) % len(module_cycle)]
        fields = {
            "module_type": module,
            "layout": "图文版块布局",
            "texts": [{"role": "section_title", "content": f"{module} 模块"}],
            "visual_description": "电商详情页分段版块，文字与产品画面组合",
            "cta_strength": 8 if module in {"promotion", "cta"} else 0,
            "has_product": True,
            "subject": "电商详情页版块",
            "scene": "图文混排页面",
            "camera": "平视展示",
            "mood": "信息明确",
            "style": "电商详情页",
            "motion": "static",
        }
        units.append(
            {
                "unit_index": idx,
                "unit_type": module,
                "start_sec": None,
                "end_sec": None,
                "image_index": idx - 1,
                "keyframe_paths": [_path],
                "fields": fields,
                "prompt_pack": _build_prompt_pack(fields, include_video=False),
                "chunk_ids": [],
            }
        )
    narrative = "AIDA" if len(units) >= 4 else "痛点-方案-CTA"
    return units, narrative


def _build_main_image_units(file_paths: list[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    units: list[dict[str, Any]] = []
    for idx, path in enumerate(file_paths, start=1):
        color = _dominant_color_hex(path)
        fields = {
            "aspect_ratio": "3:4",
            "selling_point_text": "古法酿造180天",
            "price_badge": None,
            "product_subject_ratio": 0.6,
            "background_style": "纯白棚拍" if idx % 2 else "场景化",
            "hot_zone_layout": "左上文字+右下产品" if idx % 2 else "居中产品+下方价格",
            "dominant_color": color,
            "visual_description": "电商主图，产品主体突出，卖点文字清晰",
            "has_product": True,
            "subject": "调味品主图",
            "scene": "电商展示场景",
            "camera": "定机位",
            "mood": "可信专业",
            "style": "电商主图",
            "motion": "static",
        }
        units.append(
            {
                "unit_index": idx,
                "unit_type": "main_image",
                "start_sec": None,
                "end_sec": None,
                "image_index": idx - 1,
                "keyframe_paths": [path],
                "fields": fields,
                "prompt_pack": _build_prompt_pack(fields, include_video=False),
                "chunk_ids": [],
            }
        )
    clusters: list[dict[str, Any]] = []
    if len(units) >= 6:
        buckets: dict[str, list[int]] = {}
        for u in units:
            key = str(u["fields"].get("background_style", "其他"))
            buckets.setdefault(key, []).append(u["image_index"])
        for key, members in list(buckets.items())[:6]:
            clusters.append(
                {
                    "layout": key,
                    "member_count": len(members),
                    "members": members,
                    "prompt_template_zh": f"{key}主图风格，产品主体突出，中文卖点清晰",
                    "prompt_template_en": f"{key} style e-commerce hero image, product-focused composition",
                }
            )
    return units, clusters


def _run_job(job: dict[str, Any]) -> None:
    material_id = str(job["material_id"])
    started = time.time()
    try:
        update_material_status(material_id, status="running", phase="llm_unit", progress=0.2, progress_message="开始拆解")
        material = get_material(material_id)
        if not material:
            return
        material_type = material["material_type"]
        file_paths = material.get("file_paths") or []
        if isinstance(file_paths, str):
            file_paths = json.loads(file_paths)
        if material_type == "video":
            units = _build_video_units(file_paths)
            clusters: list[dict[str, Any]] = []
            narrative_model = None
            bgm = {
                "genre": "Lo-fi Kitchen",
                "tempo_bpm": 96,
                "emotion": "温暖治愈",
                "vocal": "纯音乐",
                "reference_keywords": ["calm", "cooking", "warm"],
            }
        elif material_type == "detail_page":
            units, narrative_model = _build_detail_units(file_paths)
            clusters = []
            bgm = None
        else:
            units, clusters = _build_main_image_units(file_paths)
            narrative_model = None
            bgm = None

        update_material_status(material_id, phase="ingest", progress=0.7, progress_message="写入知识库")
        for unit in units:
            task_ids = _ingest_unit(material, unit)
            unit["chunk_ids"] = task_ids
        replace_material_units(material_id, units)
        if clusters:
            for cluster in clusters:
                task_id = _call_knowledge_ingest(
                    kb_id=str(material["target_kb_id"]),
                    title="[爆款拆解] main-image-cluster",
                    text=json.dumps(cluster, ensure_ascii=False),
                    source_url=material.get("source_url"),
                    metadata={
                        "source_kind": "reverse_storyboard",
                        "material_type": "main_image",
                        "material_id": material_id,
                        "unit_index": 0,
                        "unit_type": "cluster",
                        "chunk_kind": "main_image_cluster",
                        "has_product": True,
                        "tags": ["爆款拆解", "主图聚类"],
                    },
                )
                cluster["chunk_id"] = task_id
            replace_material_clusters(material_id, str(material["target_kb_id"]), clusters)
        update_material_summary(
            material_id,
            unit_count=len(units),
            narrative_model=narrative_model,
            bgm_json=bgm,
        )
        update_material_status(
            material_id,
            status="completed",
            phase="completed",
            progress=1.0,
            progress_message="完成",
            duration_sec=round(time.time() - started, 2),
            error=None,
        )
    except Exception as exc:
        update_material_status(
            material_id,
            status="failed",
            phase="failed",
            progress=1.0,
            progress_message="失败",
            error=str(exc),
            retries_increment=True,
            duration_sec=round(time.time() - started, 2),
        )


@router.post("/video")
async def decompose_video(
    file: UploadFile = File(...),
    kb_id: str = Form(...),
    source_url: str | None = Form(None),
) -> dict[str, Any]:
    if not file.filename:
        raise HTTPException(status_code=400, detail="缺少视频文件")
    material_id = str(uuid4())
    path = _save_upload(file, material_id)
    create_material(
        material_id=material_id,
        material_type="video",
        title=file.filename,
        source_url=source_url,
        target_kb_id=kb_id,
        file_paths=[path],
    )
    _enqueue({"material_id": material_id})
    return {"material_id": material_id, "status": "queued"}


@router.post("/detail-page")
async def decompose_detail_page(
    files: list[UploadFile] = File(...),
    kb_id: str = Form(...),
    source_url: str | None = Form(None),
) -> dict[str, Any]:
    if not files:
        raise HTTPException(status_code=400, detail="至少上传一张图片")
    material_id = str(uuid4())
    paths = [_save_upload(f, material_id) for f in files]
    create_material(
        material_id=material_id,
        material_type="detail_page",
        title=f"detail-page-{len(paths)}",
        source_url=source_url,
        target_kb_id=kb_id,
        file_paths=paths,
    )
    _enqueue({"material_id": material_id})
    return {"material_id": material_id, "status": "queued"}


@router.post("/main-image")
async def decompose_main_image(
    files: list[UploadFile] = File(...),
    kb_id: str = Form(...),
    source_url: str | None = Form(None),
) -> dict[str, Any]:
    if not files:
        raise HTTPException(status_code=400, detail="至少上传一张图片")
    material_id = str(uuid4())
    paths = [_save_upload(f, material_id) for f in files]
    create_material(
        material_id=material_id,
        material_type="main_image",
        title=f"main-image-{len(paths)}",
        source_url=source_url,
        target_kb_id=kb_id,
        file_paths=paths,
    )
    _enqueue({"material_id": material_id})
    return {"material_id": material_id, "status": "queued"}


@router.get("")
def list_decompose(material_type: str | None = Query(default=None)) -> dict[str, Any]:
    return {"items": list_materials(material_type)}


@router.get("/{material_id}")
def get_decompose(material_id: str) -> dict[str, Any]:
    material = get_material(material_id)
    if not material:
        raise HTTPException(status_code=404, detail="material not found")
    units = list_material_units(material_id)
    return {"material": material, "units": units}


@router.post("/{material_id}/reingest")
def reingest(material_id: str) -> dict[str, Any]:
    material = get_material(material_id)
    if not material:
        raise HTTPException(status_code=404, detail="material not found")
    _enqueue({"material_id": material_id})
    update_material_status(material_id, status="queued", phase="queued", progress=0.01, progress_message="重新入库排队中")
    return {"ok": True}


@router.delete("/{material_id}")
def remove_material(material_id: str) -> dict[str, Any]:
    ok = delete_material(material_id)
    if not ok:
        raise HTTPException(status_code=404, detail="material not found")
    return {"ok": True}


@router.get("/stream/{material_id}")
def stream_material(material_id: str):
    def gen():
        while True:
            material = get_material(material_id)
            if not material:
                yield "event: error\ndata: {\"error\": \"material not found\"}\n\n"
                return
            payload = {
                "material_id": material_id,
                "status": material.get("status"),
                "phase": material.get("phase"),
                "progress": material.get("progress"),
                "message": material.get("progress_message"),
                "error": material.get("error"),
            }
            yield f"event: progress\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
            if material.get("status") in {"completed", "failed"}:
                return
            time.sleep(1)

    return StreamingResponse(gen(), media_type="text/event-stream")
