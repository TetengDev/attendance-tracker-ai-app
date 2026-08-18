from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from backend.app.attendance.decision_table import AttendanceStatus
from backend.app.attendance.resolver import resolve_db_settings
from backend.app.models.attendance import AttendanceRecord, ExpectedAttendance
from backend.app.models.notifications import Notification, NotificationRule, NotificationStatus
from backend.app.models.people import ContactChannel, Guardian, Person, PersonGuardian
from backend.app.models.scheduling import Shift
from backend.app.settings.resolver import SettingContext

logger = logging.getLogger("attendance_tracker")


class NotificationGateway(Protocol):
    async def send_sms(self, recipient: str, message: str) -> None:
        """Sends an SMS to the recipient."""
        ...

    async def send_email(self, recipient: str, subject: str, message: str) -> None:
        """Sends an Email to the recipient."""
        ...


class ConsoleNotificationGateway(NotificationGateway):
    """Fallback gateway that prints to stdout/logs."""

    async def send_sms(self, recipient: str, message: str) -> None:
        logger.info("[SMS GATEWAY] Sending to %s: %s", recipient, message)

    async def send_email(self, recipient: str, subject: str, message: str) -> None:
        logger.info("[EMAIL GATEWAY] Sending to %s (Subject: %s): %s", recipient, subject, message)


class MockNotificationGateway(NotificationGateway):
    """Mock gateway used for unit tests to record and assert sent messages."""

    def __init__(self) -> None:
        self.sent_sms: list[dict[str, str]] = []
        self.sent_emails: list[dict[str, str]] = []
        self.fail_next = False

    async def send_sms(self, recipient: str, message: str) -> None:
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("Mock SMS delivery failure")
        self.sent_sms.append({"recipient": recipient, "message": message})

    async def send_email(self, recipient: str, subject: str, message: str) -> None:
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("Mock Email delivery failure")
        self.sent_emails.append({"recipient": recipient, "subject": subject, "message": message})


# Global default gateway (can be replaced in test suite setup)
current_gateway: NotificationGateway = ConsoleNotificationGateway()


def get_notification_gateway() -> NotificationGateway:
    return current_gateway


def set_notification_gateway(gateway: NotificationGateway) -> None:
    global current_gateway
    current_gateway = gateway


