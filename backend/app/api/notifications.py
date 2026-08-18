from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import HTMLResponse
from pydantic import Field
from sqlalchemy import select

from backend.app.api.common import (
    ActorDep,
    AdminUserDep,
    SessionDep,
    StrictSchema,
    audited_mutation,
    require_org_admin,
    snapshot,
)
from backend.app.models.notifications import NotificationRule
from backend.app.models.people import ContactChannel, Guardian, PersonGuardian

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


class NotificationRuleSchema(StrictSchema):
    id: UUID
    group_id: UUID | None
    person_kind: str | None
    trigger_status: str
    delay_minutes: int
    channel: ContactChannel
    template: str
    is_active: bool


class NotificationRuleCreate(StrictSchema):
    group_id: UUID | None = None
    person_kind: str | None = None
    trigger_status: str = Field(..., max_length=32)
    delay_minutes: int = Field(default=0, ge=0)
    channel: ContactChannel = ContactChannel.SMS
    template: str
    is_active: bool = True


class NotificationRuleUpdate(StrictSchema):
    group_id: UUID | None = None
    person_kind: str | None = None
    trigger_status: str | None = None
    delay_minutes: int | None = None
    channel: ContactChannel | None = None
    template: str | None = None
    is_active: bool | None = None


class PreferenceUpdate(StrictSchema):
    preferred_channel: ContactChannel
    receives_attendance_alerts: bool


class GuardianPreferenceInfo(StrictSchema):
    guardian_id: UUID
    preferred_channel: ContactChannel
    receives_attendance_alerts: bool


@router.get("/rules", response_model=list[NotificationRuleSchema])
async def list_rules(
    session: SessionDep,
    admin_user: AdminUserDep,
) -> list[NotificationRule]:
    require_org_admin(admin_user)
    stmt = select(NotificationRule)
    rules = (await session.execute(stmt)).scalars().all()
    return list(rules)


@router.get("/rules/{id}", response_model=NotificationRuleSchema)
async def get_rule(
    id: UUID,
    session: SessionDep,
    admin_user: AdminUserDep,
) -> NotificationRule:
    require_org_admin(admin_user)
    rule = await session.get(NotificationRule, id)
    if not rule:
        raise HTTPException(status_code=404, detail="Notification rule not found")
    return rule


@router.post("/rules", response_model=NotificationRuleSchema, status_code=status.HTTP_201_CREATED)
async def create_rule(
    payload: NotificationRuleCreate,
    session: SessionDep,
    admin_user: AdminUserDep,
    actor: ActorDep,
) -> NotificationRule:
    require_org_admin(admin_user)

    from backend.app.api.common import RequestActor
    actor = RequestActor(admin_user.id, actor.request_id, actor.ip_address)

    rule = NotificationRule(
        id=uuid4(),
        group_id=payload.group_id,
        person_kind=payload.person_kind,
        trigger_status=payload.trigger_status,
        delay_minutes=payload.delay_minutes,
        channel=payload.channel,
        template=payload.template,
        is_active=payload.is_active,
    )
    session.add(rule)
    await session.flush()

    await audited_mutation(
        session,
        actor,
        action="create",
        entity_type="notification_rule",
        entity_id=str(rule.id),
        before=None,
        after=snapshot(
            rule,
            (
                "group_id",
                "person_kind",
                "trigger_status",
                "delay_minutes",
                "channel",
                "template",
                "is_active",
            ),
        ),
    )
    await session.commit()
    return rule


@router.put("/rules/{id}", response_model=NotificationRuleSchema)
async def update_rule(
    id: UUID,
    payload: NotificationRuleUpdate,
    session: SessionDep,
    admin_user: AdminUserDep,
    actor: ActorDep,
) -> NotificationRule:
    require_org_admin(admin_user)
    rule = await session.get(NotificationRule, id)
    if not rule:
        raise HTTPException(status_code=404, detail="Notification rule not found")

    from backend.app.api.common import RequestActor
    actor = RequestActor(admin_user.id, actor.request_id, actor.ip_address)
    before_snap = snapshot(
        rule,
        (
            "group_id",
            "person_kind",
            "trigger_status",
            "delay_minutes",
            "channel",
            "template",
            "is_active",
        ),
    )

    if payload.group_id is not None or "group_id" in payload.model_fields_set:
        rule.group_id = payload.group_id
    if payload.person_kind is not None:
        rule.person_kind = payload.person_kind
    if payload.trigger_status is not None:
        rule.trigger_status = payload.trigger_status
    if payload.delay_minutes is not None:
        rule.delay_minutes = payload.delay_minutes
    if payload.channel is not None:
        rule.channel = payload.channel
    if payload.template is not None:
        rule.template = cast(Any, payload.template)
    if payload.is_active is not None:
        rule.is_active = payload.is_active

    await session.flush()
    await audited_mutation(
        session,
        actor,
        action="update",
        entity_type="notification_rule",
        entity_id=str(rule.id),
        before=before_snap,
        after=snapshot(
            rule,
            (
                "group_id",
                "person_kind",
                "trigger_status",
                "delay_minutes",
                "channel",
                "template",
                "is_active",
            ),
        ),
    )
    await session.commit()
    return rule


