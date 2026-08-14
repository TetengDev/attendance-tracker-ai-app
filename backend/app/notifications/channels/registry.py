import os
import sys
from backend.app.notifications.channels.base import NotificationChannel
from backend.app.notifications.channels.email import SmtpEmailChannel
from backend.app.notifications.channels.sms import TwilioSmsChannel, FakeSmsChannel

_sms_channel: NotificationChannel | None = None
_email_channel: NotificationChannel | None = None

def get_sms_channel() -> NotificationChannel:
    global _sms_channel
    if _sms_channel is None:
        if os.environ.get("USE_FAKE_SMS") == "true" or "pytest" in sys.modules:
            _sms_channel = FakeSmsChannel()
        else:
            _sms_channel = TwilioSmsChannel()
    return _sms_channel

def set_sms_channel(channel: NotificationChannel | None) -> None:
    global _sms_channel
    _sms_channel = channel

def get_email_channel() -> NotificationChannel:
    global _email_channel
    if _email_channel is None:
        host = os.environ.get("SMTP_HOST", "localhost")
        port = int(os.environ.get("SMTP_PORT", "1025"))
        _email_channel = SmtpEmailChannel(hostname=host, port=port)
    return _email_channel

def set_email_channel(channel: NotificationChannel | None) -> None:
    global _email_channel
    _email_channel = channel
