from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from backend.app.auth.passwords import (
    ARGON2_MEMORY_COST_KIB,
    ARGON2_PARALLELISM,
    ARGON2_TIME_COST,
    hash_admin_password,
    verify_admin_password,
)
from backend.app.auth.sessions import (
    ABSOLUTE_TIMEOUT,
    IDLE_TIMEOUT,
    issue_admin_session,
    verify_double_submit_csrf,
)
from backend.app.auth.totp import generate_totp_secret, totp_code, verify_totp


def test_argon2id_parameters_match_security_contract() -> None:
    password_hash = hash_admin_password("correct horse battery staple")

    assert f"m={ARGON2_MEMORY_COST_KIB}" in password_hash
    assert f"t={ARGON2_TIME_COST}" in password_hash
    assert f"p={ARGON2_PARALLELISM}" in password_hash
    assert verify_admin_password(password_hash, "correct horse battery staple")
    assert not verify_admin_password(password_hash, "wrong")


def test_totp_secret_generates_and_verifies_current_code() -> None:
    secret = generate_totp_secret()
    now = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)
    code = totp_code(secret, at=now)

    assert len(secret) == 32
    assert verify_totp(secret, code, at=now)
    assert not verify_totp(secret, "000000", at=now)


def test_issued_session_uses_opaque_hashes_and_contract_timeouts() -> None:
    admin_user_id = UUID("00000000-0000-0000-0000-000000000028")
    now = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)
    issued = issue_admin_session(admin_user_id, now=now)

    assert issued.admin_user_id == admin_user_id
    assert len(issued.session_hash) == 32
    assert len(issued.csrf_token_hash) == 32
    assert issued.session_token != issued.session_hash.hex()
    assert issued.idle_expires_at == now + IDLE_TIMEOUT
    assert issued.absolute_expires_at == now + ABSOLUTE_TIMEOUT


def test_double_submit_csrf_requires_cookie_and_header_match() -> None:
    assert verify_double_submit_csrf("token", "token")
    assert not verify_double_submit_csrf("token", "other")
    assert not verify_double_submit_csrf("token", None)
