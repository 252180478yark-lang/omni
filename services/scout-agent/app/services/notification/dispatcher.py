import logging

from app.services.notification.base import NotificationChannel
from app.services.notification.inapp import InAppChannel
from app.services.notification.browser_push import BrowserPushChannel
from app.services.notification.wecom import WecomChannel
from app.services.notification.email import EmailChannel

log = logging.getLogger(__name__)


class NotificationDispatcher:
    def __init__(self) -> None:
        self.channels: list[NotificationChannel] = [
            InAppChannel(),
            BrowserPushChannel(),
            WecomChannel(),
            EmailChannel(),
        ]

    async def broadcast(self, level: str, title: str, body: str, meta: dict | None = None) -> None:
        for ch in self.channels:
            if not ch.enabled:
                continue
            try:
                await ch.send(level, title, body, meta)
            except Exception as exc:
                log.warning("notification channel %s failed: %s", ch.name, exc)


dispatcher = NotificationDispatcher()
