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


def _ffprobe_path() -> str | None:
    custom = os.getenv("FFPROBE_PATH")
    if custom and Path(custom).exists():
        return custom
    found = shutil.which("ffprobe")
    if found:
        return found
    ffmpeg = _ffmpeg_path()
    if ffmpeg:
        probe = Path(ffmpeg).parent / ("ffprobe.exe" if os.name == "nt" else "ffprobe")
        if probe.exists():
            return str(probe)
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


def extract_video_metadata(video_path: Path) -> dict[str, object] | None:
    ffprobe = _ffprobe_path()
    if not ffprobe:
        return None
    try:
        result = subprocess.run(
            [
                ffprobe, "-v", "quiet", "-print_format", "json",
                "-show_format", "-show_streams", str(video_path),
            ],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return None
        import json as _json
        info = _json.loads(result.stdout)
        fmt = info.get("format", {})
        video_stream = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), {})
        audio_stream = next((s for s in info.get("streams", []) if s.get("codec_type") == "audio"), None)
        duration = float(fmt.get("duration", 0))
        width = int(video_stream.get("width", 0))
        height = int(video_stream.get("height", 0))
        fps_parts = video_stream.get("r_frame_rate", "0/1").split("/")
        fps = round(float(fps_parts[0]) / max(float(fps_parts[1]), 1), 2) if len(fps_parts) == 2 else 0
        bitrate = int(fmt.get("bit_rate", 0)) // 1000
        file_size_mb = round(float(fmt.get("size", 0)) / 1048576, 2)
        aspect = f"{width}:{height}"
        if width and height:
            from math import gcd
            g = gcd(width, height)
            aspect = f"{width // g}:{height // g}"
        return {
            "duration_sec": round(duration, 2),
            "resolution": f"{width}x{height}",
            "aspect_ratio": aspect,
            "fps": fps,
            "bitrate_kbps": bitrate,
            "file_size_mb": file_size_mb,
            "codec": video_stream.get("codec_name", ""),
            "has_audio": audio_stream is not None,
        }
    except Exception:
        return None


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


def extract_frames_smart(video_path: Path, work_dir: Path, duration_sec: float | None = None) -> list[Path]:
    """Adaptive frame extraction based on video duration."""
    ffmpeg = _ffmpeg_path()
    if not ffmpeg:
        return []
    if duration_sec is None or duration_sec <= 0:
        return extract_frames(video_path, work_dir)

    if duration_sec <= 15:
        fps_setting, max_frames = "fps=1", 15
    elif duration_sec <= 60:
        fps_setting, max_frames = "fps=0.5", 30
    else:
        fps_setting, max_frames = "fps=0.33", 40

    output_pattern = str(work_dir / "sframe_%04d.jpg")
    ok = _run_ffmpeg([
        ffmpeg, "-y", "-i", str(video_path),
        "-vf", fps_setting, "-frames:v", str(max_frames), output_pattern,
    ])
    if not ok:
        return extract_frames(video_path, work_dir)
    frames = sorted(work_dir.glob("sframe_*.jpg"))
    return frames if frames else extract_frames(video_path, work_dir)


def transcribe_audio(audio_or_video: Path) -> str | None:
    result = transcribe_audio_with_timestamps(audio_or_video)
    if result:
        return result.get("full_text")
    return None


def transcribe_audio_with_timestamps(audio_or_video: Path) -> dict[str, object] | None:
    try:
        from faster_whisper import WhisperModel

        model = WhisperModel(os.getenv("ASR_MODEL", "base"), device="cpu", compute_type="int8")
        segments, _ = model.transcribe(str(audio_or_video), language="zh")
        result_segments = []
        for seg in segments:
            if seg.text and seg.text.strip():
                result_segments.append({
                    "start": round(seg.start, 2),
                    "end": round(seg.end, 2),
                    "text": seg.text.strip(),
                })
        if result_segments:
            return {
                "full_text": " ".join(s["text"] for s in result_segments),
                "segments": result_segments,
            }
    except Exception:
        pass

    try:
        import whisper

        model = whisper.load_model(os.getenv("ASR_MODEL", "base"))
        result = model.transcribe(str(audio_or_video))
        text = result.get("text", "").strip()
        w_segments = result.get("segments", [])
        ts_segments = []
        for ws in w_segments:
            if isinstance(ws, dict) and ws.get("text", "").strip():
                ts_segments.append({
                    "start": round(ws.get("start", 0), 2),
                    "end": round(ws.get("end", 0), 2),
                    "text": ws["text"].strip(),
                })
        return {"full_text": text, "segments": ts_segments} if text else None
    except Exception:
        return None


