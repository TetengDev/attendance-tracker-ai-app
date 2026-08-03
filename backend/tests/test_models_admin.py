from __future__ import annotations

from typing import Any, cast

from sqlalchemy import Table

from backend.app.models.admin import AdminRole, AdminSession, AdminUser


def test_admin_user_model_encodes_role_and_totp_constraints() -> None:
    table = cast(Table, AdminUser.__table__)
    constraint_names = {constraint.name for constraint in table.constraints}

    assert "ck_admin_users_role_valid" in constraint_names
    assert "ck_admin_users_pii_export_roles_require_totp" in constraint_names
    assert "uq_admin_users_email" in constraint_names


def test_admin_session_model_stores_only_hashed_tokens() -> None:
    table = cast(Table, AdminSession.__table__)
    constraint_names = {constraint.name for constraint in table.constraints}

    assert "ck_admin_sessions_session_hash_sha256_length" in constraint_names
    assert "ck_admin_sessions_csrf_hash_sha256_length" in constraint_names
    assert "uq_admin_sessions_session_hash" in constraint_names


def test_pii_export_roles_are_totp_mandatory_roles() -> None:
    owner = AdminUser(
        email="owner@example.test",
        display_name="Owner",
        password_hash="hash",
        role=AdminRole.OWNER,
        totp_secret=b"x" * 32,
    )
    viewer = AdminUser(
        email="viewer@example.test",
        display_name="Viewer",
        password_hash="hash",
        role=AdminRole.VIEWER,
    )

    assert owner.can_export_pii
    assert not viewer.can_export_pii
    assert cast(Any, AdminUser.id).property.columns[0].server_default is not None
