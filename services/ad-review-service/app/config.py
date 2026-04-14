from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql://omni_user:changeme_in_production@localhost:5432/omni_vibe_db"
    ai_hub_url: str = "http://localhost:8001"
    knowledge_engine_url: str = "http://localhost:8002"
    video_analysis_url: str = "http://localhost:8006"
    review_model: str = "gemini-2.0-flash"
    log_level: str = "info"
    data_dir: str = "./data"


settings = Settings()
