import json
import logging

from app.config import settings
from app.services.notification.base import NotificationChannel

log = logging.getLogger(__name__)


class BrowserPushChannel(NotificationChannel):
    name = "browser_push"

    def __init__(self) -> None:
        self.enabled = settings.notification_browser_push

    async def send(self, level: str, title: str, body: str, meta: dict | None = None) -> None:
        # Browser push requires a service worker on the frontend side.
        # For now we store a push-pending record; the frontend polls and
        # triggers the actual Web Push Notification via the Notifications API.
        from app.database import get_pool
        merged = {**(meta or {}), "push_pending": True}
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO mvp_notification(level, title, body, meta, created_at)
                VALUES ($1, $2, $3, $4::jsonb, NOW())
                """,
                level, title, body, json.dumps(merged),
            )
        log.debug("browser_push queued: [%s] %s", level, title)
