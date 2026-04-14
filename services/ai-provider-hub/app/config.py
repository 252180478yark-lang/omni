from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    service_name: str = "ai-provider-hub"
    service_port: int = 8001
    log_level: str = "INFO"

    # Provider API keys (通过 /models 页面或 .env 文件配置，禁止硬编码)
    gemini_api_key: str = ""
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    deepseek_api_key: str = ""
    ollama_base_url: str = "http://ollama:11434"

    # Video generation providers
    # Seedance 2.0 (火山方舟 Ark) — 推荐使用 ARK_API_KEY
    ark_api_key: str = ""
    seedance_access_key: str = ""  # legacy, 若 ark_api_key 为空则回退
    seedance_secret_key: str = ""  # legacy
    seedance_model: str = "doubao-seedance-2-0-260128"
    seedance_fast_model: str = "doubao-seedance-2-0-fast-260128"
    kling_api_key: str = ""

    # Defaults
    default_chat_provider: str = "gemini"
    default_embedding_provider: str = "gemini"
    request_timeout_seconds: float = 120.0
    # 流式对话（含 RAG 长文生成）单次连接的读取超时，过短会导致长输出中途被断开
    chat_stream_timeout_seconds: float = 900.0
    provider_config_path: str = "/app/data/provider-config.json"

    # Redis (session / cost / rate / video-task)
    redis_url: str = "redis://:changeme_redis@omni-redis:6379/0"


settings = Settings()