def detect_scene_changes(video_path: Path, work_dir: Path, threshold: float = 30.0) -> dict[str, object] | None:
    ffmpeg = _ffmpeg_path()
    if not ffmpeg:
        return None
    try:
        result = subprocess.run(
            [
                ffmpeg, "-i", str(video_path),
                "-vf", f"select='gt(scene,0.3)',showinfo",
                "-vsync", "vfr", "-f", "null", "-",
            ],
            capture_output=True, text=True, timeout=120,
        )
        import re
        changes: list[dict[str, object]] = []
        for match in re.finditer(r"pts_time:(\d+\.?\d*)", result.stderr):
            t = float(match.group(1))
            changes.append({"time_sec": round(t, 2), "type": "cut"})

        if not changes:
            return {"scene_changes": [], "total_cuts": 0, "avg_shot_duration": 0, "min_shot_duration": 0, "max_shot_duration": 0}

        durations = []
        for i in range(1, len(changes)):
            durations.append(changes[i]["time_sec"] - changes[i - 1]["time_sec"])

        return {
            "scene_changes": changes[:50],
            "total_cuts": len(changes),
            "avg_shot_duration": round(sum(durations) / len(durations), 2) if durations else 0,
            "min_shot_duration": round(min(durations), 2) if durations else 0,
            "max_shot_duration": round(max(durations), 2) if durations else 0,
        }
    except Exception:
        return None


def compute_audio_features(audio_path: Path | None) -> dict[str, float] | None:
    if not audio_path:
        return None
    try:
        import librosa

        y, sr = librosa.load(str(audio_path), sr=22050)
        tempo, beats = librosa.beat.beat_track(y=y, sr=sr)
        return {"tempo_bpm": float(tempo), "beat_count": float(len(beats))}
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


# ---------------------------------------------------------------------------
# 人像分析辅助函数
# ---------------------------------------------------------------------------

def _classify_color_tone(mean_h: float) -> str:
    if mean_h <= 25 or mean_h >= 160:
        return "暖色"
    if 25 < mean_h <= 95:
        return "冷色"
    return "中性"


def _classify_saturation(mean_s: float) -> str:
    if mean_s >= 130:
        return "高饱和"
    if mean_s >= 70:
        return "中饱和"
    return "低饱和"


def _classify_brightness(mean_v: float) -> str:
    if mean_v >= 170:
        return "高亮"
    if mean_v >= 95:
        return "中等亮度"
    return "偏暗"


def _classify_motion(score: float) -> str:
    if score >= 12:
        return "动作丰富"
    if score >= 5:
        return "动作适中"
    return "动作克制"


def _classify_clarity(score: float) -> str:
    if score >= 150:
        return "清晰"
    if score >= 80:
        return "一般"
    return "偏模糊"


