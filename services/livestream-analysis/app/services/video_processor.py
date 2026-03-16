"""视频预处理 — ffprobe 元数据 + ffmpeg 分片"""

import json
import logging
import subprocess
from pathlib import Path

from app.models import VideoMetadata, VideoSegment

logger = logging.getLogger("livestream-analysis")


class VideoProcessError(Exception):
    pass


class VideoProcessor:
    SUPPORTED_EXTENSIONS = {".mp4", ".mov"}

    def get_metadata(self, video_path: str) -> VideoMetadata:
        path = Path(video_path)
        if not path.exists():
            raise FileNotFoundError(f"视频文件不存在: {video_path}")
        if path.suffix.lower() not in self.SUPPORTED_EXTENSIONS:
            raise VideoProcessError(f"不支持的视频格式: {path.suffix}")

        file_size = path.stat().st_size
        try:
            cmd = ["ffprobe", "-v", "quiet", "-print_format", "json",
                   "-show_format", "-show_streams", str(path)]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode != 0:
                raise VideoProcessError(f"ffprobe 执行失败: {result.stderr}")
            probe = json.loads(result.stdout)
        except FileNotFoundError:
            logger.warning("未检测到 ffprobe，使用基础文件信息")
            return VideoMetadata(path=str(path), duration_seconds=0, file_size_bytes=file_size)
        except subprocess.TimeoutExpired:
            raise VideoProcessError("ffprobe 执行超时")

        duration = float(probe.get("format", {}).get("duration", 0))
        width, height, codec, has_audio = 0, 0, "", False
        for stream in probe.get("streams", []):
            if stream.get("codec_type") == "video":
                width = int(stream.get("width", 0))
                height = int(stream.get("height", 0))
                codec = stream.get("codec_name", "")
            elif stream.get("codec_type") == "audio":
                has_audio = True

        mime = "video/quicktime" if path.suffix.lower() == ".mov" else "video/mp4"
        return VideoMetadata(path=str(path), duration_seconds=duration, width=width, height=height,
                             codec=codec, has_audio=has_audio, file_size_bytes=file_size, mime_type=mime)

    def needs_split(self, metadata: VideoMetadata, segment_minutes: int = 10) -> bool:
        return metadata.duration_seconds > segment_minutes * 60 * 3

    def split_video(self, video_path: str, segment_minutes: int = 10) -> list[VideoSegment]:
        path = Path(video_path)
        metadata = self.get_metadata(video_path)
        total = metadata.duration_seconds
        seg_sec = segment_minutes * 60

        if total <= seg_sec:
            return [VideoSegment(path=str(path), start_seconds=0, end_seconds=total,
                                 index=0, total_segments=1)]
        output_dir = path.parent / f"{path.stem}_segments"
        output_dir.mkdir(exist_ok=True)

        n = int(total // seg_sec) + (1 if total % seg_sec > 0 else 0)
        segments = []
        for i in range(n):
            start = i * seg_sec
            end = min(start + seg_sec, total)
            out = output_dir / f"{path.stem}_part{i+1:02d}{path.suffix}"
            cmd = ["ffmpeg", "-y", "-i", str(path), "-ss", str(start), "-t", str(end - start),
                   "-c", "copy", "-avoid_negative_ts", "make_zero", str(out)]
            logger.info("分片 %d/%d: %.0fs ~ %.0fs", i + 1, n, start, end)
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if result.returncode != 0:
                raise VideoProcessError(f"ffmpeg 分片失败: {result.stderr[:500]}")
            segments.append(VideoSegment(path=str(out), start_seconds=start, end_seconds=end,
                                         index=i, total_segments=n))
        return segments

    def cleanup_segments(self, segments: list[VideoSegment]) -> None:
        for seg in segments:
            try:
                p = Path(seg.path)
                if p.exists():
                    p.unlink()
                parent = p.parent
                if parent.exists() and not any(parent.iterdir()):
                    parent.rmdir()
            except Exception as e:
                logger.warning("清理临时文件失败: %s", e)
