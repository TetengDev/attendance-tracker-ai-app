"""admin auth tables

Revision ID: 4a1f0e9d6c2b
Revises: b0a9b614f8ef
Create Date: 2026-08-03 20:05:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "4a1f0e9d6c2b"
down_revision: str | None = "b0a9b614f8ef"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "admin_users",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=256), nullable=False),
        sa.Column("password_hash", sa.String(length=512), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column(
            "scope_group_ids",
            postgresql.ARRAY(sa.Uuid()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("totp_secret", sa.LargeBinary(length=32), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_login_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "display_name <> ''", name=op.f("ck_admin_users_display_name_non_empty")
        ),
        sa.CheckConstraint("email <> ''", name=op.f("ck_admin_users_email_non_empty")),
        sa.CheckConstraint(
            "password_hash <> ''", name=op.f("ck_admin_users_password_hash_non_empty")
        ),
        sa.CheckConstraint(
            "role IN ('owner', 'admin', 'hr', 'supervisor', 'viewer')",
            name=op.f("ck_admin_users_role_valid"),
        ),
        sa.CheckConstraint(
            "totp_secret IS NOT NULL OR role NOT IN ('owner', 'admin', 'hr')",
            name=op.f("ck_admin_users_pii_export_roles_require_totp"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_admin_users")),
        sa.UniqueConstraint("email", name="uq_admin_users_email"),
    )
    op.create_index("ix_admin_users_role", "admin_users", ["role"], unique=False)

    op.create_table(
        "admin_sessions",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("admin_user_id", sa.Uuid(), nullable=False),
        sa.Column("session_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("csrf_token_hash", sa.LargeBinary(length=32), nullable=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("idle_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("absolute_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rotated_from_session_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "absolute_expires_at > created_at",
            name=op.f("ck_admin_sessions_absolute_expiry_after_created"),
        ),
        sa.CheckConstraint(
            "csrf_token_hash IS NULL OR octet_length(csrf_token_hash) = 32",
            name=op.f("ck_admin_sessions_csrf_hash_sha256_length"),
        ),
        sa.CheckConstraint(
            "idle_expires_at > created_at",
            name=op.f("ck_admin_sessions_idle_expiry_after_created"),
        ),
        sa.CheckConstraint(
            "octet_length(session_hash) = 32",
            name=op.f("ck_admin_sessions_session_hash_sha256_length"),
        ),
        sa.ForeignKeyConstraint(
            ["admin_user_id"],
            ["admin_users.id"],
            name=op.f("fk_admin_sessions_admin_user_id_admin_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["rotated_from_session_id"],
            ["admin_sessions.id"],
            name=op.f("fk_admin_sessions_rotated_from_session_id_admin_sessions"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_admin_sessions")),
        sa.UniqueConstraint("session_hash", name="uq_admin_sessions_session_hash"),
    )
    op.create_index(
        "ix_admin_sessions_admin_user_active",
        "admin_sessions",
        ["admin_user_id", "revoked_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_admin_sessions_admin_user_active", table_name="admin_sessions")
    op.drop_table("admin_sessions")
    op.drop_index("ix_admin_users_role", table_name="admin_users")
    op.drop_table("admin_users")
