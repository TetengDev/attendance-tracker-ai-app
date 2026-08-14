from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.app.notifications.channels.email import SmtpEmailChannel
from backend.app.notifications.channels.sms import FakeSmsChannel, TwilioSmsChannel


@pytest.mark.anyio
async def test_fake_sms_channel() -> None:
    fake = FakeSmsChannel()
    await fake.send(recipient="+639000000000", message="Test alert message")
    assert len(fake.sent_messages) == 1
    assert fake.sent_messages[0]["recipient"] == "+639000000000"
    assert fake.sent_messages[0]["message"] == "Test alert message"


@pytest.mark.anyio
async def test_twilio_sms_channel_missing_credentials() -> None:
    # Fails closed if config is empty
    twilio = TwilioSmsChannel(account_sid=None, auth_token=None, from_number=None)
    with pytest.raises(RuntimeError) as exc_info:
        await twilio.send(recipient="+639000000000", message="Fail closed alert")
    assert "Twilio credentials missing" in str(exc_info.value)


@pytest.mark.anyio
async def test_twilio_sms_channel_success() -> None:
    # Verify that TwilioClient sync calls are successfully dispatched in the async executor
    twilio = TwilioSmsChannel(
        account_sid="mock_sid", auth_token="mock_token", from_number="+123456"
    )

    with patch("backend.app.notifications.channels.sms.Client") as MockClient:
        mock_client_instance = MagicMock()
        MockClient.return_value = mock_client_instance

        await twilio.send(recipient="+639000000000", message="Sent via Twilio")

        MockClient.assert_called_once_with("mock_sid", "mock_token")
        mock_client_instance.messages.create.assert_called_once_with(
            to="+639000000000", from_="+123456", body="Sent via Twilio"
        )


@pytest.mark.anyio
async def test_smtp_email_channel_success() -> None:
    email_channel = SmtpEmailChannel(hostname="localhost", port=1025)

    with patch("backend.app.notifications.channels.email.SMTP") as MockSMTP:
        smtp_mock_instance = AsyncMock()
        MockSMTP.return_value.__aenter__.return_value = smtp_mock_instance

        await email_channel.send(
            recipient="parent@example.com", message="Your student is late.", subject="Late Alert"
        )

        MockSMTP.assert_called_once_with(hostname="localhost", port=1025)
        smtp_mock_instance.send_message.assert_called_once()
        sent_email = smtp_mock_instance.send_message.call_args[0][0]
        assert sent_email["To"] == "parent@example.com"
        assert sent_email["Subject"] == "Late Alert"
        assert "Your student is late." in sent_email.get_content()
