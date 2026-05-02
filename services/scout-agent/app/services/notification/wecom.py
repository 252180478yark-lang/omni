import logging
from datetime import datetime

import httpx

from app.config import settings
from app.services.notification.base import NotificationChannel

log = logging.getLogger(__name__)


class WecomChannel(NotificationChannel):
    name = "wecom"

    def __init__(self) -> None:
        self.webhook = settings.wecom_webhook_url
        enabled_cfg = settings.notification_wecom_enabled
        if enabled_cfg == "auto":
            self.enabled = bool(self.webhook)
        else:
            self.enabled = enabled_cfg.lower() == "true" and bool(self.webhook)

    async def send(self, level: str, title: str, body: str, meta: dict | None = None) -> None:
        if not self.enabled:
            return
        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
        content = f"【{title}】\n{body}\n时间: {ts}"
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                self.webhook,
                json={"msgtype": "text", "text": {"content": content}},
            )
            resp.raise_for_status()
        log.debug("wecom sent: [%s] %s", level, title)
