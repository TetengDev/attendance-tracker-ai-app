from __future__ import annotations

import base64
import os

os.environ.setdefault(
    "BIOMETRIC_KEK",
    "kek.test:" + base64.urlsafe_b64encode(bytes([9]) * 32).decode().rstrip("="),
)

from datetime import UTC, date, datetime, timedelta
from typing import Any, Self
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.attendance.decision_table import AttendanceStatus
from backend.app.models.attendance import AttendanceEvent, AttendanceRecord, ExpectedAttendance
from backend.app.models.notifications import Notification, NotificationRule, NotificationStatus
from backend.app.models.people import (
    ContactChannel,
    Group,
    Guardian,
    Person,
    PersonGroup,
    PersonGuardian,
)
from backend.app.models.scheduling import Shift
from backend.app.notifications.service import (
    MockNotificationGateway,
    dispatch_pending_notifications,
    get_matching_rule,
    process_record_notifications,
    set_notification_gateway,
)


class FakeResult:
    def __init__(self, data: list[Any]) -> None:
        self._data = data

    def scalars(self) -> FakeResult:
        return self

    def all(self) -> list[Any]:
        return self._data

    def scalar_one_or_none(self) -> Any | None:
        return self._data[0] if self._data else None

    def scalar_one(self) -> Any:
        return self._data[0]


class FakeTransaction:
    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        pass


