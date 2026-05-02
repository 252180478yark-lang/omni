from abc import ABC, abstractmethod


class NotificationChannel(ABC):
    name: str
    enabled: bool = False

    @abstractmethod
    async def send(self, level: str, title: str, body: str, meta: dict | None = None) -> None: ...
