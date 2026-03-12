from typing import Any, Literal

from pydantic import BaseModel, Field


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
    model: str | None = Field(default="dall-e-3")
    size: str = "1024x1024"
    quality: str = "standard"
    n: int = Field(default=1, ge=1, le=4)


class ImageGenerateResponse(BaseModel):
    images: list[dict[str, str]]
    provider: str
    model: str
    usage: dict = Field(default_factory=dict)


# ═══ Video Generation ═══

class VideoGenerateRequest(BaseModel):
    prompt: str = Field(min_length=1)
    provider: str | None = None
    model: str | None = None
    duration: int = Field(default=4, ge=1, le=30)
    aspect_ratio: str = "16:9"
    image_url: str | None = None


class VideoGenerateResponse(BaseModel):
    task_id: str
    status: str = "processing"
    estimated_seconds: int = 120


class VideoStatusResponse(BaseModel):
    task_id: str
    status: str
    video_url: str | None = None
    duration: int | None = None


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
