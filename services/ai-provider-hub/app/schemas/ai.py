from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


# ═══ Common ═══

class Message(BaseModel):
    role: Literal["system", "user", "assistant"] = "user"
    content: str | list[dict[str, Any]]


class TokenUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


# ═══ Chat ═══

class ChatRequest(BaseModel):
    messages: list[Message] = Field(default_factory=list, min_length=1)
    provider: str | None = None
    model: str | None = None
    temperature: float = 0.7
    max_tokens: int | None = None
    stream: bool = False


class ChatResponse(BaseModel):
    content: str
    provider: str
    model: str
    usage: TokenUsage


# ═══ Embedding ═══

class EmbeddingRequest(BaseModel):
    texts: list[str] = Field(min_length=1)
    provider: str | None = None
    model: str | None = None


class EmbeddingResponse(BaseModel):
    embeddings: list[list[float]]
    provider: str
    model: str
    usage: TokenUsage


# ═══ Image Generation ═══

class ImageGenerateRequest(BaseModel):
    prompt: str = Field(min_length=1)
    provider: str | None = None
    model: str | None = Field(default="gpt-image-1.5")
    size: str = "1024x1024"
    quality: str = "standard"
    n: int = Field(default=1, ge=1, le=4)


class ImageGenerateResponse(BaseModel):
    images: list[dict[str, str]]
    provider: str
    model: str
    usage: dict = Field(default_factory=dict)


# ═══ Video Generation (Seedance 2.0 multi-modal) ═══

class VideoContentItem(BaseModel):
    """Single content element for Seedance 2.0 multi-modal video generation."""
    type: Literal["text", "image_url", "video_url", "audio_url"]
    text: str | None = None
    image_url: dict[str, str] | None = None   # {"url": "..."}
    video_url: dict[str, str] | None = None   # {"url": "..."}
    audio_url: dict[str, str] | None = None   # {"url": "..."}
    role: str | None = None  # reference_image / reference_video / reference_audio / first_frame / last_frame


class VideoGenerateRequest(BaseModel):
    prompt: str = Field(default="", description="Text prompt (backward-compat; ignored if content is given)")
    provider: str | None = None
    model: str | None = None
    duration: int = Field(default=5, ge=4, le=15)
    aspect_ratio: str = Field(default="16:9", description="Alias for ratio (backward compat)")
    ratio: str | None = Field(default=None, description="Output ratio: 21:9, 16:9, 4:3, 1:1, 3:4, 9:16, adaptive")
    image_url: str | None = Field(default=None, description="Single reference image (backward-compat shorthand)")
    # Seedance 2.0 multi-modal fields
    content: list[VideoContentItem] | None = Field(default=None, description="Multi-modal content array")
    reference_images: list[str] | None = Field(default=None, description="Reference image URLs / asset IDs")
    reference_videos: list[str] | None = Field(default=None, description="Reference video URLs")
    reference_audios: list[str] | None = Field(default=None, description="Reference audio URLs")
    first_frame: str | None = Field(default=None, description="First frame image URL")
    last_frame: str | None = Field(default=None, description="Last frame image URL")
    generate_audio: bool = Field(default=False, description="Generate audio track")
    watermark: bool = Field(default=True, description="Include watermark")
    mode: Literal["generate", "edit", "extend"] = Field(default="generate")
    tools: list[dict[str, str]] | None = Field(default=None, description='e.g. [{"type": "web_search"}]')
    quality: Literal["standard", "fast"] = Field(default="standard", description="standard=2.0, fast=2.0-fast")

    @model_validator(mode="after")
    def ensure_prompt_or_content(self) -> "VideoGenerateRequest":
        if not self.content and not self.prompt:
            raise ValueError("Either 'prompt' or 'content' must be provided")
        return self

    def effective_ratio(self) -> str:
        return self.ratio or self.aspect_ratio or "16:9"


class VideoGenerateResponse(BaseModel):
    task_id: str
    status: str = "processing"
    estimated_seconds: int = 120
    provider: str | None = None
    model: str | None = None


class VideoStatusResponse(BaseModel):
    task_id: str
    status: str
    video_url: str | None = None
    duration: int | None = None
    provider: str | None = None
    error: str | None = None


# ═══ Multimodal Analysis ═══

class AnalyzeRequest(BaseModel):
    type: Literal["image", "video", "document"] = "image"
    content: str = Field(min_length=1)
    prompt: str = Field(default="Analyze this content")
    provider: str | None = None
    model: str | None = None


class AnalyzeResponse(BaseModel):
    analysis: str
    structured_data: dict = Field(default_factory=dict)
    provider: str
    model: str
    usage: TokenUsage = Field(default_factory=TokenUsage)
