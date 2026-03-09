from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    service_name: str = "ai-provider-hub"
    service_port: int = 8001
    log_level: str = "INFO"

    gemini_api_key: str = ""
    openai_api_key: str = ""
    ollama_base_url: str = "http://ollama:11434"

    default_chat_provider: str = "gemini"
    default_embedding_provider: str = "openai"
    request_timeout_seconds: float = 30.0


settings = Settings()
