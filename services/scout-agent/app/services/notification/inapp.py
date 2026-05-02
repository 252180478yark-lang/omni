import json
import logging

from app.services.notification.base import NotificationChannel

log = logging.getLogger(__name__)


class InAppChannel(NotificationChannel):
    name = "inapp"
    enabled = True  # always on, no config needed

    async def send(self, level: str, title: str, body: str, meta: dict | None = None) -> None:
        from app.database import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO mvp_notification(level, title, body, meta, created_at)
                VALUES ($1, $2, $3, $4::jsonb, NOW())
                """,
                level, title, body, json.dumps(meta or {}),
            )
        log.debug("inapp notification sent: [%s] %s", level, title)
