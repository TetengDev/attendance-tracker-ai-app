from email.message import EmailMessage
import logging
from aiosmtplib import SMTP

logger = logging.getLogger("attendance_tracker")

class SmtpEmailChannel:
    def __init__(self, hostname: str = "localhost", port: int = 1025) -> None:
        self.hostname = hostname
        self.port = port

    async def send(self, recipient: str, message: str, subject: str | None = None) -> None:
        """Sends an email using aiosmtplib SMTP."""
        logger.info("Sending SMTP email to %s via %s:%s", recipient, self.hostname, self.port)
        
        email = EmailMessage()
        email["From"] = "no-reply@attendance-tracker.local"
        email["To"] = recipient
        email["Subject"] = subject or "Attendance Alert"
        email.set_content(message)

        try:
            async with SMTP(hostname=self.hostname, port=self.port) as client:
                await client.send_message(email)
        except Exception as e:
            logger.error("Failed to send SMTP email: %s", e)
            raise e
