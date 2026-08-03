from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from backend.app.audit.chain import AuditEntry
from backend.app.audit.service import append_audit_entry
from backend.app.db.session import get_session_factory
from backend.app.models.audit import AuditActorKind

MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
REQUEST_ID_HEADER = "x-request-id"


class AuditMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid4())
        request.state.request_id = request_id

        try:
            response = await call_next(request)
        except Exception:
            if request.method.upper() in MUTATING_METHODS:
                await _append_entry(
                    _entry_from_request_response(
                        request,
                        response=Response(status_code=500),
                        request_id=request_id,
                    )
                )
            raise

        response.headers[REQUEST_ID_HEADER] = request_id

        if request.method.upper() not in MUTATING_METHODS:
            return response

        entry = _entry_from_request_response(request, response=response, request_id=request_id)
        await _append_entry(entry)

        return response


def _entry_from_request_response(
    request: Request,
    *,
    response: Response,
    request_id: str,
) -> AuditEntry:
    return AuditEntry(
        actor_kind=_actor_kind_from_request(request),
        actor_id=_actor_id_from_request(request),
        action=f"{request.method.upper()} {request.url.path}",
        entity_type=_entity_type_from_path(request.url.path),
        entity_id=None,
        before=None,
        after={
            "status_code": response.status_code,
            "path": request.url.path,
            "method": request.method.upper(),
        },
        ip_address=request.client.host if request.client is not None else None,
        request_id=request_id,
        occurred_at=datetime.now(UTC),
    )


async def _append_entry(entry: AuditEntry) -> None:
    async with get_session_factory()() as session, session.begin():
        await append_audit_entry(session, entry)


def _actor_kind_from_request(request: Request) -> AuditActorKind:
    raw_kind = request.headers.get("x-actor-kind", AuditActorKind.SYSTEM.value)
    try:
        return AuditActorKind(raw_kind)
    except ValueError:
        return AuditActorKind.SYSTEM


def _actor_id_from_request(request: Request) -> UUID | None:
    raw_actor_id = request.headers.get("x-actor-id")
    if raw_actor_id is None:
        return None
    try:
        return UUID(raw_actor_id)
    except ValueError:
        return None


def _entity_type_from_path(path: str) -> str:
    stripped = path.strip("/")
    if not stripped:
        return "root"
    return stripped.split("/", maxsplit=1)[0]