def _normalize_gender(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return "男性" if int(value) == 1 else "女性"
    text = str(value).strip().lower()
    if text in {"男", "男性"}:
        return "男性"
    if text in {"女", "女性"}:
        return "女性"
    if text in {"m", "male", "man", "masculine"} or text.startswith("m"):
        return "男性"
    if text in {"f", "female", "woman", "feminine"} or text.startswith("f"):
        return "女性"
    return None


def _normalize_emotion(value: str | None) -> str | None:
    if not value:
        return None
    mapping = {
        "happy": "愉悦",
        "sad": "低落",
        "neutral": "平静",
        "angry": "愤怒",
        "fear": "紧张",
        "surprise": "惊讶",
        "disgust": "厌恶",
    }
    key = str(value).strip().lower()
    return mapping.get(key, None)


def _classify_pose_energy(score: float, confidence: float) -> str | None:
    if confidence < 0.4:
        return None
    if score >= 0.55:
        return "动作丰富"
    if score >= 0.4:
        return "动作适中"
    return "动作克制"


def _analyze_pose(image: object) -> dict[str, float] | None:
    try:
        import cv2
        import mediapipe as mp
    except Exception:
        return None

    mp_pose = mp.solutions.pose
    with mp_pose.Pose(static_image_mode=True, model_complexity=1, min_detection_confidence=0.5) as pose:
        result = pose.process(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))

    if not result.pose_landmarks:
        return None

    landmarks = result.pose_landmarks.landmark
    idx = mp_pose.PoseLandmark
    points = [idx.LEFT_WRIST, idx.RIGHT_WRIST, idx.LEFT_ANKLE, idx.RIGHT_ANKLE]
    hips = [idx.LEFT_HIP, idx.RIGHT_HIP]
    shoulders = [idx.LEFT_SHOULDER, idx.RIGHT_SHOULDER]

    def _get_point(item):
        point = landmarks[item]
        return point.x, point.y, point.visibility

    hip_x = sum(_get_point(h)[0] for h in hips) / len(hips)
    hip_y = sum(_get_point(h)[1] for h in hips) / len(hips)

    distances = []
    visibilities = []
    for point in points + shoulders + hips:
        x, y, v = _get_point(point)
        visibilities.append(v)
        distances.append(((x - hip_x) ** 2 + (y - hip_y) ** 2) ** 0.5)

    pose_energy = sum(distances) / len(distances)
    pose_confidence = sum(visibilities) / len(visibilities)
    return {"pose_energy": float(pose_energy), "pose_confidence": float(pose_confidence)}


def _analyze_face_with_insightface(image: object) -> dict[str, object] | None:
    try:
        from insightface.app import FaceAnalysis
    except Exception:
        return None

    try:
        app = FaceAnalysis(
            name=os.getenv("INSIGHTFACE_MODEL", "buffalo_l"),
            providers=["CPUExecutionProvider"],
        )
        app.prepare(ctx_id=0, det_size=(640, 640))
        faces = app.get(image)
    except Exception:
        return None

    if not faces:
        return None

    def _face_area(face) -> float:
        x1, y1, x2, y2 = [float(v) for v in face.bbox]
        return max(0.0, (x2 - x1) * (y2 - y1))

    face = max(faces, key=_face_area)
    h, w = image.shape[:2]
    face_area_ratio = _face_area(face) / float(w * h)
    return {
        "age": getattr(face, "age", None),
        "gender": _normalize_gender(getattr(face, "sex", None)),
        "emotion": None,
        "face_area_ratio": face_area_ratio,
        "source": "insightface",
    }


def _analyze_face_with_deepface(image: object) -> dict[str, object] | None:
    try:
        from deepface import DeepFace
    except Exception:
        return None

    try:
        result = DeepFace.analyze(
            img_path=image,
            actions=["age", "gender", "emotion"],
            enforce_detection=False,
        )
    except Exception:
        return None

    if isinstance(result, list):
        result = result[0] if result else {}

    region = result.get("region") or {}
    w, h = region.get("w"), region.get("h")
    image_h, image_w = image.shape[:2]
    face_area_ratio = None
    if w and h:
        face_area_ratio = float(w * h) / float(image_w * image_h)

    gender = result.get("dominant_gender")
    if not gender:
        raw_gender = result.get("gender")
        if isinstance(raw_gender, dict) and raw_gender:
            gender = max(raw_gender.items(), key=lambda item: item[1])[0]
        else:
            gender = raw_gender
    emotion = result.get("dominant_emotion")
    return {
        "age": result.get("age"),
        "gender": _normalize_gender(gender),
        "emotion": emotion,
        "face_area_ratio": face_area_ratio,
        "source": "deepface",
    }


