from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    service_name: str = "knowledge-engine"
    service_port: int = 8002
    ai_provider_hub_url: str = "http://ai-provider-hub:8001"
    embedding_provider: str = "openai"
    embedding_model: str = "text-embedding-3-small"
    chunk_size: int = 512
    chunk_overlap: int = 50
    embedding_batch_size: int = 100
    database_path: str = "/app/data/knowledge.db"


settings = Settings()
