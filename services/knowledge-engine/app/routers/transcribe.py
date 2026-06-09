"""本地语音转文字（桌面输入框口述 → 文字）。

faster-whisper · CPU · medium · 中文 · **离线不走云**（模型首次从 HF 下载后本地跑）。
桌面录音（MediaRecorder webm/opus）→ IPC → main → POST 本端点 → faster-whisper 转 → 返文字填输入框。

口径/约束：
- device=cpu, compute_type=int8（无 GPU 也能跑；medium 中文/专有名词更准，代价是慢几倍）。
- 模型懒加载（首次调用才 load + 下载 ~1.5GB），之后常驻内存；用 WHISPER_MODEL env 可改大小。
- 转写是 CPU 阻塞操作 → 走 run_in_threadpool，不堵 FastAPI 事件循环。
- 国内首次下模型慢/被墙：给 KE 容器设 `HF_ENDPOINT=https://hf-mirror.com`。
- PyAV(av) 内置 ffmpeg 解 webm/opus，无需系统 ffmpeg。
"""
from __future__ import annotations

import logging
import os
import tempfile

from fastapi import APIRouter, File, UploadFile
from fastapi.concurrency import run_in_threadpool

logger = logging.getLogger(__name__)

transcribe_router = APIRouter(prefix="/api/v1", tags=["transcribe"])

_MODEL_SIZE = os.environ.get("WHISPER_MODEL", "medium")
_model = None  # 懒加载单例


def _get_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel  # 延迟 import，未装/未用时不影响 KE 启动
        logger.info("加载 faster-whisper 模型 size=%s device=cpu compute=int8（首次会下载 ~1.5GB）", _MODEL_SIZE)
        _model = WhisperModel(_MODEL_SIZE, device="cpu", compute_type="int8")
    return _model


def _transcribe_file(path: str, language: str | None) -> dict:
    """阻塞转写（在 threadpool 跑）。vad_filter 去静音、beam_size=5 提准。"""
    model = _get_model()
    segments, info = model.transcribe(
        path, language=language or None, vad_filter=True, beam_size=5,
    )
    text = "".join(seg.text for seg in segments).strip()
    return {"text": text, "language": info.language, "duration": round(info.duration, 2)}


@transcribe_router.post("/transcribe")
async def transcribe(audio: UploadFile = File(...), language: str = "zh") -> dict:
    """本地转写：上传音频（webm/opus/wav…）→ {ok, text, language, duration}。

    language 默认 'zh'（中文）；传空走自动检测。失败 fail-open 返 {ok:false,error}（前端不崩、提示老板手打）。
    """
    data = await audio.read()
    if not data:
        return {"ok": False, "error": "empty_audio"}
    suffix = os.path.splitext(audio.filename or "")[1] or ".webm"
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    try:
        tmp.write(data)
        tmp.flush()
        tmp.close()
        result = await run_in_threadpool(_transcribe_file, tmp.name, language)
        logger.info("transcribe ok: %d 字 / %.1fs 音频", len(result["text"]), result.get("duration") or 0)
        return {"ok": True, **result}
    except Exception as exc:  # noqa: BLE001
        logger.exception("transcribe 失败")
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    finally:
        try:
            os.unlink(tmp.name)
        except Exception:  # noqa: BLE001
            pass
