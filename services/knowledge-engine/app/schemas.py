from pydantic import BaseModel, Field

from app.config import settings


class KnowledgeBaseCreateRequest(BaseModel):
    name: str = Field(min_length=1)
    description: str = ""
    embedding_model: str = settings.embedding_model
    dimension: int = Field(default=1536, gt=0)


class IngestRequest(BaseModel):
    kb_id: str
    title: str = Field(min_length=1)
    text: str = Field(min_length=1)
    source_url: str | None = None


class QueryRequest(BaseModel):
    kb_id: str
    query: str
    top_k: int = Field(default=5, ge=1, le=100)


class QueryResult(BaseModel):
    id: str
    title: str
    content: str
    source: str
    score: float = 0.0


class DocumentDetail(BaseModel):
    id: str
    kb_id: str
    title: str
    source_url: str | None = None
    raw_text: str
