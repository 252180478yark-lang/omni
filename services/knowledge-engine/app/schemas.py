from pydantic import BaseModel, Field


# ═══ Knowledge Base ═══

class KnowledgeBaseCreateRequest(BaseModel):
    name: str = Field(min_length=1)
    description: str = ""
    embedding_provider: str | None = None
    embedding_model: str | None = None
    dimension: int | None = Field(default=None, gt=0)


# ═══ Ingestion ═══

class IngestRequest(BaseModel):
    kb_id: str
    title: str = Field(min_length=1)
    text: str = Field(min_length=1)
    source_url: str | None = None
    source_type: str = "manual"


# ═══ Query / Search ═══

class QueryRequest(BaseModel):
    kb_id: str
    query: str
    top_k: int = Field(default=5, ge=1, le=100)


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    kb_id: str | None = None
    top_k: int = Field(default=5, ge=1, le=100)
    score_threshold: float = Field(default=0.0, ge=0.0, le=1.0)
    search_type: str = Field(default="hybrid", pattern="^(vector|fulltext|hybrid)$")
    filter_source_type: str | None = None
    filter_tags: list[str] | None = None


# ═══ RAG ═══

class RAGRequest(BaseModel):
    kb_id: str = ""
    kb_ids: list[str] | None = None
    query: str = Field(min_length=1)
    top_k: int = Field(default=10, ge=1, le=50)
    model: str | None = None
    provider: str | None = None
    stream: bool = False
    session_id: str | None = None

    def resolved_kb_ids(self) -> list[str]:
        """Return deduplicated list of KB IDs (kb_ids takes priority over kb_id)."""
        if self.kb_ids:
            return list(dict.fromkeys(self.kb_ids))
        if self.kb_id:
            return [self.kb_id]
        return []


# ═══ Response Models ═══

class QueryResult(BaseModel):
    id: str
    title: str | None = None
    content: str
    source_url: str | None = None
    score: float = 0.0
    search_source: str = "hybrid"


class DocumentDetail(BaseModel):
    id: str
    kb_id: str
    title: str
    source_url: str | None = None
    source_type: str = "manual"
    raw_text: str = ""
    chunk_count: int = 0


# ═══ Harvester ═══

class HarvesterChapter(BaseModel):
    index: int = 0
    title: str = ""
    graph_path: str = ""
    markdown: str = ""
    word_count: int = 0
    block_count: int = 0
    source_url: str | None = None
    error: str | None = None
