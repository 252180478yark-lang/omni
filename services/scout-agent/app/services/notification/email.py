import logging

from app.config import settings
from app.services.notification.base import NotificationChannel

log = logging.getLogger(__name__)


class EmailChannel(NotificationChannel):
    name = "email"

    def __init__(self) -> None:
        enabled_cfg = settings.notification_email_enabled
        if enabled_cfg == "auto":
            self.enabled = bool(settings.smtp_host and settings.smtp_user)
        else:
            self.enabled = enabled_cfg.lower() == "true"

    async def send(self, level: str, title: str, body: str, meta: dict | None = None) -> None:
        # Email sending is a placeholder — implement with aiosmtplib when needed.
        log.debug("email channel: not implemented, skipping [%s] %s", level, title)
