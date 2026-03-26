from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    service_name: str = "ai-provider-hub"
    service_port: int = 8001
    log_level: str = "INFO"

    # Provider API keys
    gemini_api_key: str = "AIzaSyByUe8Nxi6bWlsBqLAHFUG8ryGPe7chJws"
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    deepseek_api_key: str = ""
    ollama_base_url: str = "http://ollama:11434"

    # Defaults
    default_chat_provider: str = "gemini"
    default_embedding_provider: str = "gemini"
    request_timeout_seconds: float = 120.0
    provider_config_path: str = "/app/data/provider-config.json"

    # Redis (session / cost / rate / video-task)
    redis_url: str = "redis://:changeme_redis@omni-redis:6379/0"


settings = Settings()
