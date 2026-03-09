from typing import Any, Literal

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"] = "user"
    content: str | list[dict[str, Any]]


class ChatCompletionRequest(BaseModel):
    model: str
    messages: list[ChatMessage]
    stream: bool = False
    temperature: float = 0.7
    max_tokens: int | None = None


class EmbeddingRequest(BaseModel):
    model: str
    input: str | list[str]


class EmbeddingItem(BaseModel):
    object: str = "embedding"
    index: int
    embedding: list[float] = Field(default_factory=list)
