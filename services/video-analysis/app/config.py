from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    service_name: str = "video-analysis"
    service_port: int = 8006
    data_dir: str = "/app/data/video-analysis"


settings = Settings()
