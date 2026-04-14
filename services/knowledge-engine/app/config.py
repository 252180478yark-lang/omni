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
    # 单次响应中「引用来源」每条 content 的最大字符数（前端展示 / 自复制等）
    rag_source_snippet_max_chars: int = 2000
    # RAG 生成阶段传给对话模型的 max_tokens（受各云厂商实际上限约束，可在环境变量调大/调小）
    # 大多数模型单次输出上限约 8192 tokens；多轮续写靠 rag_continue_max_rounds 实现长文
    rag_max_output_tokens: int = 8192
    # 多轮自动续写（接近 target_chars）
    rag_continue_max_rounds: int = 10
    rag_continue_target_ratio: float = 0.95  # 累计字数 >= target * ratio 则停
    rag_continue_max_target_chars: int = 200_000  # 单请求目标字数上限（防滥用）

    # RAG Advanced — query enhancement
    rag_query_rewrite: bool = True
    rag_hyde: bool = True
    rag_subquery: bool = True
    rag_subquery_max: int = 3

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
    video_analysis_service_url: str = "http://video-analysis:8006"

    # Legacy SQLite fallback (kept for backward compat)
    database_path: str = "/app/data/knowledge.db"


settings = Settings()
