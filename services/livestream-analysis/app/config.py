"""直播切片分析 — 配置管理"""

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


DATA_DIR = Path("/app/data/livestream-analysis")


class Settings(BaseSettings):
    gemini_api_key: str = Field(default="", description="Gemini API Key (通过 .env 或 ai-provider-hub 同步配置，禁止硬编码)")
    gemini_model: str = "gemini-2.5-pro-preview-06-05"
    gemini_temperature: float = 0.3
    gemini_max_output_tokens: int = 65536

    max_video_duration_minutes: int = 60
    segment_duration_minutes: int = 10

    request_timeout_seconds: int = 300
    max_retries: int = 3
    upload_poll_interval_seconds: int = 5
    upload_poll_max_wait_seconds: int = 300

    http_proxy: str = ""
    https_proxy: str = ""

    parallel_workers: int = 3

    data_dir: str = str(DATA_DIR)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