async def process_record_notifications(
    session: Any,  # AsyncSession
    record: AttendanceRecord,
    old_status: AttendanceStatus | None,
) -> None:
    """Invoked by attendance resolver when an AttendanceRecord is written or updated.

    Queues new notifications or retracts/cancels existing pending notifications.
    """
    if old_status is not None and record.status == old_status:
        return

    # Only students get guardian alerts generally
    person_stmt = (
        select(Person)
        .where(Person.id == record.person_id)
        .options(
            selectinload(Person.guardians).selectinload(PersonGuardian.guardian),
            selectinload(Person.group_memberships),
        )
    )
    person = (await session.execute(person_stmt)).scalar_one_or_none()
    if not person or not person.is_active or not person.guardians:
        return

    # Load expected attendance to calculate schedule start time / settings context
    expected = None
    location_tz = "Asia/Manila"
    if record.expected_attendance_id:
        expected_stmt = select(ExpectedAttendance).where(
            ExpectedAttendance.id == record.expected_attendance_id
        )
        expected = (await session.execute(expected_stmt)).scalar_one_or_none()
        if expected and expected.location_id:
            from backend.app.models.devices import Location

            loc_stmt = select(Location).where(Location.id == expected.location_id)
            loc = (await session.execute(loc_stmt)).scalar_one_or_none()
            if loc and loc.timezone:
                location_tz = loc.timezone

    # Load shift info for template naming
    shift_name = "Regular"
    if record.shift_id and record.shift_id != UUID("00000000-0000-0000-0000-000000000000"):
        shift_stmt = select(Shift).where(Shift.id == record.shift_id)
        shift = (await session.execute(shift_stmt)).scalar_one_or_none()
        if shift:
            shift_name = shift.name

    # Load settings context
    context = SettingContext(location_id=expected.location_id if expected else None)
    settings_obj = await resolve_db_settings(session, context)
    delay_mins = settings_obj.settings.get("attendance.absence_notify_delay_minutes", 10)

    # 1. Handle Transition to ABSENT
    if record.status == AttendanceStatus.ABSENT:
        for pg in person.guardians:
            if not pg.receives_attendance_alerts or not pg.guardian:
                continue

            guardian = pg.guardian
            if guardian.preferred_channel == ContactChannel.NONE:
                continue

            recipient = (
                guardian.phone
                if guardian.preferred_channel == ContactChannel.SMS
                else guardian.email
            )
            if not recipient:
                continue

            # Check matching rule or fallback to defaults
            rule = await get_matching_rule(session, person, "absent")
            delay = rule.delay_minutes if rule else delay_mins
            template_str = rule.template if rule else get_fallback_template("absent")

            # Calculate scheduled send time
            base_time = expected.expected_start_at if expected else datetime.now(UTC)
            scheduled_at = base_time + timedelta(minutes=delay)

            # Dedupe key: ensure unique notification per person, date, shift, period, and guardian
            dedupe_key = f"absence:{record.person_id}:{record.business_date}:{record.shift_id}:{record.period_label}:{guardian.id}"

            # Check if this alert is already queued/sent (database unique key will protect, but checking here prevents unnecessary exception overhead)
            exists_stmt = select(Notification.id).where(Notification.dedupe_key == dedupe_key)
            if (await session.execute(exists_stmt)).scalar_one_or_none():
                continue

            unsubscribe_token = generate_unsubscribe_token(guardian.id)
            unsubscribe_url = f"http://localhost:8000/api/notifications/unsubscribe?token={unsubscribe_token}"

            # Render message
            message_body = render_template(
                str(template_str),
                {
                    "guardian_name": guardian.display_name,
                    "person_name": person.display_name,
                    "shift_name": shift_name,
                    "date": record.business_date.isoformat(),
                    "unsubscribe_url": unsubscribe_url,
                },
            )

            # Insert pending notification
            notif = Notification(
                person_id=record.person_id,
                business_date=record.business_date,
                shift_id=record.shift_id,
                period_label=record.period_label,
                guardian_id=guardian.id,
                type="absence",
                status=NotificationStatus.PENDING,
                channel=guardian.preferred_channel,
                recipient=recipient,
                message_body=message_body,
                dedupe_key=dedupe_key,
                scheduled_at=scheduled_at,
            )
            session.add(notif)

    # 2. Handle Transition to Late / On Time / Present (Retraction of Absence)
    elif record.status in (
        AttendanceStatus.ON_TIME,
        AttendanceStatus.LATE,
        AttendanceStatus.PRESENT_UNSCHEDULED,
    ):
        # Find any PENDING absence alerts and retract them immediately
        pending_stmt = select(Notification).where(
            Notification.person_id == record.person_id,
            Notification.business_date == record.business_date,
            Notification.shift_id == record.shift_id,
            Notification.period_label == record.period_label,
            Notification.type == "absence",
            Notification.status == NotificationStatus.PENDING,
        )
        pending_alerts = (await session.execute(pending_stmt)).scalars().all()
        for alert in pending_alerts:
            alert.status = NotificationStatus.RETRACTED
            session.add(alert)

        # Check if an absence alert was already SENT
        sent_stmt = select(Notification).where(
            Notification.person_id == record.person_id,
            Notification.business_date == record.business_date,
            Notification.shift_id == record.shift_id,
            Notification.period_label == record.period_label,
            Notification.type == "absence",
            Notification.status == NotificationStatus.SENT,
        )
        sent_alerts = (await session.execute(sent_stmt)).scalars().all()

        if sent_alerts:
            # An absence alert was already sent. We must dispatch a retraction.
            for alert in sent_alerts:
                guardian_id = alert.guardian_id
                guardian_stmt = select(Guardian).where(Guardian.id == guardian_id)
                guardian = (await session.execute(guardian_stmt)).scalar_one_or_none()
                if not guardian or guardian.preferred_channel == ContactChannel.NONE:
                    continue

                recipient = (
                    guardian.phone
                    if guardian.preferred_channel == ContactChannel.SMS
                    else guardian.email
                )
                if not recipient:
                    continue

                dedupe_key = f"retraction:{record.person_id}:{record.business_date}:{record.shift_id}:{record.period_label}:{guardian_id}"

                # Check if already retraction queued/sent
                exists_stmt = select(Notification.id).where(Notification.dedupe_key == dedupe_key)
                if (await session.execute(exists_stmt)).scalar_one_or_none():
                    continue

                rule = await get_matching_rule(session, person, "retraction")
                template_str = rule.template if rule else get_fallback_template("retraction")

                # Get actual arrival time from events
                arrival_time = "—"
                if record.first_event_id:
                    # Lazy import to avoid circular references
                    from backend.app.models.attendance import AttendanceEvent

                    event_stmt = select(AttendanceEvent).where(
                        AttendanceEvent.id == record.first_event_id
                    )
                    event = (await session.execute(event_stmt)).scalar_one_or_none()
                    if event:
                        from zoneinfo import ZoneInfo
                        arrival_time = event.occurred_at.astimezone(ZoneInfo(location_tz)).strftime("%H:%M:%S")

                unsubscribe_token = generate_unsubscribe_token(guardian_id)
                unsubscribe_url = f"http://localhost:8000/api/notifications/unsubscribe?token={unsubscribe_token}"

                # Render message
                message_body = render_template(
                    str(template_str),
                    {
                        "guardian_name": guardian.display_name,
                        "person_name": person.display_name,
                        "shift_name": shift_name,
                        "date": record.business_date.isoformat(),
                        "time": arrival_time,
                        "unsubscribe_url": unsubscribe_url,
                    },
                )

                retraction = Notification(
                    person_id=record.person_id,
                    business_date=record.business_date,
                    shift_id=record.shift_id,
                    period_label=record.period_label,
                    guardian_id=guardian_id,
                    type="retraction",
                    status=NotificationStatus.PENDING,
                    channel=guardian.preferred_channel,
                    recipient=recipient,
                    message_body=message_body,
                    dedupe_key=dedupe_key,
                    scheduled_at=datetime.now(UTC),
                )
                session.add(retraction)

        # 3. Handle Late/Tardiness alerts
        if record.status == AttendanceStatus.LATE:
            for pg in person.guardians:
                if not pg.receives_attendance_alerts or not pg.guardian:
                    continue

                guardian = pg.guardian
                if guardian.preferred_channel == ContactChannel.NONE:
                    continue

                recipient = (
                    guardian.phone
                    if guardian.preferred_channel == ContactChannel.SMS
                    else guardian.email
                )
                if not recipient:
                    continue

                dedupe_key = f"late:{record.person_id}:{record.business_date}:{record.shift_id}:{record.period_label}:{guardian.id}"

                exists_stmt = select(Notification.id).where(Notification.dedupe_key == dedupe_key)
                if (await session.execute(exists_stmt)).scalar_one_or_none():
                    continue

                rule = await get_matching_rule(session, person, "late")
                delay = rule.delay_minutes if rule else 0
                template_str = rule.template if rule else get_fallback_template("late")

                # Get actual arrival time from events
                arrival_time = "—"
                if record.first_event_id:
                    # Lazy import to avoid circular references
                    from backend.app.models.attendance import AttendanceEvent

                    event_stmt = select(AttendanceEvent).where(
                        AttendanceEvent.id == record.first_event_id
                    )
                    event = (await session.execute(event_stmt)).scalar_one_or_none()
                    if event:
                        from zoneinfo import ZoneInfo
                        arrival_time = event.occurred_at.astimezone(ZoneInfo(location_tz)).strftime("%H:%M:%S")

                unsubscribe_token = generate_unsubscribe_token(guardian.id)
                unsubscribe_url = f"http://localhost:8000/api/notifications/unsubscribe?token={unsubscribe_token}"

                # Render message
                message_body = render_template(
                    str(template_str),
                    {
                        "guardian_name": guardian.display_name,
                        "person_name": person.display_name,
                        "shift_name": shift_name,
                        "date": record.business_date.isoformat(),
                        "time": arrival_time,
                        "unsubscribe_url": unsubscribe_url,
                    },
                )

                scheduled_at = datetime.now(UTC) + timedelta(minutes=delay)

                late_notif = Notification(
                    person_id=record.person_id,
                    business_date=record.business_date,
                    shift_id=record.shift_id,
                    period_label=record.period_label,
                    guardian_id=guardian.id,
                    type="late",
                    status=NotificationStatus.PENDING,
                    channel=guardian.preferred_channel,
                    recipient=recipient,
                    message_body=message_body,
                    dedupe_key=dedupe_key,
                    scheduled_at=scheduled_at,
                )
                session.add(late_notif)


