from typing import Any, Literal

from pydantic import BaseModel, Field


class Message(BaseModel):
    role: Literal["system", "user", "assistant"] = "user"
    content: str | list[dict[str, Any]]


class TokenUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatResponse(BaseModel):
    content: str
    provider: str
    model: str
    usage: TokenUsage


class ChatRequest(BaseModel):
    messages: list[Message] = Field(default_factory=list, min_length=1)
    provider: str | None = None
    model: str | None = None
    temperature: float = 0.7
    max_tokens: int | None = None
    stream: bool = False


class EmbeddingRequest(BaseModel):
    texts: list[str] = Field(min_length=1)
    provider: str | None = None
    model: str | None = None


class EmbeddingResponse(BaseModel):
    embeddings: list[list[float]]
    provider: str
    model: str
    usage: TokenUsage

