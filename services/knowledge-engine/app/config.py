from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    service_name: str = "knowledge-engine"
    service_port: int = 8002

    # PostgreSQL (primary storage)
    database_url: str = "postgresql://omni_user:changeme_in_production@omni-postgres:5432/omni_vibe_db"
    db_pool_min: int = 2
    db_pool_max: int = 10

    # Redis (caching)
    redis_url: str = "redis://:changeme_redis@omni-redis:6379/1"

    # AI Provider Hub
    ai_provider_hub_url: str = "http://ai-provider-hub:8001"

    # Embedding defaults
    embedding_provider: str = "gemini"
    embedding_model: str = "gemini-embedding-2-preview"
    embedding_batch_size: int = 100

    # Chunking
    chunk_size: int = 768
    chunk_overlap: int = 128

    # RAG
    rag_top_k: int = 15
    rag_score_threshold: float = 0.25

    # RAG Advanced — query enhancement
    rag_query_rewrite: bool = True
    rag_hyde: bool = True
    rag_subquery: bool = True
    rag_subquery_max: int = 5

    # RAG Advanced — reranking
    rag_cross_encoder_rerank: bool = True
    rag_rerank_top_n: int = 8

    # RAG Advanced — context
    rag_context_window: int = 2
    rag_contextual_compression: bool = True

    # RAG Advanced — CRAG
    rag_crag_enabled: bool = True

    # Indexing — chunk headers
    chunk_contextual_headers: bool = True

    # Indexing — HyPE (hypothetical prompt embeddings)
    hype_enabled: bool = True
    hype_questions_per_chunk: int = 3

    # Harvester
    harvester_auth_state: str = "/app/data/harvester_auth.json"
    feishu_auth_state: str = "/app/data/feishu_auth.json"

    # Legacy SQLite fallback (kept for backward compat)
    database_path: str = "/app/data/knowledge.db"


settings = Settings()
