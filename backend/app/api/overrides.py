"""REST API router for manual attendance overrides."""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID

from fastapi import APIRouter
from pydantic import Field
from sqlalchemy import select

from backend.app.api.common import (
    ActorDep,
    AdminUserDep,
    CrudError,
    CrudErrorCode,
    RequestActor,
    SessionDep,
    StrictSchema,
    audited_mutation,
    commit_or_422,
    require_org_admin,
    snapshot,
    translate_crud_error,
)
from backend.app.attendance.decision_table import AttendanceStatus
from backend.app.models.attendance import AttendanceOverride

router = APIRouter(prefix="/api/attendance/overrides", tags=["attendance_overrides"])

OVERRIDE_FIELDS = (
    "id",
    "person_id",
    "business_date",
    "shift_id",
    "period_label",
    "status",
    "reason",
    "actor_admin_id",
)


class OverrideCreate(StrictSchema):
    person_id: UUID
    business_date: date
    shift_id: UUID
    period_label: str = Field(min_length=1, max_length=64)
    status: AttendanceStatus
    reason: str = Field(min_length=1, max_length=512)


class OverrideRead(StrictSchema):
    id: UUID
    person_id: UUID
    business_date: date
    shift_id: UUID
    period_label: str
    status: AttendanceStatus
    reason: str
    actor_admin_id: UUID | None


@router.post("", response_model=OverrideRead, status_code=201)
async def create_or_update_override(
    payload: OverrideCreate,
    session: SessionDep,
    admin_user: AdminUserDep,
    actor: ActorDep,
) -> AttendanceOverride:
    """Create or update a manual override for a specific attendance target.

    Fails closed if role validation fails, triggers automatic re-resolution,
    and publishes an audit log event.
    """
    try:
        require_org_admin(admin_user)
    except CrudError as exc:
        raise translate_crud_error(exc) from exc

    actor = RequestActor(admin_user.id, actor.request_id, actor.ip_address)

    # Check for empty reason validation (CheckConstraint equivalent)
    if not payload.reason.strip():
        raise translate_crud_error(
            CrudError(CrudErrorCode.INVALID_INPUT, "Reason cannot be empty")
        )

    # Query if override natural key already exists
    stmt = select(AttendanceOverride).where(
        AttendanceOverride.person_id == payload.person_id,
        AttendanceOverride.business_date == payload.business_date,
        AttendanceOverride.shift_id == payload.shift_id,
        AttendanceOverride.period_label == payload.period_label,
    )
    res = await session.execute(stmt)
    override = res.scalar_one_or_none()

    before = None
    if override:
        before = snapshot(override, OVERRIDE_FIELDS)
        override.status = payload.status
        override.reason = payload.reason
        override.actor_admin_id = admin_user.id
    else:
        from uuid import uuid4
        override = AttendanceOverride(
            id=uuid4(),
            person_id=payload.person_id,
            business_date=payload.business_date,
            shift_id=payload.shift_id,
            period_label=payload.period_label,
            status=payload.status,
            reason=payload.reason,
            actor_admin_id=admin_user.id,
        )
        session.add(override)

    try:
        await commit_or_422(session)
    except CrudError as exc:
        raise translate_crud_error(exc) from exc

    # Trigger resolution
    from backend.app.attendance.resolver import redis_resolver_state, resolve

    redis_resolver_state.set_dirty(payload.person_id, payload.business_date)
    await resolve(session, payload.person_id, payload.business_date, as_of=datetime.now(UTC))

    try:
        await commit_or_422(session)
    except CrudError as exc:
        raise translate_crud_error(exc) from exc

    # Write audit log
    await audited_mutation(
        session,
        actor,
        action="attendance.override.create_or_update",
        entity_type="attendance_override",
        entity_id=str(override.id),
        before=before,
        after=snapshot(override, OVERRIDE_FIELDS),
    )

    return override


@router.get("", response_model=list[OverrideRead])
async def list_overrides(
    session: SessionDep,
    admin_user: AdminUserDep,
    person_id: UUID | None = None,
    business_date: date | None = None,
) -> list[AttendanceOverride]:
    """Retrieve manual overrides, filterable by person and date."""
    try:
        require_org_admin(admin_user)
    except CrudError as exc:
        raise translate_crud_error(exc) from exc

    stmt = select(AttendanceOverride)
    if person_id:
        stmt = stmt.where(AttendanceOverride.person_id == person_id)
    if business_date:
        stmt = stmt.where(AttendanceOverride.business_date == business_date)

    res = await session.execute(stmt)
    return list(res.scalars().all())


@router.delete("/{id}", status_code=204)
async def delete_override(
    id: UUID,
    session: SessionDep,
    admin_user: AdminUserDep,
    actor: ActorDep,
) -> None:
    """Delete a manual override, triggering immediate re-resolution and logging audit details."""
    try:
        require_org_admin(admin_user)
    except CrudError as exc:
        raise translate_crud_error(exc) from exc

    actor = RequestActor(admin_user.id, actor.request_id, actor.ip_address)

    # Fetch override
    stmt = select(AttendanceOverride).where(AttendanceOverride.id == id)
    res = await session.execute(stmt)
    override = res.scalar_one_or_none()
    if not override:
        raise translate_crud_error(
            CrudError(CrudErrorCode.NOT_FOUND, "attendance override not found")
        )

    before = snapshot(override, OVERRIDE_FIELDS)
    person_id = override.person_id
    business_date = override.business_date

    await session.delete(override)

    try:
        await commit_or_422(session)
    except CrudError as exc:
        raise translate_crud_error(exc) from exc

    # Trigger resolution
    from backend.app.attendance.resolver import redis_resolver_state, resolve

    redis_resolver_state.set_dirty(person_id, business_date)
    await resolve(session, person_id, business_date, as_of=datetime.now(UTC))

    try:
        await commit_or_422(session)
    except CrudError as exc:
        raise translate_crud_error(exc) from exc

    # Write audit log
    await audited_mutation(
        session,
        actor,
        action="attendance.override.delete",
        entity_type="attendance_override",
        entity_id=str(id),
        before=before,
        after=None,
    )
