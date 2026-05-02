from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql://omni_user:changeme_in_production@localhost:5432/omni_vibe_db"
    ai_hub_url: str = "http://localhost:8001"

    douyin_shop_id: str = ""
    yuntu_brand_id: str = "WADAKAN_HETIANKUAN"
    yuntu_industry: str = "food_beverage"

    wecom_webhook_url: str = ""
    smtp_host: str = ""
    smtp_port: int = 465
    smtp_user: str = ""
    smtp_password: str = ""

    notification_inapp_enabled: bool = True
    notification_browser_push: bool = True
    notification_wecom_enabled: str = "auto"
    notification_email_enabled: str = "auto"

    enable_scheduler: bool = True
    schedule_cron: str = "30 8 * * *"
    playwright_headless: bool = False  # False locally (anti-bot); True in Docker

    log_level: str = "info"
    sessions_dir: str = "./sessions"
    downloads_dir: str = "./downloads"
    snapshots_dir: str = "./snapshots"
    runbooks_dir: str = "./runbooks"


settings = Settings()
