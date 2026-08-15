from __future__ import annotations

import logging
from datetime import UTC, date, datetime, time
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from sqlalchemy import and_, case, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from backend.app.attendance.decision_table import AttendanceStatus
from backend.app.models.attendance import (
    AttendanceEvent,
    AttendanceEventOutcome,
    AttendanceOverride,
    AttendanceRecord,
    ExpectedAttendance,
)
from backend.app.models.devices import Device, DeviceHeartbeat, Location
from backend.app.models.people import Group, Person, PersonGroup

logger = logging.getLogger("attendance_tracker")


async def get_daily_register_data(
    session: AsyncSession,
    date_from: date,
    date_to: date,
    group_id: UUID | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    evt_in = aliased(AttendanceEvent)
    evt_out = aliased(AttendanceEvent)

    # Let's adjust shifts name selection to use a proper sqlalchemy join
    # Shift table can be joined directly
    stmt = (
        select(
            AttendanceRecord.id,
            AttendanceRecord.person_id,
            AttendanceRecord.override_id,
            Person.display_name.label("name"),
            Person.external_id,
            Group.name.label("group_name"),
            AttendanceRecord.shift_id,
            AttendanceRecord.business_date,
            ExpectedAttendance.expected_start_at,
            ExpectedAttendance.expected_end_at,
            evt_in.occurred_at.label("actual_in"),
            evt_out.occurred_at.label("actual_out"),
            AttendanceRecord.late_minutes,
            AttendanceRecord.status,
            AttendanceRecord.flags,
        )
        .join(Person, AttendanceRecord.person_id == Person.id)
        .outerjoin(
            ExpectedAttendance, AttendanceRecord.expected_attendance_id == ExpectedAttendance.id
        )
        .outerjoin(evt_in, AttendanceRecord.first_event_id == evt_in.id)
        .outerjoin(evt_out, AttendanceRecord.last_event_id == evt_out.id)
        .outerjoin(
            PersonGroup,
            and_(
                PersonGroup.person_id == Person.id,
                PersonGroup.effective_from <= AttendanceRecord.business_date,
                or_(
                    PersonGroup.effective_to.is_(None),
                    PersonGroup.effective_to >= AttendanceRecord.business_date,
                ),
                PersonGroup.is_primary == True,
            ),
        )
        .outerjoin(Group, PersonGroup.group_id == Group.id)
        .where(AttendanceRecord.business_date.between(date_from, date_to))
        .order_by(AttendanceRecord.business_date.asc(), Person.display_name.asc())
    )

    if group_id:
        stmt = stmt.where(PersonGroup.group_id == group_id)

    result = await session.execute(stmt)
    rows = []
    # To get shift names safely without breaking on UUID("00000000-0000-0000-0000-000000000000") for unscheduled shifts:
    # We query the shifts name separately or join on shifts table.
    shifts_res = await session.execute(sa.text("SELECT id, name FROM shifts"))
    shift_names = {r[0]: r[1] for r in shifts_res.all()}

    for r in result.mappings().all():
        row = dict(r)
        row["shift_name"] = shift_names.get(row["shift_id"], "No Shift")

        flags_dict = row.get("flags") or {}
        flag_list = [k for k, v in flags_dict.items() if v]
        row["flags_str"] = ", ".join(flag_list) if flag_list else "None"
        rows.append(row)

    headers = [
        "business_date",
        "external_id",
        "name",
        "group_name",
        "shift_name",
        "expected_start_at",
        "expected_end_at",
        "actual_in",
        "actual_out",
        "late_minutes",
        "status",
        "flags_str",
    ]
    return rows, headers


async def get_timesheet_data(
    session: AsyncSession,
    date_from: date,
    date_to: date,
    person_id: UUID | None = None,
    group_id: UUID | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    evt_in = aliased(AttendanceEvent)
    evt_out = aliased(AttendanceEvent)

    stmt = (
        select(
            AttendanceRecord.id,
            AttendanceRecord.person_id,
            AttendanceRecord.override_id,
            Person.display_name.label("name"),
            Person.external_id,
            Group.name.label("group_name"),
            AttendanceRecord.shift_id,
            AttendanceRecord.business_date,
            ExpectedAttendance.expected_start_at,
            ExpectedAttendance.expected_end_at,
            evt_in.occurred_at.label("actual_in"),
            evt_out.occurred_at.label("actual_out"),
            AttendanceRecord.late_minutes,
            AttendanceRecord.status,
            AttendanceRecord.flags,
        )
        .join(Person, AttendanceRecord.person_id == Person.id)
        .outerjoin(
            ExpectedAttendance, AttendanceRecord.expected_attendance_id == ExpectedAttendance.id
        )
        .outerjoin(evt_in, AttendanceRecord.first_event_id == evt_in.id)
        .outerjoin(evt_out, AttendanceRecord.last_event_id == evt_out.id)
        .outerjoin(
            PersonGroup,
            and_(
                PersonGroup.person_id == Person.id,
                PersonGroup.effective_from <= AttendanceRecord.business_date,
                or_(
                    PersonGroup.effective_to.is_(None),
                    PersonGroup.effective_to >= AttendanceRecord.business_date,
                ),
                PersonGroup.is_primary == True,
            ),
        )
        .outerjoin(Group, PersonGroup.group_id == Group.id)
        .where(AttendanceRecord.business_date.between(date_from, date_to))
        .order_by(Person.display_name.asc(), AttendanceRecord.business_date.asc())
    )

    if person_id:
        stmt = stmt.where(Person.id == person_id)
    if group_id:
        stmt = stmt.where(PersonGroup.group_id == group_id)

    result = await session.execute(stmt)
    rows = []
    shifts_res = await session.execute(sa.text("SELECT id, name FROM shifts"))
    shift_names = {r[0]: r[1] for r in shifts_res.all()}

    for r in result.mappings().all():
        row = dict(r)
        row["shift_name"] = shift_names.get(row["shift_id"], "No Shift")

        flags_dict = row.get("flags") or {}
        flag_list = [k for k, v in flags_dict.items() if v]
        row["flags_str"] = ", ".join(flag_list) if flag_list else "None"
        rows.append(row)

    headers = [
        "name",
        "external_id",
        "group_name",
        "business_date",
        "shift_name",
        "expected_start_at",
        "expected_end_at",
        "actual_in",
        "actual_out",
        "late_minutes",
        "status",
        "flags_str",
    ]
    return rows, headers


async def get_payroll_summary_data(
    session: AsyncSession,
    date_from: date,
    date_to: date,
    group_id: UUID | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    stmt = (
        select(
            Person.display_name.label("name"),
            Person.external_id,
            func.coalesce(Group.name, "No Group").label("group_name"),
            func.count(
                case(
                    (
                        and_(
                            ExpectedAttendance.id.is_not(None),
                            ExpectedAttendance.is_working_day == True,
                        ),
                        1,
                    ),
                    else_=None,
                )
            ).label("scheduled_days"),
            func.count(
                case(
                    (
                        AttendanceRecord.status.in_(
                            [
                                AttendanceStatus.ON_TIME,
                                AttendanceStatus.LATE,
                                AttendanceStatus.COMPLETE,
                                AttendanceStatus.INCOMPLETE,
                                AttendanceStatus.PRESENT_UNSCHEDULED,
                            ]
                        ),
                        1,
                    ),
                    else_=None,
                )
            ).label("days_present"),
            func.count(
                case((AttendanceRecord.status == AttendanceStatus.ABSENT, 1), else_=None)
            ).label("days_absent"),
            func.count(
                case((AttendanceRecord.status == AttendanceStatus.EXCUSED, 1), else_=None)
            ).label("days_excused"),
            func.count(
                case(
                    (
                        or_(
                            AttendanceRecord.status == AttendanceStatus.LATE,
                            AttendanceRecord.late_minutes > 0,
                        ),
                        1,
                    ),
                    else_=None,
                )
            ).label("total_lates"),
            func.sum(func.coalesce(AttendanceRecord.late_minutes, 0)).label("total_late_minutes"),
        )
        .join(Person, AttendanceRecord.person_id == Person.id)
        .outerjoin(
            ExpectedAttendance, AttendanceRecord.expected_attendance_id == ExpectedAttendance.id
        )
        .outerjoin(
            PersonGroup,
            and_(
                PersonGroup.person_id == Person.id,
                PersonGroup.effective_from <= date_to,
                or_(
                    PersonGroup.effective_to.is_(None),
                    PersonGroup.effective_to >= date_from,
                ),
                PersonGroup.is_primary == True,
            ),
        )
        .outerjoin(Group, PersonGroup.group_id == Group.id)
        .where(AttendanceRecord.business_date.between(date_from, date_to))
        .group_by(Person.id, Person.display_name, Person.external_id, Group.name)
        .order_by(Person.display_name.asc())
    )

    if group_id:
        stmt = stmt.where(PersonGroup.group_id == group_id)

    result = await session.execute(stmt)
    rows = [dict(r) for r in result.mappings().all()]
    for r in rows:
        if r["total_late_minutes"] is None:
            r["total_late_minutes"] = 0
    headers = [
        "name",
        "external_id",
        "group_name",
        "scheduled_days",
        "days_present",
        "days_absent",
        "days_excused",
        "total_lates",
        "total_late_minutes",
    ]
    return rows, headers


async def get_tardiness_data(
    session: AsyncSession,
    date_from: date,
    date_to: date,
    group_id: UUID | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    evt_in = aliased(AttendanceEvent)

    stmt = (
        select(
            AttendanceRecord.id,
            AttendanceRecord.business_date,
            Person.display_name.label("name"),
            Person.external_id,
            Group.name.label("group_name"),
            AttendanceRecord.shift_id,
            ExpectedAttendance.expected_start_at,
            evt_in.occurred_at.label("actual_in"),
            AttendanceRecord.late_minutes,
        )
        .join(Person, AttendanceRecord.person_id == Person.id)
        .outerjoin(
            ExpectedAttendance, AttendanceRecord.expected_attendance_id == ExpectedAttendance.id
        )
        .outerjoin(evt_in, AttendanceRecord.first_event_id == evt_in.id)
        .outerjoin(
            PersonGroup,
            and_(
                PersonGroup.person_id == Person.id,
                PersonGroup.effective_from <= AttendanceRecord.business_date,
                or_(
                    PersonGroup.effective_to.is_(None),
                    PersonGroup.effective_to >= AttendanceRecord.business_date,
                ),
                PersonGroup.is_primary == True,
            ),
        )
        .outerjoin(Group, PersonGroup.group_id == Group.id)
        .where(
            and_(
                AttendanceRecord.business_date.between(date_from, date_to),
                or_(
                    AttendanceRecord.status == AttendanceStatus.LATE,
                    AttendanceRecord.late_minutes > 0,
                ),
            )
        )
        .order_by(AttendanceRecord.business_date.asc(), Person.display_name.asc())
    )

    if group_id:
        stmt = stmt.where(PersonGroup.group_id == group_id)

    result = await session.execute(stmt)
    rows = []
    shifts_res = await session.execute(sa.text("SELECT id, name FROM shifts"))
    shift_names = {r[0]: r[1] for r in shifts_res.all()}

    for r in result.mappings().all():
        row = dict(r)
        row["shift_name"] = shift_names.get(row["shift_id"], "No Shift")
        rows.append(row)

    headers = [
        "business_date",
        "name",
        "external_id",
        "group_name",
        "shift_name",
        "expected_start_at",
        "actual_in",
        "late_minutes",
    ]
    return rows, headers


async def get_absence_data(
    session: AsyncSession,
    date_from: date,
    date_to: date,
    group_id: UUID | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    stmt = (
        select(
            AttendanceRecord.id,
            AttendanceRecord.business_date,
            Person.display_name.label("name"),
            Person.external_id,
            Group.name.label("group_name"),
            AttendanceRecord.shift_id,
            AttendanceOverride.reason.label("override_reason"),
        )
        .join(Person, AttendanceRecord.person_id == Person.id)
        .outerjoin(AttendanceOverride, AttendanceRecord.override_id == AttendanceOverride.id)
        .outerjoin(
            PersonGroup,
            and_(
                PersonGroup.person_id == Person.id,
                PersonGroup.effective_from <= AttendanceRecord.business_date,
                or_(
                    PersonGroup.effective_to.is_(None),
                    PersonGroup.effective_to >= AttendanceRecord.business_date,
                ),
                PersonGroup.is_primary == True,
            ),
        )
        .outerjoin(Group, PersonGroup.group_id == Group.id)
        .where(
            and_(
                AttendanceRecord.business_date.between(date_from, date_to),
                AttendanceRecord.status == AttendanceStatus.ABSENT,
            )
        )
        .order_by(AttendanceRecord.business_date.asc(), Person.display_name.asc())
    )

    if group_id:
        stmt = stmt.where(PersonGroup.group_id == group_id)

    result = await session.execute(stmt)
    rows = []
    shifts_res = await session.execute(sa.text("SELECT id, name FROM shifts"))
    shift_names = {r[0]: r[1] for r in shifts_res.all()}

    for r in result.mappings().all():
        row = dict(r)
        row["shift_name"] = shift_names.get(row["shift_id"], "No Shift")
        row["override_reason"] = row.get("override_reason") or "N/A"
        rows.append(row)

    headers = [
        "business_date",
        "name",
        "external_id",
        "group_name",
        "shift_name",
        "override_reason",
    ]
    return rows, headers


async def get_truancy_data(
    session: AsyncSession,
    date_from: date,
    date_to: date,
    group_id: UUID | None = None,
    min_absences: int = 3,
) -> tuple[list[dict[str, Any]], list[str]]:
    stmt = (
        select(
            Person.display_name.label("name"),
            Person.external_id,
            func.coalesce(Group.name, "No Group").label("group_name"),
            func.count(AttendanceRecord.id).label("absence_count"),
            func.string_agg(
                func.to_char(AttendanceRecord.business_date, "YYYY-MM-DD"), ", "
            ).label("absent_dates"),
        )
        .join(Person, AttendanceRecord.person_id == Person.id)
        .outerjoin(
            PersonGroup,
            and_(
                PersonGroup.person_id == Person.id,
                PersonGroup.effective_from <= date_to,
                or_(
                    PersonGroup.effective_to.is_(None),
                    PersonGroup.effective_to >= date_from,
                ),
                PersonGroup.is_primary == True,
            ),
        )
        .outerjoin(Group, PersonGroup.group_id == Group.id)
        .where(
            and_(
                AttendanceRecord.business_date.between(date_from, date_to),
                AttendanceRecord.status == AttendanceStatus.ABSENT,
            )
        )
        .group_by(Person.id, Person.display_name, Person.external_id, Group.name)
        .having(func.count(AttendanceRecord.id) >= min_absences)
        .order_by(desc("absence_count"), Person.display_name.asc())
    )

    if group_id:
        stmt = stmt.where(PersonGroup.group_id == group_id)

    result = await session.execute(stmt)
    rows = [dict(r) for r in result.mappings().all()]
    headers = [
        "name",
        "external_id",
        "group_name",
        "absence_count",
        "absent_dates",
    ]
    return rows, headers


async def get_perfect_attendance_data(
    session: AsyncSession,
    date_from: date,
    date_to: date,
    group_id: UUID | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    stmt = (
        select(
            Person.display_name.label("name"),
            Person.external_id,
            func.coalesce(Group.name, "No Group").label("group_name"),
            func.count(
                case(
                    (
                        and_(
                            ExpectedAttendance.id.is_not(None),
                            ExpectedAttendance.is_working_day == True,
                        ),
                        1,
                    ),
                    else_=None,
                )
            ).label("scheduled_days"),
            func.count(
                case(
                    (
                        AttendanceRecord.status.in_(
                            [
                                AttendanceStatus.ON_TIME,
                                AttendanceStatus.COMPLETE,
                            ]
                        ),
                        1,
                    ),
                    else_=None,
                )
            ).label("days_present"),
        )
        .join(Person, AttendanceRecord.person_id == Person.id)
        .outerjoin(
            ExpectedAttendance, AttendanceRecord.expected_attendance_id == ExpectedAttendance.id
        )
        .outerjoin(
            PersonGroup,
            and_(
                PersonGroup.person_id == Person.id,
                PersonGroup.effective_from <= date_to,
                or_(
                    PersonGroup.effective_to.is_(None),
                    PersonGroup.effective_to >= date_from,
                ),
                PersonGroup.is_primary == True,
            ),
        )
        .outerjoin(Group, PersonGroup.group_id == Group.id)
        .where(AttendanceRecord.business_date.between(date_from, date_to))
        .group_by(Person.id, Person.display_name, Person.external_id, Group.name)
        .having(
            and_(
                func.count(
                    case(
                        (
                            and_(
                                ExpectedAttendance.id.is_not(None),
                                ExpectedAttendance.is_working_day == True,
                            ),
                            1,
                        ),
                        else_=None,
                    )
                )
                > 0,
                # count(absent) = 0
                func.count(
                    case((AttendanceRecord.status == AttendanceStatus.ABSENT, 1), else_=None)
                )
                == 0,
                # count(late) = 0
                func.count(
                    case(
                        (
                            or_(
                                AttendanceRecord.status == AttendanceStatus.LATE,
                                AttendanceRecord.late_minutes > 0,
                            ),
                            1,
                        ),
                        else_=None,
                    )
                )
                == 0,
            )
        )
        .order_by(Person.display_name.asc())
    )

    if group_id:
        stmt = stmt.where(PersonGroup.group_id == group_id)

    result = await session.execute(stmt)
    rows = [dict(r) for r in result.mappings().all()]
    headers = [
        "name",
        "external_id",
        "group_name",
        "scheduled_days",
        "days_present",
    ]
    return rows, headers


async def get_headcount_by_hour_data(
    session: AsyncSession,
    date_from: date,
    date_to: date,
) -> tuple[list[dict[str, Any]], list[str]]:
    stmt = (
        select(
            func.extract(
                "hour", func.timezone("Asia/Manila", AttendanceEvent.occurred_at)
            ).label("hour"),
            func.count(case((AttendanceEvent.direction == "in", 1), else_=None)).label("in_count"),
            func.count(case((AttendanceEvent.direction == "out", 1), else_=None)).label(
                "out_count"
            ),
        )
        .where(
            and_(
                AttendanceEvent.outcome == AttendanceEventOutcome.ACCEPTED,
                AttendanceEvent.occurred_at
                >= datetime.combine(date_from, time.min).replace(
                    tzinfo=ZoneInfo("Asia/Manila")
                ),
                AttendanceEvent.occurred_at
                <= datetime.combine(date_to, time.max).replace(
                    tzinfo=ZoneInfo("Asia/Manila")
                ),
            )
        )
        .group_by(
            func.extract("hour", func.timezone("Asia/Manila", AttendanceEvent.occurred_at))
        )
        .order_by("hour")
    )

    result = await session.execute(stmt)
    rows_map = {
        int(r.hour): {
            "hour": int(r.hour),
            "in_count": r.in_count,
            "out_count": r.out_count,
            "total_count": r.in_count + r.out_count,
        }
        for r in result.all()
    }

    rows = []
    for h in range(24):
        rows.append(
            rows_map.get(
                h,
                {
                    "hour": h,
                    "in_count": 0,
                    "out_count": 0,
                    "total_count": 0,
                },
            )
        )

    headers = [
        "hour",
        "in_count",
        "out_count",
        "total_count",
    ]
    return rows, headers


async def get_muster_roll_data(
    session: AsyncSession,
) -> tuple[list[dict[str, Any]], list[str]]:
    tz = ZoneInfo("Asia/Manila")
    now_local = datetime.now(tz)
    start_of_today = datetime.combine(now_local.date(), time.min).replace(tzinfo=tz)

    subq = (
        select(
            AttendanceEvent.person_id,
            AttendanceEvent.direction,
            AttendanceEvent.occurred_at,
            AttendanceEvent.location_id,
            AttendanceEvent.device_id,
        )
        .where(
            and_(
                AttendanceEvent.outcome == AttendanceEventOutcome.ACCEPTED,
                AttendanceEvent.occurred_at >= start_of_today,
                AttendanceEvent.person_id.is_not(None),
            )
        )
        .order_by(AttendanceEvent.person_id, AttendanceEvent.occurred_at.desc())
        .distinct(AttendanceEvent.person_id)
        .subquery()
    )

    stmt = (
        select(
            Person.display_name.label("name"),
            Person.external_id,
            Group.name.label("group_name"),
            subq.c.occurred_at.label("checked_in_at"),
            Location.name.label("location_name"),
            Device.token_display_prefix.label("device_name"),
        )
        .join(Person, subq.c.person_id == Person.id)
        .outerjoin(Location, subq.c.location_id == Location.id)
        .outerjoin(Device, subq.c.device_id == Device.id)
        .outerjoin(
            PersonGroup,
            and_(
                PersonGroup.person_id == Person.id,
                PersonGroup.effective_from <= now_local.date(),
                or_(
                    PersonGroup.effective_to.is_(None),
                    PersonGroup.effective_to >= now_local.date(),
                ),
                PersonGroup.is_primary == True,
            ),
        )
        .outerjoin(Group, PersonGroup.group_id == Group.id)
        .where(and_(subq.c.direction == "in", Person.is_active == True))
        .order_by(Person.display_name.asc())
    )

    result = await session.execute(stmt)
    rows = [dict(r) for r in result.mappings().all()]
    headers = [
        "name",
        "external_id",
        "group_name",
        "checked_in_at",
        "location_name",
        "device_name",
    ]
    return rows, headers


async def get_exception_report_data(
    session: AsyncSession,
    date_from: date,
    date_to: date,
    group_id: UUID | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    record_stmt = (
        select(
            AttendanceRecord.business_date,
            Person.display_name.label("name"),
            Person.external_id,
            Group.name.label("group_name"),
            AttendanceRecord.status,
            AttendanceRecord.flags,
            AttendanceRecord.override_id,
            AttendanceOverride.reason.label("override_reason"),
        )
        .join(Person, AttendanceRecord.person_id == Person.id)
        .outerjoin(AttendanceOverride, AttendanceRecord.override_id == AttendanceOverride.id)
        .outerjoin(
            PersonGroup,
            and_(
                PersonGroup.person_id == Person.id,
                PersonGroup.effective_from <= AttendanceRecord.business_date,
                or_(
                    PersonGroup.effective_to.is_(None),
                    PersonGroup.effective_to >= AttendanceRecord.business_date,
                ),
                PersonGroup.is_primary == True,
            ),
        )
        .outerjoin(Group, PersonGroup.group_id == Group.id)
        .where(
            and_(
                AttendanceRecord.business_date.between(date_from, date_to),
                or_(
                    AttendanceRecord.override_id.is_not(None),
                    AttendanceRecord.flags.op("->>")("location_mismatch") == "true",
                    AttendanceRecord.flags.op("->>")("auto_closed") == "true",
                ),
            )
        )
    )

    if group_id:
        record_stmt = record_stmt.where(PersonGroup.group_id == group_id)

    records_res = await session.execute(record_stmt)
    rows = []

    for r in records_res.mappings().all():
        flags = r["flags"] or {}
        details = []
        exc_type = "Record Exception"

        if r["override_id"]:
            exc_type = "Manual Override"
            details.append(
                f"Override Status: {r['status']}. Reason: {r['override_reason'] or 'N/A'}"
            )
        if flags.get("location_mismatch"):
            exc_type = "Location Mismatch"
            details.append("Check-in and check-out happened in conflicting locations.")
        if flags.get("auto_closed"):
            exc_type = "Auto-Closed Session"
            details.append("User did not check out; shift was auto-closed.")

        rows.append(
            {
                "timestamp": datetime.combine(r["business_date"], time.min).replace(
                    tzinfo=ZoneInfo("Asia/Manila")
                ),
                "name": r["name"],
                "external_id": r["external_id"] or "N/A",
                "group_name": r["group_name"] or "N/A",
                "exception_type": exc_type,
                "details": "; ".join(details),
            }
        )

    # raw events with failed outcomes
    event_stmt = (
        select(
            AttendanceEvent.occurred_at,
            Person.display_name.label("name"),
            Person.external_id,
            Group.name.label("group_name"),
            AttendanceEvent.outcome,
            AttendanceEvent.direction,
        )
        .outerjoin(Person, AttendanceEvent.person_id == Person.id)
        .outerjoin(
            PersonGroup,
            and_(
                PersonGroup.person_id == Person.id,
                PersonGroup.effective_from <= AttendanceEvent.business_date,
                or_(
                    PersonGroup.effective_to.is_(None),
                    PersonGroup.effective_to >= AttendanceEvent.business_date,
                ),
                PersonGroup.is_primary == True,
            ),
        )
        .outerjoin(Group, PersonGroup.group_id == Group.id)
        .where(
            and_(
                AttendanceEvent.occurred_at
                >= datetime.combine(date_from, time.min).replace(
                    tzinfo=ZoneInfo("Asia/Manila")
                ),
                AttendanceEvent.occurred_at
                <= datetime.combine(date_to, time.max).replace(
                    tzinfo=ZoneInfo("Asia/Manila")
                ),
                AttendanceEvent.outcome.in_(
                    [
                        AttendanceEventOutcome.AMBIGUOUS,
                        AttendanceEventOutcome.LOW_CONFIDENCE,
                        AttendanceEventOutcome.UNKNOWN_FACE,
                        AttendanceEventOutcome.LOCATION_CONFLICT,
                    ]
                ),
            )
        )
    )

    if group_id:
        event_stmt = event_stmt.where(PersonGroup.group_id == group_id)

    events_res = await session.execute(event_stmt)
    for ev in events_res.mappings().all():
        name = ev["name"] or "Unknown Face"
        outcome_str = str(ev["outcome"])
        direction_str = str(ev["direction"]).upper()

        rows.append(
            {
                "timestamp": ev["occurred_at"],
                "name": name,
                "external_id": ev["external_id"] or "N/A",
                "group_name": ev["group_name"] or "N/A",
                "exception_type": f"Scan Error: {outcome_str.title()}",
                "details": f"Attempted {direction_str} scan failed due to {outcome_str.lower().replace('_', ' ')}.",
            }
        )

    rows.sort(key=lambda x: x["timestamp"], reverse=True)

    for row in rows:
        row["timestamp_str"] = row["timestamp"].strftime("%Y-%m-%d %H:%M:%S")

    headers = [
        "timestamp_str",
        "name",
        "external_id",
        "group_name",
        "exception_type",
        "details",
    ]
    return rows, headers


async def get_device_health_data(
    session: AsyncSession,
) -> tuple[list[dict[str, Any]], list[str]]:
    subq = (
        select(
            DeviceHeartbeat.device_id,
            DeviceHeartbeat.observed_at,
            DeviceHeartbeat.battery_pct,
            DeviceHeartbeat.clock_skew_ms,
        )
        .order_by(DeviceHeartbeat.device_id, DeviceHeartbeat.observed_at.desc())
        .distinct(DeviceHeartbeat.device_id)
        .subquery()
    )

    stmt = (
        select(
            Device.token_display_prefix.label("device_name"),
            Device.mode,
            Device.form_factor,
            Location.name.label("location_name"),
            subq.c.observed_at,
            subq.c.battery_pct,
            subq.c.clock_skew_ms,
        )
        .outerjoin(Location, Device.location_id == Location.id)
        .outerjoin(subq, Device.id == subq.c.device_id)
        .order_by(Device.token_display_prefix.asc())
    )

    res = await session.execute(stmt)
    rows = []
    now = datetime.now(UTC)

    for r in res.mappings().all():
        row = dict(r)
        observed = row.get("observed_at")
        if observed:
            # Active if heartbeat in last 5 minutes
            is_active = (now - observed).total_seconds() < 300
            row["status"] = "Active" if is_active else "Offline"
            row["last_active"] = observed.strftime("%Y-%m-%d %H:%M:%S")
            row["battery"] = (
                f"{row['battery_pct']}%" if row["battery_pct"] is not None else "N/A"
            )
            row["skew"] = f"{row['clock_skew_ms']} ms"
        else:
            row["status"] = "Offline"
            row["last_active"] = "Never"
            row["battery"] = "N/A"
            row["skew"] = "N/A"

        rows.append(row)

    headers = [
        "device_name",
        "mode",
        "form_factor",
        "location_name",
        "last_active",
        "battery",
        "skew",
        "status",
    ]
    return rows, headers


# Map report types to their generators
REPORT_GENERATORS: dict[str, Any] = {
    "daily_register": get_daily_register_data,
    "timesheet": get_timesheet_data,
    "payroll_summary": get_payroll_summary_data,
    "tardiness": get_tardiness_data,
    "absence": get_absence_data,
    "truancy": get_truancy_data,
    "perfect_attendance": get_perfect_attendance_data,
    "headcount_by_hour": get_headcount_by_hour_data,
    "muster_roll": get_muster_roll_data,
    "exception_report": get_exception_report_data,
    "device_health": get_device_health_data,
}
