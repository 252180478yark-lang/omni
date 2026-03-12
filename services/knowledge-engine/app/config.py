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
    chunk_size: int = 512
    chunk_overlap: int = 64

    # RAG
    rag_top_k: int = 5
    rag_score_threshold: float = 0.7

    # Legacy SQLite fallback (kept for backward compat)
    database_path: str = "/app/data/knowledge.db"


settings = Settings()
