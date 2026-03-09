from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "dev"
    database_url: str = "postgresql+asyncpg://omni_user:changeme_in_production@localhost:5432/omni_vibe_db"
    redis_url: str = "redis://:changeme_redis@localhost:6379/0"
    jwt_secret_key: str = "change_me"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30
    jwt_refresh_token_expire_days: int = 7
    service_name: str = "identity-service"
    service_port: int = 8000
    log_level: str = "INFO"
    cors_origins: str = "*"


settings = Settings()
