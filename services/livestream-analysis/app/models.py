"""直播切片分析 — 数据模型"""

from pydantic import BaseModel, Field
from typing import Optional


class PersonScript(BaseModel):
    role: str = Field(description="角色: 主播/助播/嘉宾/模特")
    content: str = Field(description="该人物在此段的逐字稿")


class Segment(BaseModel):
    time_start: str = Field(description="开始时间 MM:SS")
    time_end: str = Field(description="结束时间 MM:SS")
    duration_seconds: int = Field(description="持续秒数")
    phase: str = Field(description="流程阶段")
    visual_description: str = Field(description="画面描述")
    background_elements: list[str] = Field(default_factory=list, description="背景元素：场景布局、道具、灯光、背景板等")
    overlay_elements: list[str] = Field(default_factory=list, description="贴片元素：浮窗、字幕条、价格标签、二维码、促销横幅等")
    person_count: int = Field(description="人物数量")
    person_roles: list[str] = Field(default_factory=list)
    scripts: dict[str, PersonScript] = Field(default_factory=dict)
    speech_pace: str = Field(description="语速评估")
    rhythm_notes: str = Field(default="")
    style_tags: list[str] = Field(default_factory=list)
    notes: Optional[str] = Field(default=None)


class PersonSummary(BaseModel):
    role: str
    description: str


class Summary(BaseModel):
    total_duration: str
    total_segments: int
    person_summary: list[PersonSummary] = Field(default_factory=list)
    phase_distribution: dict[str, int] = Field(default_factory=dict)
    overall_style: str = ""
    highlights: list[str] = Field(default_factory=list)
    improvements: list[str] = Field(default_factory=list)


class AnalysisResult(BaseModel):
    segments: list[Segment]
    summary: Summary


class VideoMetadata(BaseModel):
    path: str
    duration_seconds: float
    width: int = 0
    height: int = 0
    codec: str = ""
    has_audio: bool = True
    file_size_bytes: int = 0
    mime_type: str = "video/mp4"

    @property
    def duration_formatted(self) -> str:
        minutes = int(self.duration_seconds) // 60
        seconds = int(self.duration_seconds) % 60
        return f"{minutes:02d}:{seconds:02d}"

    @property
    def file_size_mb(self) -> float:
        return round(self.file_size_bytes / (1024 * 1024), 1)


class VideoSegment(BaseModel):
    path: str
    start_seconds: float
    end_seconds: float
    index: int
    total_segments: int

    @property
    def start_formatted(self) -> str:
        minutes = int(self.start_seconds) // 60
        seconds = int(self.start_seconds) % 60
        return f"{minutes:02d}:{seconds:02d}"

    @property
    def end_formatted(self) -> str:
        minutes = int(self.end_seconds) // 60
        seconds = int(self.end_seconds) % 60
        return f"{minutes:02d}:{seconds:02d}"


class FileInfo(BaseModel):
    name: str
    uri: str
    state: str
    mime_type: str = "video/mp4"
