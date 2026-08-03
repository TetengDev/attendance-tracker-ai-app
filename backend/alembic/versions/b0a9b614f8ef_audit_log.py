"""audit log

Revision ID: b0a9b614f8ef
Revises: 165783157a35
Create Date: 2026-08-03 19:20:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b0a9b614f8ef"
down_revision: str | None = "165783157a35"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("actor_kind", sa.String(length=16), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("entity_type", sa.String(length=128), nullable=False),
        sa.Column("entity_id", sa.String(length=128), nullable=True),
        sa.Column("before", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("request_id", sa.String(length=128), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("prev_hash", sa.LargeBinary(length=32), nullable=True),
        sa.Column("hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "actor_kind IN ('admin', 'device', 'system', 'job')",
            name=op.f("ck_audit_log_actor_kind_valid"),
        ),
        sa.CheckConstraint("action <> ''", name=op.f("ck_audit_log_action_non_empty")),
        sa.CheckConstraint(
            "entity_type <> ''",
            name=op.f("ck_audit_log_entity_type_non_empty"),
        ),
        sa.CheckConstraint("request_id <> ''", name=op.f("ck_audit_log_request_id_non_empty")),
        sa.CheckConstraint("octet_length(hash) = 32", name=op.f("ck_audit_log_hash_sha256_length")),
        sa.CheckConstraint(
            "prev_hash IS NULL OR octet_length(prev_hash) = 32",
            name=op.f("ck_audit_log_prev_hash_sha256_length"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_log")),
    )
    op.create_index("ix_audit_log_actor", "audit_log", ["actor_kind", "actor_id"], unique=False)
    op.create_index("ix_audit_log_created_at", "audit_log", ["created_at"], unique=False)
    op.create_index("ix_audit_log_entity", "audit_log", ["entity_type", "entity_id"], unique=False)
    op.execute(
        """
        CREATE FUNCTION prevent_audit_log_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'audit_log is append-only';
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_log_no_update_delete
        BEFORE UPDATE OR DELETE ON audit_log
        FOR EACH ROW
        EXECUTE FUNCTION prevent_audit_log_mutation();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_log_no_update_delete ON audit_log")
    op.execute("DROP FUNCTION IF EXISTS prevent_audit_log_mutation()")
    op.drop_index("ix_audit_log_entity", table_name="audit_log")
    op.drop_index("ix_audit_log_created_at", table_name="audit_log")
    op.drop_index("ix_audit_log_actor", table_name="audit_log")
    op.drop_table("audit_log")