@router.delete("/rules/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(
    id: UUID,
    session: SessionDep,
    admin_user: AdminUserDep,
    actor: ActorDep,
) -> None:
    require_org_admin(admin_user)
    rule = await session.get(NotificationRule, id)
    if not rule:
        raise HTTPException(status_code=404, detail="Notification rule not found")

    from backend.app.api.common import RequestActor
    actor = RequestActor(admin_user.id, actor.request_id, actor.ip_address)
    before_snap = snapshot(
        rule,
        (
            "group_id",
            "person_kind",
            "trigger_status",
            "delay_minutes",
            "channel",
            "template",
            "is_active",
        ),
    )

    await session.delete(rule)
    await audited_mutation(
        session,
        actor,
        action="delete",
        entity_type="notification_rule",
        entity_id=str(id),
        before=before_snap,
        after=None,
    )
    await session.commit()


@router.get("/preferences/{guardian_id}", response_model=GuardianPreferenceInfo)
async def get_preferences(
    guardian_id: UUID,
    session: SessionDep,
    admin_user: AdminUserDep,
) -> dict[str, Any]:
    require_org_admin(admin_user)
    guardian = await session.get(Guardian, guardian_id)
    if not guardian:
        raise HTTPException(status_code=404, detail="Guardian not found")

    pg_stmt = select(PersonGuardian).where(PersonGuardian.guardian_id == guardian_id)
    pg_links = (await session.execute(pg_stmt)).scalars().all()
    receives_alerts = any(link.receives_attendance_alerts for link in pg_links) if pg_links else True

    return {
        "guardian_id": guardian_id,
        "preferred_channel": guardian.preferred_channel,
        "receives_attendance_alerts": receives_alerts,
    }


@router.patch("/preferences/{guardian_id}", response_model=GuardianPreferenceInfo)
async def update_preferences(
    guardian_id: UUID,
    payload: PreferenceUpdate,
    session: SessionDep,
    admin_user: AdminUserDep,
    actor: ActorDep,
) -> dict[str, Any]:
    require_org_admin(admin_user)
    guardian = await session.get(Guardian, guardian_id)
    if not guardian:
        raise HTTPException(status_code=404, detail="Guardian not found")

    from backend.app.api.common import RequestActor
    actor = RequestActor(admin_user.id, actor.request_id, actor.ip_address)
    before_pref: dict[str, object] = {
        "preferred_channel": guardian.preferred_channel,
    }

    guardian.preferred_channel = payload.preferred_channel

    pg_stmt = select(PersonGuardian).where(PersonGuardian.guardian_id == guardian_id)
    pg_links = (await session.execute(pg_stmt)).scalars().all()
    for link in pg_links:
        link.receives_attendance_alerts = payload.receives_attendance_alerts
        session.add(link)

    await session.flush()
    await audited_mutation(
        session,
        actor,
        action="update_preferences",
        entity_type="guardian_preferences",
        entity_id=str(guardian_id),
        before=before_pref,
        after={
            "preferred_channel": payload.preferred_channel,
            "receives_attendance_alerts": payload.receives_attendance_alerts,
        },
    )
    await session.commit()

    return {
        "guardian_id": guardian_id,
        "preferred_channel": payload.preferred_channel,
        "receives_attendance_alerts": payload.receives_attendance_alerts,
    }


@router.get("/unsubscribe", response_class=HTMLResponse)
async def unsubscribe(
    session: SessionDep,
    token: str = Query(...),
) -> HTMLResponse:
    import jwt

    from backend.app.config import get_settings

    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=["HS256"],
        )
        if payload.get("purpose") != "unsubscribe":
            return HTMLResponse(
                content="<html><body><h2>Invalid unsubscribe request.</h2></body></html>",
                status_code=400,
            )
        guardian_id = UUID(payload["sub"])
    except jwt.PyJWTError:
        return HTMLResponse(
            content="<html><body><h2>Link is invalid or has expired.</h2></body></html>",
            status_code=400,
        )

    guardian = await session.get(Guardian, guardian_id)
    if not guardian:
        return HTMLResponse(
            content="<html><body><h2>Guardian not found.</h2></body></html>",
            status_code=404,
        )

    guardian.preferred_channel = ContactChannel.NONE
    session.add(guardian)

    pg_stmt = select(PersonGuardian).where(PersonGuardian.guardian_id == guardian_id)
    pg_links = (await session.execute(pg_stmt)).scalars().all()
    for link in pg_links:
        link.receives_attendance_alerts = False
        session.add(link)

    from backend.app.audit.chain import AuditEntry
    from backend.app.audit.service import append_audit_entry
    from backend.app.models.audit import AuditActorKind

    await append_audit_entry(
        session,
        AuditEntry(
            actor_kind=AuditActorKind.SYSTEM,
            actor_id=None,
            action="opt_out_unsubscribe",
            entity_type="guardian_preferences",
            entity_id=str(guardian_id),
            before=None,
            after={"preferred_channel": "none", "receives_attendance_alerts": False},
            ip_address=None,
            request_id=str(uuid4()),
            occurred_at=datetime.now(UTC),
        ),
    )
    await session.commit()

    return HTMLResponse(
        content=(
            "<html><body style='font-family: sans-serif; text-align: center; margin-top: 100px;'>"
            "<h2>You have been successfully unsubscribed from all attendance notifications.</h2>"
            "<p>You will no longer receive SMS or Email alerts.</p>"
            "</body></html>"
        )
    )
