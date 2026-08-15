from typing import Protocol


class NotificationChannel(Protocol):
    async def send(self, recipient: str, message: str, subject: str | None = None) -> None:
        """Sends a notification to the recipient."""
        ...
