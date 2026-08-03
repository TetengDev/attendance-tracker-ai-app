from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.audit.chain import AuditEntry
from backend.app.audit.service import append_audit_entry
from backend.app.db.session import get_session
from backend.app.models.admin import AdminRole, AdminUser
from backend.app.models.audit import AuditActorKind

SessionDep = Annotated[AsyncSession, Depends(get_session)]

class StrictSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class PageParams(StrictSchema):
    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class CrudErrorCode(str, Enum):
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    INVALID_INPUT = "INVALID_INPUT"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"


@dataclass(frozen=True)
class CrudError(Exception):
    code: CrudErrorCode
    message: str


@dataclass(frozen=True)
class RequestActor:
    admin_id: UUID | None
    request_id: str
    ip_address: str | None


def request_actor(
    request: Request,
    x_request_id: Annotated[str | None, Header(alias="x-request-id")] = None,
) -> RequestActor:
    client_host = request.client.host if request.client else None
    return RequestActor(
        admin_id=None,
        request_id=x_request_id or str(uuid4()),
        ip_address=client_host,
    )


ActorDep = Annotated[RequestActor, Depends(request_actor)]


def translate_crud_error(exc: CrudError) -> HTTPException:
    if exc.code == CrudErrorCode.UNAUTHORIZED:
        return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=exc.message)
    if exc.code == CrudErrorCode.FORBIDDEN:
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=exc.message)
    if exc.code == CrudErrorCode.NOT_FOUND:
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.message)
    if exc.code == CrudErrorCode.CONFLICT:
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.message)
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.message)


def handle_integrity_error(exc: IntegrityError) -> CrudError:
    return CrudError(CrudErrorCode.CONFLICT, "resource conflicts with existing data")


async def authenticated_admin_user(
    session: SessionDep,
    x_admin_id: Annotated[str | None, Header(alias="x-admin-id")] = None,
) -> AdminUser:
    if x_admin_id is None:
        raise translate_crud_error(CrudError(CrudErrorCode.UNAUTHORIZED, "admin authentication required"))
    try:
        admin_id = UUID(x_admin_id)
    except ValueError as exc:
        raise translate_crud_error(CrudError(CrudErrorCode.UNAUTHORIZED, "invalid admin identity")) from exc
    admin_user = (
        await session.execute(select(AdminUser).where(AdminUser.id == admin_id, AdminUser.is_active.is_(True)))
    ).scalar_one_or_none()
    if admin_user is None:
        raise translate_crud_error(CrudError(CrudErrorCode.UNAUTHORIZED, "admin authentication required"))
    return admin_user


AdminUserDep = Annotated[AdminUser, Depends(authenticated_admin_user)]


def require_org_admin(admin_user: AdminUser) -> None:
    if AdminRole(admin_user.role) not in {AdminRole.OWNER, AdminRole.ADMIN, AdminRole.HR}:
        raise CrudError(CrudErrorCode.FORBIDDEN, "admin role cannot manage org-wide resources")


async def audited_mutation(
    session: AsyncSession,
    actor: RequestActor,
    *,
    action: str,
    entity_type: str,
    entity_id: str | None,
    before: dict[str, object] | None,
    after: dict[str, object] | None,
) -> None:
    await append_audit_entry(
        session,
        AuditEntry(
            actor_kind=AuditActorKind.ADMIN,
            actor_id=actor.admin_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            before=before,
            after=after,
            ip_address=actor.ip_address,
            request_id=actor.request_id,
            occurred_at=datetime.now(UTC),
        ),
    )


def snapshot(model: object, fields: tuple[str, ...]) -> dict[str, object]:
    return {field: _jsonable(getattr(model, field)) for field in fields}


def apply_updates(model: object, values: dict[str, object]) -> None:
    for key, value in values.items():
        setattr(model, key, value)


async def commit_or_422(session: AsyncSession) -> None:
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise handle_integrity_error(exc) from exc
    except ValueError as exc:
        await session.rollback()
        raise CrudError(CrudErrorCode.INVALID_INPUT, str(exc)) from exc


def _jsonable(value: object) -> object:
    if isinstance(value, (UUID, datetime)):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    return value
