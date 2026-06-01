from __future__ import annotations
from pydantic import BaseModel, Field


class FetchRequest(BaseModel):
    platform: str = Field(..., description="yuntu|compass|doudian")
    endpoint: str = Field(..., description="目录 key")
    params: dict | None = None
    body: dict | None = None


class BatchFetchRequest(BaseModel):
    requests: list[FetchRequest]


class FetchResult(BaseModel):
    endpoint_key: str
    platform: str | None = None
    verdict: str
    status: int | None = None
    code: object | None = None
    has_data: bool = False
    fields: dict = {}
    url: str | None = None
    elapsed_ms: int | None = None
    attempts: int | None = None
    error: str | None = None
    hint: str | None = None
