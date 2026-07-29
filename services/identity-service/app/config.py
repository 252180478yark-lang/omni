from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "dev"
    database_url: str = "postgresql+asyncpg://omni_user:changeme_in_production@localhost:5432/omni_vibe_db"
    redis_url: str = "redis://:changeme_redis@localhost:6379/0"
    # Inline keys exist only for hermetic tests.  Runtime deployments must use
    # an allocator-owned, read-only file outside the repository.
    jwt_secret_key: str | None = None
    jwt_secret_key_file: str | None = None
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30
    jwt_refresh_token_expire_days: int = 7
    service_name: str = "identity-service"
    service_port: int = 8000
    log_level: str = "INFO"
    cors_origins: str = "*"

    @property
    def jwt_signing_key(self) -> bytes:
        environment = self.app_env.strip().lower()
        is_test = environment in {"test", "testing"}
        if self.jwt_algorithm != "HS256":
            raise RuntimeError("unsupported JWT signing algorithm")

        if self.jwt_secret_key_file:
            path = Path(self.jwt_secret_key_file)
            if not path.is_absolute() and not is_test:
                raise RuntimeError("JWT_SECRET_KEY_FILE must be an absolute path")
            try:
                key = path.read_bytes()
            except OSError as exc:
                raise RuntimeError("JWT signing key file is unavailable") from exc
        elif is_test and self.jwt_secret_key is not None:
            key = self.jwt_secret_key.encode("utf-8")
        else:
            raise RuntimeError("JWT_SECRET_KEY_FILE is required")

        normalized = key.strip().lower()
        unsafe_markers = (
            b"change_me",
            b"changeme",
            b"replace_me",
            b"replace-me",
            b"your-secret",
            b"default-secret",
            b"insecure",
            b"example-secret",
        )
        if (
            len(key) < 32
            or len(key) > 4096
            or len(set(key)) < 8
            or any(marker in normalized for marker in unsafe_markers)
        ):
            raise RuntimeError("JWT signing key is unsafe")
        return key


settings = Settings()