def extract_persona_details(frames: list[Path]) -> dict[str, object] | None:
    try:
        import cv2
    except Exception:
        return None

    if not frames:
        return None

    try:
        face_cascade = cv2.CascadeClassifier(
            f"{cv2.data.haarcascades}haarcascade_frontalface_default.xml"
        )
        if face_cascade.empty():
            face_cascade = None
    except Exception:
        face_cascade = None
    try:
        smile_cascade = cv2.CascadeClassifier(f"{cv2.data.haarcascades}haarcascade_smile.xml")
        if smile_cascade.empty():
            smile_cascade = None
    except Exception:
        smile_cascade = None

    images: list[tuple[Path, object]] = []
    face_frames = 0
    face_area_ratios: list[float] = []
    smile_hits = 0
    blur_scores: list[float] = []
    hsv_samples: list[list[float]] = []
    motion_scores: list[float] = []
    prev_gray = None
    best_face_image = None
    best_face_ratio = 0.0

    for frame_path in frames[:5]:
        try:
            image = cv2.imread(str(frame_path))
            if image is None:
                continue
            images.append((frame_path, image))
            height, width = image.shape[:2]
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

            blur_scores.append(float(cv2.Laplacian(gray, cv2.CV_64F).var()))
            hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
            mean_h, mean_s, mean_v, _ = cv2.mean(hsv)
            hsv_samples.append([mean_h, mean_s, mean_v])

            if prev_gray is not None:
                diff = cv2.absdiff(prev_gray, gray)
                motion_scores.append(float(diff.mean()))
            prev_gray = gray

            if face_cascade:
                faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=3)
                if len(faces) > 0:
                    face_frames += 1
                    x, y, w, h = faces[0]
                    face_ratio = (w * h) / float(width * height)
                    face_area_ratios.append(face_ratio)
                    if smile_cascade:
                        roi_gray = gray[y : y + h, x : x + w]
                        smiles = smile_cascade.detectMultiScale(
                            roi_gray, scaleFactor=1.7, minNeighbors=20
                        )
                        if len(smiles) > 0:
                            smile_hits += 1
                    if face_ratio > best_face_ratio:
                        best_face_ratio = face_ratio
                        best_face_image = image
        except Exception:
            continue

    if not hsv_samples or not images:
        return None

    avg_h = sum(item[0] for item in hsv_samples) / len(hsv_samples)
    avg_s = sum(item[1] for item in hsv_samples) / len(hsv_samples)
    avg_v = sum(item[2] for item in hsv_samples) / len(hsv_samples)
    avg_blur = sum(blur_scores) / len(blur_scores) if blur_scores else 0.0
    avg_motion = sum(motion_scores) / len(motion_scores) if motion_scores else 0.0

    tone = _classify_color_tone(avg_h)
    saturation = _classify_saturation(avg_s)
    brightness = _classify_brightness(avg_v)

    face_attr = None
    face_image = best_face_image or images[0][1]
    face_attr = _analyze_face_with_insightface(face_image)
    if not face_attr:
        face_attr = _analyze_face_with_deepface(face_image)

    face_ratio = None
    if face_area_ratios:
        face_ratio = sum(face_area_ratios) / len(face_area_ratios)
    elif face_attr and face_attr.get("face_area_ratio"):
        face_ratio = float(face_attr["face_area_ratio"])

    smile_ratio = 0.0
    if face_ratio is not None:
        if face_ratio >= 0.12:
            face_size = "特写"
        elif face_ratio >= 0.05:
            face_size = "中景"
        else:
            face_size = "远景"
        clarity = _classify_clarity(avg_blur)
        appearance_parts = [f"{face_size}画面，人像{clarity}"]
    else:
        appearance_parts = ["人像不清晰或未检测到"]

    gender_label = _normalize_gender(face_attr.get("gender")) if face_attr else None
    age_value = None
    if face_attr and face_attr.get("age") is not None:
        try:
            age_value = int(round(float(face_attr["age"])))
        except Exception:
            age_value = None
    if gender_label:
        appearance_parts.append(gender_label)
    if age_value is not None:
        appearance_parts.append(f"约{age_value}岁")
    appearance = "，".join(appearance_parts)

    emotion_label = _normalize_emotion(face_attr.get("emotion")) if face_attr else None

    if emotion_label:
        micro_expression = f"情绪倾向：{emotion_label}"
    elif face_frames > 0:
        smile_ratio = smile_hits / float(face_frames)
        if smile_ratio >= 0.6:
            micro_expression = "微笑明显"
        elif smile_ratio >= 0.2:
            micro_expression = "轻微表情变化"
        else:
            micro_expression = "表情平稳"
    else:
        micro_expression = "无法识别"

    pose_attr = _analyze_pose(face_image)
    pose_energy = pose_attr.get("pose_energy") if pose_attr else None
    pose_confidence = pose_attr.get("pose_confidence") if pose_attr else 0.0
    pose_label = None
    if pose_energy is not None:
        pose_label = _classify_pose_energy(float(pose_energy), float(pose_confidence))

    body_language = pose_label or _classify_motion(avg_motion)
    outfit = f"{tone}/{saturation}/{brightness}"

    signals: dict[str, object] = {
        "face_frames": face_frames,
        "smile_ratio": round(smile_ratio, 2),
        "motion_score": round(avg_motion, 2),
        "clarity_score": round(avg_blur, 1),
    }
    if face_attr:
        signals.update(
            {
                "age_estimate": age_value,
                "gender": gender_label,
                "emotion": emotion_label,
                "face_model": face_attr.get("source"),
                "face_area_ratio": round(face_ratio, 3) if face_ratio is not None else None,
            }
        )
    if pose_energy is not None:
        signals.update(
            {
                "pose_energy": round(float(pose_energy), 3),
                "pose_confidence": round(float(pose_confidence), 2),
            }
        )

    return {
        "appearance": appearance,
        "outfit": f"穿搭色系：{outfit}",
        "micro_expression": micro_expression,
        "body_language": body_language,
        "signals": signals,
    }


