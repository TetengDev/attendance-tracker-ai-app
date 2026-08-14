import asyncio
import logging
import os
from twilio.rest import Client

logger = logging.getLogger("attendance_tracker")

class TwilioSmsChannel:
    def __init__(self, account_sid: str | None = None, auth_token: str | None = None, from_number: str | None = None) -> None:
        self.account_sid = account_sid or os.environ.get("TWILIO_ACCOUNT_SID")
        self.auth_token = auth_token or os.environ.get("TWILIO_AUTH_TOKEN")
        self.from_number = from_number or os.environ.get("TWILIO_FROM_NUMBER")

    async def send(self, recipient: str, message: str, subject: str | None = None) -> None:
        """Sends an SMS using Twilio Client. Fails closed if credentials are missing."""
        if not self.account_sid or not self.auth_token or not self.from_number:
            err_msg = "Twilio credentials missing. SMS channel failed closed."
            logger.error(err_msg)
            raise RuntimeError(err_msg)

        logger.info("Sending Twilio SMS to %s from %s", recipient, self.from_number)
        
        loop = asyncio.get_running_loop()
        
        def _sync_send() -> None:
            client = Client(self.account_sid, self.auth_token)
            client.messages.create(
                to=recipient,
                from_=self.from_number,
                body=message
            )

        try:
            await loop.run_in_executor(None, _sync_send)
        except Exception as e:
            logger.error("Failed to send Twilio SMS: %s", e)
            raise e


class FakeSmsChannel:
    def __init__(self) -> None:
        self.sent_messages: list[dict[str, str]] = []

    async def send(self, recipient: str, message: str, subject: str | None = None) -> None:
        logger.info("[FAKE SMS CHANNEL] Sending to %s: %s", recipient, message)
        self.sent_messages.append({"recipient": recipient, "message": message})