class NotificationMockSession(AsyncSession):
    """A highly specialized Mock Session for Notification test scenarios."""

    def __init__(
        self,
        *,
        person: Person | None = None,
        expected: ExpectedAttendance | None = None,
        shift: Shift | None = None,
        notifications: list[Notification] | None = None,
        rules: list[NotificationRule] | None = None,
        guardian: Guardian | None = None,
        event: AttendanceEvent | None = None,
    ) -> None:
        super().__init__(bind=MagicMock())
        self.person = person
        self.expected = expected
        self.shift = shift
        self.notifications = notifications if notifications is not None else []
        self.rules = rules if rules is not None else []
        self.guardian = guardian
        self.event = event

        self.added: list[Any] = []
        self.deleted_models: list[Any] = []
        self.committed = False

    def begin(self) -> FakeTransaction:  # type: ignore[override]
        return FakeTransaction()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        pass

    def add(self, instance: Any) -> None:  # type: ignore[override]
        self.added.append(instance)

    async def delete(self, instance: Any) -> None:
        self.deleted_models.append(instance)

    async def commit(self) -> None:
        self.committed = True

    async def execute(
        self,
        statement: Any,
        params: Any = None,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        sql = str(statement)
        params_dict = {}
        try:
            params_dict = statement.compile().params
        except Exception:  # noqa: BLE001, S110
            pass

        # 1. Resolve Settings query
        if "FROM settings_version" in sql:
            return FakeResult([1])
        if "FROM settings" in sql:
            return FakeResult([])

        # 2. Person lookup
        if "FROM people" in sql:
            return FakeResult([self.person] if self.person else [])

        # 3. ExpectedAttendance lookup
        if "FROM expected_attendance" in sql:
            return FakeResult([self.expected] if self.expected else [])

        # 4. Shift lookup
        if "FROM shifts" in sql:
            return FakeResult([self.shift] if self.shift else [])

        # 5. Guardian lookup
        if "FROM guardians" in sql:
            return FakeResult([self.guardian] if self.guardian else [])

        # 6. AttendanceEvent lookup
        if "FROM attendance_events" in sql:
            return FakeResult([self.event] if self.event else [])

        # 7. NotificationRule matching
        if "FROM notification_rules" in sql:
            filtered_rules = self.rules
            if "is_active" in sql:
                filtered_rules = [r for r in filtered_rules if r.is_active]
            return FakeResult(filtered_rules)

        # 8. Duplicate check or Status query on notifications
        if "FROM notifications" in sql:
            # First compile params
            params_dict = {}
            try:
                params_dict = statement.compile().params
            except Exception:  # noqa: BLE001, S110
                pass

            # Check if it's the exists/dedupe query
            is_dedupe_check = False
            for k in params_dict:
                if "dedupe" in k:
                    is_dedupe_check = True
                    break

            if is_dedupe_check:
                # Check compiled params or sql
                dedupe_val = params_dict.get("dedupe_key_1") or params_dict.get("dedupe_key")
                if dedupe_val:
                    for notif in self.notifications:
                        if notif.dedupe_key == dedupe_val:
                            return FakeResult([notif.id])
                return FakeResult([])

            # Filter by status and type using compiled params
            filtered = self.notifications
            if params_dict:
                # Filter status
                for k, v in params_dict.items():
                    if k.startswith("status"):
                        filtered = [n for n in filtered if n.status == v]
                # Filter type
                for k, v in params_dict.items():
                    if k.startswith("type"):
                        filtered = [n for n in filtered if n.type == v]

            return FakeResult(filtered)

        return FakeResult([])


# ---------------------------------------------------------------------------
# Setup Helpers
# ---------------------------------------------------------------------------

PERSON_ID = uuid4()
GUARDIAN_ID = uuid4()
SHIFT_ID = uuid4()
LOCATION_ID = uuid4()
GROUP_ID = uuid4()


def setup_person_with_guardian() -> tuple[Person, Guardian]:
    p = Person(id=PERSON_ID, display_name="Alice", kind="student")
    p.is_active = True
    g = Guardian(
        id=GUARDIAN_ID,
        display_name="Mr. Bob",
        phone="+639000000000",
        preferred_channel=ContactChannel.SMS,
    )
    pg = PersonGuardian(
        person_id=PERSON_ID,
        guardian_id=GUARDIAN_ID,
        relationship="father",
        receives_attendance_alerts=True,
    )
    pg.guardian = g
    p.guardians = [pg]
    p.group_memberships = []
    return p, g


# ---------------------------------------------------------------------------
# Test Cases
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_process_record_notifications_queues_absence() -> None:
    """Verifies that transitioning to ABSENT queues an absence notification to the active guardian."""
    person, _guardian = setup_person_with_guardian()
    expected = ExpectedAttendance(
        person_id=PERSON_ID,
        business_date=date(2026, 8, 14),
        shift_id=SHIFT_ID,
        period_label="",
        expected_start_at=datetime(2026, 8, 14, 8, 0, tzinfo=UTC),
        expected_end_at=datetime(2026, 8, 14, 17, 0, tzinfo=UTC),
    )
    expected.id = uuid4()
    expected.location_id = LOCATION_ID

    record = AttendanceRecord(
        person_id=PERSON_ID,
        business_date=date(2026, 8, 14),
        shift_id=SHIFT_ID,
        period_label="",
        status=AttendanceStatus.ABSENT,
        expected_attendance_id=expected.id,
    )

    session = NotificationMockSession(person=person, expected=expected)
    await process_record_notifications(session, record, old_status=None)

    # Asserts that 1 notification has been queued
    assert len(session.added) == 1
    notif: Notification = session.added[0]
    assert notif.person_id == PERSON_ID
    assert notif.guardian_id == GUARDIAN_ID
    assert notif.type == "absence"
    assert notif.status == NotificationStatus.PENDING
    assert notif.recipient == "+639000000000"
    assert notif.channel == ContactChannel.SMS
    # Verify scheduled delay (8:00 AM + 10 mins default = 8:10 AM)
    assert notif.scheduled_at == datetime(2026, 8, 14, 8, 10, tzinfo=UTC)


@pytest.mark.anyio
async def test_process_record_notifications_retracts_pending() -> None:
    """Transitioning to ON_TIME should change queued PENDING absence alerts to RETRACTED."""
    person, _guardian = setup_person_with_guardian()
    record = AttendanceRecord(
        person_id=PERSON_ID,
        business_date=date(2026, 8, 14),
        shift_id=SHIFT_ID,
        period_label="",
        status=AttendanceStatus.ON_TIME,
    )

    pending_alert = Notification(
        person_id=PERSON_ID,
        business_date=date(2026, 8, 14),
        shift_id=SHIFT_ID,
        period_label="",
        guardian_id=GUARDIAN_ID,
        type="absence",
        status=NotificationStatus.PENDING,
        channel=ContactChannel.SMS,
        recipient="+639000000000",
        message_body="Test",
        dedupe_key="absence:key",
        scheduled_at=datetime.now(UTC),
    )

    session = NotificationMockSession(person=person, notifications=[pending_alert])
    await process_record_notifications(session, record, old_status=AttendanceStatus.ABSENT)

    # Verify that the pending alert status was changed to retracted
    assert pending_alert.status == NotificationStatus.RETRACTED


@pytest.mark.anyio
async def test_process_record_notifications_queues_retraction_for_sent() -> None:
    """Transitioning to LATE when an alert was already SENT should queue a retraction alert immediately."""
    person, guardian = setup_person_with_guardian()
    record = AttendanceRecord(
        person_id=PERSON_ID,
        business_date=date(2026, 8, 14),
        shift_id=SHIFT_ID,
        period_label="",
        status=AttendanceStatus.LATE,
        first_event_id=123,
    )

    sent_alert = Notification(
        person_id=PERSON_ID,
        business_date=date(2026, 8, 14),
        shift_id=SHIFT_ID,
        period_label="",
        guardian_id=GUARDIAN_ID,
        type="absence",
        status=NotificationStatus.SENT,
        channel=ContactChannel.SMS,
        recipient="+639000000000",
        message_body="Alice was marked absent",
        dedupe_key="absence:key",
        scheduled_at=datetime.now(UTC),
    )

    event = AttendanceEvent(
        id=123,
        occurred_at=datetime(2026, 8, 14, 8, 25, tzinfo=UTC),
        server_received_at=datetime(2026, 8, 14, 8, 25, tzinfo=UTC),
        idempotency_key="idemp",
    )

    session = NotificationMockSession(
        person=person,
        notifications=[sent_alert],
        guardian=guardian,
        event=event,
    )
    await process_record_notifications(session, record, old_status=AttendanceStatus.ABSENT)

    # Asserts that a retraction alert has been queued
    assert len(session.added) == 1
    retraction: Notification = session.added[0]
    assert retraction.type == "retraction"
    assert retraction.status == NotificationStatus.PENDING
    assert "Correction" in retraction.message_body
    assert "08:25:00" in retraction.message_body  # Contains arrival time


@pytest.mark.anyio
async def test_get_matching_rule_precedence() -> None:
    """Tests that rule matching properly scores rules by specificity."""
    person, _guardian = setup_person_with_guardian()
    
    # Active group membership
    group = Group(id=GROUP_ID, name="Grade 7", kind="grade")
    membership = PersonGroup(
        person_id=PERSON_ID,
        group_id=GROUP_ID,
        effective_from=date(2026, 6, 1),
    )
    membership.group = group
    person.group_memberships = [membership]

    # Rule A: applies to student kind only (score = 5)
    rule_a = NotificationRule(
        trigger_status="absent",
        person_kind="student",
        delay_minutes=15,
        template="Rule A {person_name}",
        is_active=True,
    )
    # Rule B: applies to Grade 7 group only (score = 10)
    rule_b = NotificationRule(
        trigger_status="absent",
        group_id=GROUP_ID,
        delay_minutes=20,
        template="Rule B {person_name}",
        is_active=True,
    )
    # Rule C: applies to Grade 7 student (score = 15)
    rule_c = NotificationRule(
        trigger_status="absent",
        group_id=GROUP_ID,
        person_kind="student",
        delay_minutes=30,
        template="Rule C {person_name}",
        is_active=True,
    )

    session = NotificationMockSession(rules=[rule_a, rule_b, rule_c])
    
    # Rule C should win because it matches both kind and group
    rule = await get_matching_rule(session, person, "absent")
    assert rule is not None
    assert str(rule.template) == "Rule C {person_name}"

    # Verify fallback if C is inactive
    rule_c.is_active = False
    rule = await get_matching_rule(session, person, "absent")
    assert rule is not None
    assert str(rule.template) == "Rule B {person_name}"


@pytest.mark.anyio
async def test_dispatch_pending_notifications() -> None:
    """Verifies that the background worker dispatches pending alerts via gateway and handles errors."""
    mock_gateway = MockNotificationGateway()
    set_notification_gateway(mock_gateway)

    notif_sms = Notification(
        person_id=PERSON_ID,
        business_date=date(2026, 8, 14),
        shift_id=SHIFT_ID,
        guardian_id=GUARDIAN_ID,
        type="absence",
        status=NotificationStatus.PENDING,
        channel=ContactChannel.SMS,
        recipient="+639111111111",
        message_body="SMS text",
        dedupe_key="sms_key",
        scheduled_at=datetime.now(UTC) - timedelta(minutes=5),
    )

    notif_email = Notification(
        person_id=PERSON_ID,
        business_date=date(2026, 8, 14),
        shift_id=SHIFT_ID,
        guardian_id=GUARDIAN_ID,
        type="absence",
        status=NotificationStatus.PENDING,
        channel=ContactChannel.EMAIL,
        recipient="guardian@example.com",
        message_body="Email text",
        dedupe_key="email_key",
        scheduled_at=datetime.now(UTC) - timedelta(minutes=5),
    )

    session = NotificationMockSession(notifications=[notif_sms, notif_email])
    sent_count = await dispatch_pending_notifications(session)

    # Both should be processed
    assert sent_count == 2
    assert len(mock_gateway.sent_sms) == 1
    assert mock_gateway.sent_sms[0]["recipient"] == "+639111111111"
    assert len(mock_gateway.sent_emails) == 1
    assert mock_gateway.sent_emails[0]["recipient"] == "guardian@example.com"
    
    # Assert database status update
    assert notif_sms.status == NotificationStatus.SENT
    assert notif_email.status == NotificationStatus.SENT

    # Test failure handling with retries and backoff
    mock_gateway.fail_next = True
    notif_fail = Notification(
        person_id=PERSON_ID,
        business_date=date(2026, 8, 14),
        shift_id=SHIFT_ID,
        guardian_id=GUARDIAN_ID,
        type="absence",
        status=NotificationStatus.PENDING,
        channel=ContactChannel.SMS,
        recipient="+639222222222",
        message_body="SMS text",
        dedupe_key="sms_fail_key",
        scheduled_at=datetime.now(UTC) - timedelta(minutes=5),
        retry_count=0,
    )
    session = NotificationMockSession(notifications=[notif_fail])
    await dispatch_pending_notifications(session)

    # Status should still be PENDING (for retry), retry_count incremented to 1, and scheduled_at shifted
    assert notif_fail.status == NotificationStatus.PENDING
    assert notif_fail.retry_count == 1
    assert "Attempt 1/5 failed" in (notif_fail.error_message or "")
    assert notif_fail.scheduled_at > datetime.now(UTC) + timedelta(seconds=110)

    # Trigger max retries exceeded
    notif_max_fail = Notification(
        person_id=PERSON_ID,
        business_date=date(2026, 8, 14),
        shift_id=SHIFT_ID,
        guardian_id=GUARDIAN_ID,
        type="absence",
        status=NotificationStatus.PENDING,
        channel=ContactChannel.SMS,
        recipient="+639222222222",
        message_body="SMS text",
        dedupe_key="sms_fail_key_max",
        scheduled_at=datetime.now(UTC) - timedelta(minutes=5),
        retry_count=4,
    )
    mock_gateway.fail_next = True
    session_max = NotificationMockSession(notifications=[notif_max_fail])
    await dispatch_pending_notifications(session_max)

    # Now status should be FAILED since retry_count reached 5
    assert notif_max_fail.status == NotificationStatus.FAILED
    assert notif_max_fail.retry_count == 5
    assert "Max retries (5) exceeded" in (notif_max_fail.error_message or "")


@pytest.mark.anyio
async def test_pluggable_channels_registry() -> None:
    """Verify that pluggable channels are correctly initialized in the registry."""
    import os
    from backend.app.notifications.channels import (
        get_sms_channel,
        get_email_channel,
        FakeSmsChannel,
        SmtpEmailChannel,
        set_sms_channel,
        set_email_channel,
    )

    # Clear registry cache
    set_sms_channel(None)
    set_email_channel(None)

    # In test mode, get_sms_channel defaults to FakeSmsChannel
    sms_chan = get_sms_channel()
    assert isinstance(sms_chan, FakeSmsChannel)

    # Get email channel defaults to SmtpEmailChannel
    email_chan = get_email_channel()
    assert isinstance(email_chan, SmtpEmailChannel)
    assert email_chan.hostname == "localhost"
    assert email_chan.port == 1025