def build_analysis_inputs(video_path: Path) -> dict[str, object]:
    inputs: dict[str, object] = {}
    with tempfile.TemporaryDirectory() as tmp_dir:
        work_dir = Path(tmp_dir)

        video_meta = extract_video_metadata(video_path)
        if video_meta:
            inputs["video_metadata"] = video_meta

        duration_sec = video_meta.get("duration_sec") if video_meta else None

        audio_path = extract_audio(video_path, work_dir)

        if duration_sec and isinstance(duration_sec, (int, float)):
            frames = extract_frames_smart(video_path, work_dir, float(duration_sec))
        else:
            frames = extract_frames(video_path, work_dir)

        asr_result = transcribe_audio_with_timestamps(audio_path or video_path)
        if asr_result:
            inputs["asr_text"] = asr_result.get("full_text", "")
            segments = asr_result.get("segments", [])
            if segments:
                inputs["asr_segments"] = segments
        else:
            asr_text = transcribe_audio(audio_path or video_path)
            if asr_text:
                inputs["asr_text"] = asr_text

        ocr_text = extract_ocr(frames)
        if ocr_text:
            inputs["ocr_text"] = ocr_text

        audio_features = compute_audio_features(audio_path)
        if audio_features:
            inputs["audio_features"] = audio_features

        try:
            persona_detail = extract_persona_details(frames)
            if persona_detail:
                inputs["persona_detail"] = persona_detail
        except Exception:
            pass

        scene_data = detect_scene_changes(video_path, work_dir)
        if scene_data:
            inputs["scene_changes"] = scene_data

        ffmpeg_path = _ffmpeg_path()
        inputs["ffmpeg_path"] = ffmpeg_path
        inputs["ffmpeg_available"] = ffmpeg_path is not None
    return inputs
