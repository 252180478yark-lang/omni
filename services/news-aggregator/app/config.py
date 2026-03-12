from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "dev"
    service_name: str = "news-aggregator"
    service_port: int = 8005
    log_level: str = "INFO"

    database_url: str = "postgresql+asyncpg://omni_user:changeme_in_production@omni-postgres:5432/omni_vibe_db"
    redis_url: str = "redis://:changeme_redis@omni-redis:6379/2"

    serper_api_key: str = ""
    bocha_api_key: str = ""
    tianapi_key: str = ""

    sp3_base_url: str = "http://ai-provider-hub:8001"
    sp4_base_url: str = "http://knowledge-engine:8002"

    sp5_default_freshness: str = "oneDay"
    sp5_relevance_threshold: float = 0.3
    sp5_enrich_batch_size: int = 5
    sp5_target_kb_id: str = "default"

    enricher_provider: str = "gemini"
    enricher_model: str = "gemini-2.0-flash"
    enricher_max_tokens: int = 2000


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
