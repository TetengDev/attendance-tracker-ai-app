from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

SESSION_BYTES = 32
CSRF_BYTES = 32
IDLE_TIMEOUT = timedelta(hours=8)
ABSOLUTE_TIMEOUT = timedelta(hours=24)


def hash_token(token: str) -> bytes:
    return hashlib.sha256(token.encode("utf-8")).digest()


def new_opaque_token() -> str:
    return secrets.token_urlsafe(SESSION_BYTES)


def new_csrf_token() -> str:
    return secrets.token_urlsafe(CSRF_BYTES)


@dataclass(frozen=True)
class IssuedAdminSession:
    admin_user_id: UUID
    session_token: str
    session_hash: bytes
    csrf_token: str
    csrf_token_hash: bytes
    issued_at: datetime
    idle_expires_at: datetime
    absolute_expires_at: datetime


def issue_admin_session(admin_user_id: UUID, *, now: datetime | None = None) -> IssuedAdminSession:
    issued_at = now or datetime.now(UTC)
    session_token = new_opaque_token()
    csrf_token = new_csrf_token()
    return IssuedAdminSession(
        admin_user_id=admin_user_id,
        session_token=session_token,
        session_hash=hash_token(session_token),
        csrf_token=csrf_token,
        csrf_token_hash=hash_token(csrf_token),
        issued_at=issued_at,
        idle_expires_at=issued_at + IDLE_TIMEOUT,
        absolute_expires_at=issued_at + ABSOLUTE_TIMEOUT,
    )


def verify_double_submit_csrf(cookie_token: str | None, header_token: str | None) -> bool:
    if cookie_token is None or header_token is None:
        return False
    return secrets.compare_digest(cookie_token, header_token)
