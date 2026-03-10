from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def _ffmpeg_path() -> str | None:
    custom = os.getenv("FFMPEG_PATH")
    if custom:
        custom_path = Path(custom)
        if custom_path.exists():
            return str(custom_path)

    found = shutil.which("ffmpeg")
    if found:
        return found
    return None


def _run_ffmpeg(args: list[str]) -> bool:
    try:
        subprocess.run(args, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False


def extract_audio(video_path: Path, work_dir: Path) -> Path | None:
    ffmpeg = _ffmpeg_path()
    if not ffmpeg:
        return None
    output = work_dir / "audio.wav"
    ok = _run_ffmpeg(
        [
            ffmpeg,
            "-y",
            "-i",
            str(video_path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            str(output),
        ]
    )
    return output if ok and output.exists() else None


def extract_frames(video_path: Path, work_dir: Path, max_frames: int = 5) -> list[Path]:
    ffmpeg = _ffmpeg_path()
    if not ffmpeg:
        return []
    output_pattern = str(work_dir / "frame_%02d.jpg")
    ok = _run_ffmpeg(
        [
            ffmpeg,
            "-y",
            "-i",
            str(video_path),
            "-vf",
            "fps=1",
            "-frames:v",
            str(max_frames),
            output_pattern,
        ]
    )
    if not ok:
        return []
    return sorted(work_dir.glob("frame_*.jpg"))


def transcribe_audio(audio_or_video: Path) -> str | None:
    try:
        from faster_whisper import WhisperModel

        model = WhisperModel(os.getenv("ASR_MODEL", "base"), device="cpu", compute_type="int8")
        segments, _ = model.transcribe(str(audio_or_video), language="zh")
        return " ".join(segment.text.strip() for segment in segments if segment.text)
    except Exception:
        return None


def extract_ocr(frames: list[Path]) -> str | None:
    if not frames:
        return None
    try:
        from paddleocr import PaddleOCR

        ocr = PaddleOCR(use_angle_cls=True, lang="ch")
        texts: list[str] = []
        for frame in frames[:5]:
            result = ocr.ocr(str(frame), cls=True)
            for line in result or []:
                for item in line:
                    if isinstance(item, list) and len(item) > 1:
                        texts.append(str(item[1][0]))
        return " ".join(t for t in texts if t)
    except Exception:
        return None


def build_analysis_inputs(video_path: Path) -> dict[str, object]:
    inputs: dict[str, object] = {}
    with tempfile.TemporaryDirectory() as tmp_dir:
        work_dir = Path(tmp_dir)
        audio_path = extract_audio(video_path, work_dir)
        frames = extract_frames(video_path, work_dir)

        asr_text = transcribe_audio(audio_path or video_path)
        if asr_text:
            inputs["asr_text"] = asr_text

        ocr_text = extract_ocr(frames)
        if ocr_text:
            inputs["ocr_text"] = ocr_text

        ffmpeg_path = _ffmpeg_path()
        inputs["ffmpeg_path"] = ffmpeg_path
        inputs["ffmpeg_available"] = ffmpeg_path is not None
    return inputs
