"""settings tables

Revision ID: 165783157a35
Revises: dade611d4072
Create Date: 2026-08-03 18:47:32.975815
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "165783157a35"
down_revision: str | None = "dade611d4072"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "settings",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("scope_id", sa.Uuid(), nullable=True),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("version", sa.BigInteger(), nullable=False),
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
        sa.CheckConstraint("key <> ''", name=op.f("ck_settings_key_non_empty")),
        sa.CheckConstraint(
            "scope != 'org' OR scope_id IS NULL",
            name=op.f("ck_settings_org_scope_forbids_scope_id"),
        ),
        sa.CheckConstraint(
            "scope = 'org' OR scope_id IS NOT NULL",
            name=op.f("ck_settings_non_org_scope_requires_scope_id"),
        ),
        sa.CheckConstraint(
            "scope IN ('org', 'location', 'device')",
            name=op.f("ck_settings_scope_valid"),
        ),
        sa.CheckConstraint("version > 0", name=op.f("ck_settings_version_positive")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_settings")),
        sa.UniqueConstraint("key", "scope", "scope_id", name="uq_settings_key_scope_scope_id"),
    )
    op.create_index(
        "uq_settings_org_key_scope",
        "settings",
        ["key", "scope"],
        unique=True,
        postgresql_where=sa.text("scope = 'org'"),
    )
    op.create_index(
        "uq_settings_scoped_key_scope_scope_id",
        "settings",
        ["key", "scope", "scope_id"],
        unique=True,
        postgresql_where=sa.text("scope IN ('location', 'device')"),
    )
    op.create_table(
        "settings_versions",
        sa.Column("namespace", sa.String(length=64), server_default="global", nullable=False),
        sa.Column(
            "current_version",
            sa.BigInteger(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "current_version > 0",
            name=op.f("ck_settings_versions_current_version_positive"),
        ),
        sa.PrimaryKeyConstraint("namespace", name=op.f("pk_settings_versions")),
    )


def downgrade() -> None:
    op.drop_table("settings_versions")
    op.drop_index(
        "uq_settings_scoped_key_scope_scope_id",
        table_name="settings",
        postgresql_where=sa.text("scope IN ('location', 'device')"),
    )
    op.drop_index(
        "uq_settings_org_key_scope",
        table_name="settings",
        postgresql_where=sa.text("scope = 'org'"),
    )
    op.drop_table("settings")
