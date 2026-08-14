from __future__ import annotations

import asyncio
import logging
from datetime import UTC, date, datetime, time, timedelta
from typing import cast
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.attendance.decision_table import AttendanceStatus
from backend.app.config import get_settings
from backend.app.models.attendance import (
    AttendanceEvent,
    AttendanceEventOutcome,
    AttendanceOverride,
    AttendanceRecord,
    ExpectedAttendance,
)
from backend.app.models.people import Person, PersonGroup
from backend.app.models.scheduling import (
    AssignmentContext,
    AssignmentScope,
    CalendarDay,
    PersonException,
    Schedule,
    ScheduleAssignment,
    ScheduleRule,
    Shift,
    resolve_schedule_assignment,
)
from backend.app.models.settings import Setting, SettingsVersion
from backend.app.settings.resolver import (
    ResolvedSettings,
    SettingContext,
    SettingValue,
    resolve_settings,
)

logger = logging.getLogger("attendance_tracker")


def _handle_resolver_task_done(
    task: asyncio.Task[None], person_id: UUID, business_date: date
) -> None:
    try:
        task.result()
    except Exception:
        logger.exception(
            "Background resolve task failed for person %s on date %s",
            person_id,
            business_date,
        )


class RedisResolverState:
    """Redis helper for managing debouncing dirty states during attendance resolution."""

    def __init__(self) -> None:
        try:
            self.client: redis.Redis | None = redis.from_url(
                get_settings().redis_url, decode_responses=True
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Redis is not available for resolver: %s", exc)
            self.client = None

    def set_dirty(self, person_id: UUID, business_date: date) -> None:
        if self.client:
            try:
                self.client.set(f"dirty:{person_id}:{business_date}", 1, ex=86400)
            except Exception:  # noqa: BLE001, S110
                pass

    def clear_dirty(self, person_id: UUID, business_date: date) -> bool:
        if self.client:
            try:
                return bool(self.client.delete(f"dirty:{person_id}:{business_date}"))
            except Exception:  # noqa: BLE001, S110
                pass
        return False

    def is_dirty(self, person_id: UUID, business_date: date) -> bool:
        if self.client:
            try:
                return bool(self.client.exists(f"dirty:{person_id}:{business_date}"))
            except Exception:  # noqa: BLE001, S110
                pass
        return False


redis_resolver_state = RedisResolverState()


async def resolve_db_settings(
    db: AsyncSession,
    context: SettingContext,
) -> ResolvedSettings:
    """Retrieve settings and resolve them for context."""
    result = await db.execute(select(Setting))
    db_settings = result.scalars().all()

    values = [
        SettingValue(
            key=s.key,
            scope=s.scope,
            scope_id=s.scope_id,
            value=s.value,
            version=s.version,
        )
        for s in db_settings
    ]

    settings_ver = await db.execute(
        select(SettingsVersion.current_version).where(SettingsVersion.namespace == "global")
    )
    ver = settings_ver.scalar_one_or_none() or 1

    return resolve_settings(values, context, version=ver)


async def resolve(
    session: AsyncSession,
    person_id: UUID,
    business_date: date,
    *,
    as_of: datetime,
) -> None:
    """Resolves and rebuilds attendance records for a specific person and business date.

    Uses SELECT FOR UPDATE on Person to prevent concurrency races.
    """
    # 1. Lock the Person row to serialize concurrent resolution executions
    person_stmt = select(Person).where(Person.id == person_id).with_for_update()
    person = (await session.execute(person_stmt)).scalar_one_or_none()
    if not person:
        logger.warning("Resolver failed: person %s not found", person_id)
        return

    # Check merge pointer
    if person.merged_into_person_id is not None:
        logger.info(
            "Person %s is merged into %s. Redirecting resolution.",
            person_id,
            person.merged_into_person_id,
        )
        # Clear dirty flag on alias and set it on canonical person
        redis_resolver_state.clear_dirty(person_id, business_date)
        redis_resolver_state.set_dirty(person.merged_into_person_id, business_date)
        await resolve(session, person.merged_into_person_id, business_date, as_of=as_of)
        return

    # 2. Clear dirty flag in Redis
    redis_resolver_state.clear_dirty(person_id, business_date)

    # 3. Fetch expected attendance rows
    expected_stmt = select(ExpectedAttendance).where(
        ExpectedAttendance.person_id == person_id,
        ExpectedAttendance.business_date == business_date,
        ExpectedAttendance.voided_at.is_(None),
    )
    expected_rows = (await session.execute(expected_stmt)).scalars().all()

    # 4. Fetch overrides
    override_stmt = select(AttendanceOverride).where(
        AttendanceOverride.person_id == person_id,
        AttendanceOverride.business_date == business_date,
    )
    overrides = (await session.execute(override_stmt)).scalars().all()
    overrides_by_grain = {(o.shift_id, o.period_label): o for o in overrides}

    # 5. Fetch exceptions and calendar days
    exception_stmt = select(PersonException).where(
        PersonException.person_id == person_id,
        PersonException.business_date == business_date,
    )
    exceptions = (await session.execute(exception_stmt)).scalars().all()

    # Get settings for lookback/lookahead
    dummy_context = SettingContext()
    global_settings = await resolve_db_settings(session, dummy_context)
    lookback_mins = global_settings.settings.get("attendance.lookback_minutes", 240)
    lookahead_mins = global_settings.settings.get("attendance.lookahead_minutes", 240)
    lookback = timedelta(minutes=lookback_mins)
    lookahead = timedelta(minutes=lookahead_mins)

    # 6. Fetch events
    # We fetch all events for this person. To cover overnight and lookback/lookahead,
    # we determine a wide interval.
    events: list[AttendanceEvent] = []
    if expected_rows:
        min_start = min(e.expected_start_at for e in expected_rows)
        max_end = max(e.expected_end_at for e in expected_rows)
        event_stmt = select(AttendanceEvent).where(
            AttendanceEvent.person_id == person_id,
            AttendanceEvent.occurred_at >= min_start - lookback,
            AttendanceEvent.occurred_at <= max_end + lookahead,
        )
        events = list((await session.execute(event_stmt)).scalars().all())
    else:
        # No expected rows: retrieve all events that occurred on this business_date in Manila time zone (fallback)
        tz = ZoneInfo("Asia/Manila")
        start_dt = datetime.combine(business_date, time.min).replace(tzinfo=tz)
        end_dt = datetime.combine(business_date, time.max).replace(tzinfo=tz)
        event_stmt = select(AttendanceEvent).where(
            AttendanceEvent.person_id == person_id,
            AttendanceEvent.occurred_at >= start_dt,
            AttendanceEvent.occurred_at <= end_dt,
        )
        events = list((await session.execute(event_stmt)).scalars().all())

    # Map events to expected rows (absolute UTC interval containment)
    events_by_expected: dict[UUID, list[AttendanceEvent]] = {}
    matched_event_ids: set[int] = set()

    for expected in expected_rows:
        events_by_expected[expected.id] = []
        for event in events:
            if (
                event.occurred_at >= expected.expected_start_at - lookback
                and event.occurred_at <= expected.expected_end_at + lookahead
            ):
                events_by_expected[expected.id].append(event)
                matched_event_ids.add(event.id)

                # Set business_date and shift_id on event if not already set or mismatched
                if event.business_date != business_date or event.shift_id != expected.shift_id:
                    event.business_date = business_date
                    event.shift_id = expected.shift_id
                    session.add(event)

    # Unmatched events that occurred on this day get updated with business_date
    for event in events:
        if event.id not in matched_event_ids and event.business_date != business_date:
            event.business_date = business_date
            session.add(event)

    # 7. Classify and write records
    # Fetch existing records to compare resolved_at
    existing_rec_stmt = select(AttendanceRecord).where(
        AttendanceRecord.person_id == person_id,
        AttendanceRecord.business_date == business_date,
    )
    existing_records = (await session.execute(existing_rec_stmt)).scalars().all()
    existing_by_grain = {(r.shift_id, r.period_label): r for r in existing_records}

    resolved_grains: set[tuple[UUID, str]] = set()
    for grain, rec in existing_by_grain.items():
        if rec.resolved_at > as_of:
            resolved_grains.add(grain)

    if not expected_rows:
        # Rule 4: present_unscheduled
        # Only create a record if we have events that fall on this day
        accepted_events = [ev for ev in events if ev.outcome == AttendanceEventOutcome.ACCEPTED]
        if accepted_events:
            sorted_events = sorted(accepted_events, key=lambda ev: ev.occurred_at)
            first_event = sorted_events[0]
            last_event = sorted_events[-1] if len(sorted_events) > 1 else None

            # Check min_dwell_minutes
            min_dwell = global_settings.settings.get("attendance.min_dwell_minutes", 5)
            if (
                last_event
                and (last_event.occurred_at - first_event.occurred_at).total_seconds()
                < min_dwell * 60
            ):
                last_event = None

            # Dummy shift_id = UUID("00000000-0000-0000-0000-000000000000") for unscheduled
            dummy_shift_id = UUID("00000000-0000-0000-0000-000000000000")
            period_label = ""
            existing = existing_by_grain.get((dummy_shift_id, period_label))
            if existing and existing.resolved_at > as_of:
                # Stale out-of-order execution, skip
                return

            status = AttendanceStatus.PRESENT_UNSCHEDULED
            override = overrides_by_grain.get((dummy_shift_id, period_label))
            if override:
                status = override.status

            flags = {
                "was_late": False,
                "left_early": False,
                "location_mismatch": False,
                "was_backdated": any(ev.was_backdated for ev in accepted_events),
                "auto_closed": False,
            }

            record = existing or AttendanceRecord(
                person_id=person_id,
                business_date=business_date,
                shift_id=dummy_shift_id,
                period_label=period_label,
            )
            record.status = status
            record.first_event_id = first_event.id
            record.last_event_id = last_event.id if last_event else None
            record.late_minutes = None
            record.flags = cast(dict[str, object], flags)
            record.resolved_at = as_of
            record.override_id = override.id if override else None
            record.expected_attendance_id = None
            session.add(record)
            resolved_grains.add((dummy_shift_id, period_label))
    else:
        # Loop expected rows
        for expected in expected_rows:
            existing = existing_by_grain.get((expected.shift_id, expected.period_label))
            if existing and existing.resolved_at > as_of:
                # Stale out-of-order execution, skip
                continue

            # Load settings scoped to this location
            context = SettingContext(location_id=expected.location_id)
            settings = await resolve_db_settings(session, context)

            grace_in = settings.settings.get("attendance.grace_in_minutes", 10)
            grace_out = settings.settings.get("attendance.grace_out_minutes", 10)
            absent_after = settings.settings.get("attendance.absent_after_minutes", 60)
            min_dwell = settings.settings.get("attendance.min_dwell_minutes", 5)
            auto_close_enabled = settings.settings.get("attendance.auto_close_enabled", False)
            auto_close_mins = settings.settings.get("attendance.auto_close_minutes", 120)

            # Get matching events
            matching_events = [
                ev
                for ev in events_by_expected[expected.id]
                if ev.outcome == AttendanceEventOutcome.ACCEPTED
            ]

            # Pair events
            first_event = None
            last_event = None
            if matching_events:
                sorted_events = sorted(matching_events, key=lambda ev: ev.occurred_at)
                first_event = sorted_events[0]
                if len(sorted_events) > 1:
                    last_event = sorted_events[-1]
                    if (
                        last_event.occurred_at - first_event.occurred_at
                    ).total_seconds() < min_dwell * 60:
                        last_event = None

            # Calendar Day check
            cal_day_stmt = select(CalendarDay).where(
                CalendarDay.location_id == expected.location_id,
                CalendarDay.business_date == business_date,
            )
            cal_day = (await session.execute(cal_day_stmt)).scalar_one_or_none()

            # Exception check
            exc = exceptions[0] if exceptions else None

            # Override check
            override = overrides_by_grain.get((expected.shift_id, expected.period_label))

            # Apply Decision Table Rules
            status = AttendanceStatus.PENDING
            late_minutes = None
            auto_closed = False

            if override:
                status = override.status
            elif exc:
                status = AttendanceStatus.EXCUSED
            elif cal_day and not cal_day.is_working_day:
                status = AttendanceStatus.HOLIDAY
            elif not expected.is_working_day:
                status = AttendanceStatus.NOT_SCHEDULED
            elif not first_event:
                # No arrival yet
                if as_of < expected.expected_start_at + timedelta(minutes=absent_after):
                    status = AttendanceStatus.PENDING
                else:
                    status = AttendanceStatus.ABSENT
            else:
                # Arrived
                # On time check
                if first_event.occurred_at <= expected.expected_start_at + timedelta(
                    minutes=grace_in
                ):
                    status = AttendanceStatus.ON_TIME
                else:
                    # Late
                    status = AttendanceStatus.LATE
                    late_minutes = int(
                        (
                            first_event.occurred_at
                            - (expected.expected_start_at + timedelta(minutes=grace_in))
                        ).total_seconds()
                        / 60
                    )
                    late_minutes = max(late_minutes, 0)

                # Check auto-close / incomplete
                if (
                    not last_event
                    and auto_close_enabled
                    and as_of > expected.expected_end_at + timedelta(minutes=auto_close_mins)
                ):
                    status = AttendanceStatus.INCOMPLETE
                    auto_closed = True

            # Determine flags
            flags = {
                "was_late": first_event is not None
                and first_event.occurred_at
                > expected.expected_start_at + timedelta(minutes=grace_in),
                "left_early": last_event is not None
                and last_event.occurred_at
                < expected.expected_end_at - timedelta(minutes=grace_out),
                "location_mismatch": any(
                    ev.location_id != expected.location_id
                    for ev in matching_events
                    if ev.location_id
                ),
                "was_backdated": any(ev.was_backdated for ev in matching_events),
                "auto_closed": auto_closed,
            }

            # Create or update record
            record = existing or AttendanceRecord(
                person_id=person_id,
                business_date=business_date,
                shift_id=expected.shift_id,
                period_label=expected.period_label,
            )
            record.expected_attendance_id = expected.id
            record.override_id = override.id if override else None
            record.status = status
            record.first_event_id = first_event.id if first_event else None
            record.last_event_id = last_event.id if last_event else None
            record.late_minutes = late_minutes
            record.flags = cast(dict[str, object], flags)
            record.resolved_at = as_of
            session.add(record)
            resolved_grains.add((expected.shift_id, expected.period_label))

    # Delete any stale/obsolete records for this person and date that were not resolved in this pass
    for grain, rec in existing_by_grain.items():
        if grain not in resolved_grains:
            await session.delete(rec)

    await session.commit()

    # 8. Re-check dirty flag. If set again, re-enqueue
    if redis_resolver_state.is_dirty(person_id, business_date):
        logger.info("Person %s still dirty. Re-enqueuing resolve task.", person_id)
        task = asyncio.create_task(resolve_with_new_session(person_id, business_date, as_of=as_of))
        task.add_done_callback(lambda t: _handle_resolver_task_done(t, person_id, business_date))


async def resolve_with_new_session(
    person_id: UUID, business_date: date, *, as_of: datetime
) -> None:
    """Helper to run resolve with a fresh database session in an asyncio background task."""
    from backend.app.db.session import get_session_factory

    async_session = get_session_factory()
    async with async_session() as session:
        await resolve(session, person_id, business_date, as_of=as_of)


async def expand_schedules(
    session: AsyncSession,
    *,
    person_ids: list[UUID] | None = None,
    start_date: date,
    end_date: date,
    allow_past: bool = False,
) -> None:
    """Generates ExpectedAttendance entries for a set of people across a date range.

    Voided expected rows are kept/versioned (voided_at timestamp updated).
    """
    from backend.app.models.people import Person

    # 1. Fetch active people
    query = select(Person).where(Person.is_active.is_(True))
    if person_ids is not None:
        query = query.where(Person.id.in_(person_ids))
    people = (await session.execute(query)).scalars().all()

    # 2. Fetch all schedule assignments and their rules/shifts
    assignments = list((await session.execute(select(ScheduleAssignment))).scalars().all())
    schedules = {s.id: s for s in (await session.execute(select(Schedule))).scalars().all()}
    rules = (await session.execute(select(ScheduleRule))).scalars().all()
    shifts = {sh.id: sh for sh in (await session.execute(select(Shift))).scalars().all()}

    # Group rules by schedule
    rules_by_schedule: dict[UUID, list[ScheduleRule]] = {}
    for rule in rules:
        rules_by_schedule.setdefault(rule.schedule_id, []).append(rule)

    # 3. Process each person and date
    today = datetime.now(UTC).astimezone(ZoneInfo("Asia/Manila")).date()

    for person in people:
        # Fetch active groups for person
        group_stmt = select(PersonGroup).where(PersonGroup.person_id == person.id)
        memberships = (await session.execute(group_stmt)).scalars().all()

        current_date = start_date
        while current_date <= end_date:
            if current_date < today and not allow_past:
                # Do not write past rows unless allow_past is explicitly True
                current_date += timedelta(days=1)
                continue

            # Build group list for context
            active_memberships = [m for m in memberships if m.is_active_on(current_date)]
            group_ids = tuple(m.group_id for m in active_memberships)

            # Determine primary location
            location_id = None
            primary_membership = [m for m in active_memberships if m.is_primary]
            if primary_membership:
                # Check location of schedule assignment if scoped to location
                pass

            # If no primary location resolved, default to None or search location assignments
            # Let's find applicable assignment. Since context has location_id, we can look up
            # any location assignment that applies, or try location_id=None.
            # To be thorough, we evaluate the assignments.
            context = AssignmentContext(
                person_id=person.id,
                group_ids=group_ids,
                location_id=location_id or UUID("00000000-0000-0000-0000-000000000000"),
            )

            resolved_assignment = resolve_schedule_assignment(assignments, context, current_date)
            if not resolved_assignment:
                # Clear/void existing expected row if it exists
                void_stmt = select(ExpectedAttendance).where(
                    ExpectedAttendance.person_id == person.id,
                    ExpectedAttendance.business_date == current_date,
                    ExpectedAttendance.voided_at.is_(None),
                )
                to_void = (await session.execute(void_stmt)).scalars().all()
                if to_void:
                    for v in to_void:
                        v.voided_at = datetime.now(UTC)
                        session.add(v)
                    redis_resolver_state.set_dirty(person.id, current_date)

                current_date += timedelta(days=1)
                continue

            schedule = schedules.get(resolved_assignment.schedule_id)
            if not schedule:
                current_date += timedelta(days=1)
                continue

            # Lookup rule for weekday (0 = Monday, 6 = Sunday)
            weekday = current_date.weekday()
            schedule_rules = rules_by_schedule.get(schedule.id, [])
            matched_rule = next((r for r in schedule_rules if r.weekday == weekday), None)

            if not matched_rule:
                # Clear/void existing
                void_stmt = select(ExpectedAttendance).where(
                    ExpectedAttendance.person_id == person.id,
                    ExpectedAttendance.business_date == current_date,
                    ExpectedAttendance.voided_at.is_(None),
                )
                to_void = (await session.execute(void_stmt)).scalars().all()
                if to_void:
                    for v in to_void:
                        v.voided_at = datetime.now(UTC)
                        session.add(v)
                    redis_resolver_state.set_dirty(person.id, current_date)

                current_date += timedelta(days=1)
                continue

            shift = shifts.get(matched_rule.shift_id) if matched_rule.shift_id else None

            # Fallback times if rule/shift has no times but we still have an expected non-working rule
            is_working_day = matched_rule.is_working_day and (shift is not None)
            starts_at = shift.starts_at if shift else time(8, 0)
            ends_at = shift.ends_at if shift else time(17, 0)
            crosses_midnight = shift.crosses_midnight if shift else False
            absent_after_mins = shift.absent_after_minutes if shift else 60

            # Timezone
            tz_str = schedule.timezone or "Asia/Manila"
            tz = ZoneInfo(tz_str)

            # Calculate UTC start / end
            start_local = datetime.combine(current_date, starts_at).replace(tzinfo=tz)
            if crosses_midnight or ends_at <= starts_at:
                end_date_val = current_date + timedelta(days=1)
            else:
                end_date_val = current_date
            end_local = datetime.combine(end_date_val, ends_at).replace(tzinfo=tz)

            absent_after_at_local = start_local + timedelta(minutes=absent_after_mins)

            expected_start_at = start_local.astimezone(UTC)
            expected_end_at = end_local.astimezone(UTC)
            absent_after_at = absent_after_at_local.astimezone(UTC)

            # Determine natural key matches
            nk_stmt = select(ExpectedAttendance).where(
                ExpectedAttendance.person_id == person.id,
                ExpectedAttendance.business_date == current_date,
                ExpectedAttendance.shift_id
                == (matched_rule.shift_id or UUID("00000000-0000-0000-0000-000000000000")),
                ExpectedAttendance.period_label == matched_rule.period_label,
            )
            existing_expected = (await session.execute(nk_stmt)).scalar_one_or_none()

            # Get location_id from assignment
            loc_id = (
                resolved_assignment.scope_id
                if resolved_assignment.scope == AssignmentScope.LOCATION
                else None
            )

            # Void other expected rows for the same date
            void_stmt = select(ExpectedAttendance).where(
                ExpectedAttendance.person_id == person.id,
                ExpectedAttendance.business_date == current_date,
                ExpectedAttendance.id != (existing_expected.id if existing_expected else uuid4()),
                ExpectedAttendance.voided_at.is_(None),
            )
            to_void = (await session.execute(void_stmt)).scalars().all()
            dirty_needed = False
            if to_void:
                for v in to_void:
                    v.voided_at = datetime.now(UTC)
                    session.add(v)
                dirty_needed = True

            expected = existing_expected or ExpectedAttendance(
                person_id=person.id,
                business_date=current_date,
                shift_id=matched_rule.shift_id or UUID("00000000-0000-0000-0000-000000000000"),
                period_label=matched_rule.period_label,
            )
            
            # Check if expected row changed
            if (
                not existing_expected
                or expected.location_id != loc_id
                or expected.schedule_id != schedule.id
                or expected.expected_start_at != expected_start_at
                or expected.expected_end_at != expected_end_at
                or expected.absent_after_at != absent_after_at
                or expected.is_working_day != is_working_day
                or expected.voided_at is not None
            ):
                expected.location_id = loc_id
                expected.schedule_id = schedule.id
                expected.expected_start_at = expected_start_at
                expected.expected_end_at = expected_end_at
                expected.absent_after_at = absent_after_at
                expected.is_working_day = is_working_day
                expected.voided_at = None  # Ensure unvoided if matched
                session.add(expected)
                dirty_needed = True

            if dirty_needed:
                redis_resolver_state.set_dirty(person.id, current_date)

            current_date += timedelta(days=1)

    await session.commit()


async def rebuild_all_attendance(
    session: AsyncSession,
    *,
    as_of: datetime,
) -> None:
    """Rebuilds the entire attendance records cache.

    Truncates attendance_records, queries all expected rows and unmatched events,
    and runs the resolver.
    """
    # 1. Rebuild cache incrementally via resolver (which handles stale record deletion)

    # 2. Find all unique (person_id, business_date) from active expected rows
    expected_stmt = (
        select(ExpectedAttendance.person_id, ExpectedAttendance.business_date)
        .where(ExpectedAttendance.voided_at.is_(None))
        .distinct()
    )
    expected_pairs = (await session.execute(expected_stmt)).all()

    # 3. Find all unique (person_id, business_date) from attendance events
    event_stmt = (
        select(AttendanceEvent.person_id, AttendanceEvent.business_date)
        .where(AttendanceEvent.person_id.is_not(None))
        .distinct()
    )
    event_pairs = (await session.execute(event_stmt)).all()

    # Combine pairs
    all_pairs = set(expected_pairs) | set(event_pairs)

    # 4. Resolve each pair
    for person_id, business_date in all_pairs:
        if person_id is not None and business_date is not None:
            await resolve(session, person_id, business_date, as_of=as_of)