async def get_matching_rule(
    session: Any,
    person: Person,
    trigger_status: str,
) -> NotificationRule | None:
    """Finds the most specific notification rule matching the person kind and group memberships."""
    # Fetch all active rules for this trigger status
    stmt = select(NotificationRule).where(
        NotificationRule.trigger_status == trigger_status,
        NotificationRule.is_active.is_(True),
    )
    rules = (await session.execute(stmt)).scalars().all()
    if not rules:
        return None

    # Get active groups for this person
    group_ids = {
        m.group_id for m in person.group_memberships if m.is_active_on(datetime.now(UTC).date())
    }

    best_rule: NotificationRule | None = None
    best_score = -1

    for rule in rules:
        score = 0
        # Group match
        if rule.group_id:
            if rule.group_id not in group_ids:
                continue
            score += 10

        # Person kind match
        if rule.person_kind:
            if rule.person_kind != person.kind:
                continue
            score += 5

        if score > best_score:
            best_score = score
            best_rule = rule

    return best_rule


async def dispatch_pending_notifications(
    session: Any, gateway: NotificationGateway | None = None
) -> int:
    """Finds and sends all pending notifications scheduled to be sent now or in the past.

    Uses lock options to prevent double-delivery races, and implements retry and backoff.
    """
    if gateway is None:
        gateway = get_notification_gateway()

    from backend.app.notifications.channels import get_email_channel, get_sms_channel

    email_chan = get_email_channel()
    sms_chan = get_sms_channel()

    now_utc = datetime.now(UTC)
    # Query with select FOR UPDATE to lock rows and prevent race conditions between parallel worker loops
    stmt = (
        select(Notification)
        .where(
            Notification.status == NotificationStatus.PENDING,
            Notification.scheduled_at <= now_utc,
        )
        .with_for_update(skip_locked=True)
        .limit(100)
    )
    res = await session.execute(stmt)
    notifications = res.scalars().all()

    count = 0
    for notif in notifications:
        try:
            if not isinstance(gateway, ConsoleNotificationGateway):
                # Unit tests injected a mock/stub gateway
                if notif.channel == ContactChannel.SMS:
                    await gateway.send_sms(notif.recipient, notif.message_body)
                elif notif.channel == ContactChannel.EMAIL:
                    await gateway.send_email(
                        recipient=notif.recipient,
                        subject="Attendance Alert",
                        message=notif.message_body,
                    )
                else:
                    raise ValueError(f"Unsupported notification channel: {notif.channel}")
            else:
                # Pluggable channels under normal operation
                if notif.channel == ContactChannel.SMS:
                    await sms_chan.send(notif.recipient, notif.message_body)
                elif notif.channel == ContactChannel.EMAIL:
                    await email_chan.send(
                        recipient=notif.recipient,
                        message=notif.message_body,
                        subject="Attendance Alert",
                    )
                else:
                    raise ValueError(f"Unsupported notification channel: {notif.channel}")

            notif.status = NotificationStatus.SENT
            notif.sent_at = datetime.now(UTC)
            notif.error_message = None
        except Exception as exc:
            logger.exception("Failed to deliver notification %s", notif.id)
            notif.retry_count += 1
            if notif.retry_count >= 5:
                notif.status = NotificationStatus.FAILED
                notif.error_message = f"Max retries (5) exceeded: {exc}"
            else:
                delay = 2**notif.retry_count
                notif.scheduled_at = datetime.now(UTC) + timedelta(minutes=delay)
                notif.error_message = f"Attempt {notif.retry_count}/5 failed: {exc}"

        session.add(notif)
        count += 1

    if count > 0:
        await session.commit()

    return count


def render_template(template_str: str, context: dict[str, Any]) -> str:
    from jinja2 import Template
    t = Template(template_str)
    return str(t.render(**context))


def get_fallback_template(trigger_status: str) -> str:
    import os
    filename = "absence.txt" if trigger_status == "absent" else f"{trigger_status}.txt"
    dir_path = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(dir_path, "templates", filename)
    with open(file_path, "r", encoding="utf-8") as f:
        return str(f.read())


def generate_unsubscribe_token(guardian_id: UUID) -> str:
    import jwt

    from backend.app.config import get_settings
    settings = get_settings()
    payload = {
        "sub": str(guardian_id),
        "purpose": "unsubscribe",
        "exp": datetime.now(UTC) + timedelta(days=90),
    }
    return jwt.encode(payload, settings.jwt_secret.get_secret_value(), algorithm="HS256")
