"""scan sessions

Revision ID: 8c9914b0f51b
Revises: 2d8b7f4c6a91
Create Date: 2026-08-04 01:55:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8c9914b0f51b"
down_revision: str | None = "2d8b7f4c6a91"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scan_sessions",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column("operator_admin_id", sa.Uuid(), nullable=True),
        sa.Column("location_source", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("start_lat", sa.Numeric(precision=8, scale=6), nullable=True),
        sa.Column("start_lng", sa.Numeric(precision=9, scale=6), nullable=True),
        sa.Column("gps_accuracy_m", sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column("scan_count", sa.Integer(), nullable=False),
        sa.Column("end_reason", sa.String(length=32), nullable=True),
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
            "end_reason IS NULL OR end_reason IN ('explicit', 'idle_timeout', 'max_duration', 'token_revoked')",
            name=op.f("ck_scan_sessions_end_reason_valid"),
        ),
        sa.CheckConstraint(
            "(ended_at IS NULL AND end_reason IS NULL) OR (ended_at IS NOT NULL AND end_reason IS NOT NULL)",
            name=op.f("ck_scan_sessions_ended_state_matches_reason"),
        ),
        sa.CheckConstraint(
            "ended_at IS NULL OR ended_at >= started_at",
            name=op.f("ck_scan_sessions_ended_at_not_before_started_at"),
        ),
        sa.CheckConstraint(
            "gps_accuracy_m IS NULL OR gps_accuracy_m >= 0",
            name=op.f("ck_scan_sessions_gps_accuracy_non_negative"),
        ),
        sa.CheckConstraint(
            "last_activity_at >= started_at",
            name=op.f("ck_scan_sessions_last_activity_not_before_started_at"),
        ),
        sa.CheckConstraint(
            "location_source IN ('device_fixed', 'session_declared', 'geofence')",
            name=op.f("ck_scan_sessions_location_source_valid"),
        ),
        sa.CheckConstraint(
            "scan_count >= 0", name=op.f("ck_scan_sessions_scan_count_non_negative")
        ),
        sa.CheckConstraint(
            "start_lat IS NULL OR start_lat BETWEEN -90 AND 90",
            name=op.f("ck_scan_sessions_start_lat_range"),
        ),
        sa.CheckConstraint(
            "start_lng IS NULL OR start_lng BETWEEN -180 AND 180",
            name=op.f("ck_scan_sessions_start_lng_range"),
        ),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["devices.id"],
            name=op.f("fk_scan_sessions_device_id_devices"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["location_id"],
            ["locations.id"],
            name=op.f("fk_scan_sessions_location_id_locations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["operator_admin_id"],
            ["admin_users.id"],
            name=op.f("fk_scan_sessions_operator_admin_id_admin_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scan_sessions")),
    )
    op.create_index(
        "ix_scan_sessions_device_started_at",
        "scan_sessions",
        ["device_id", "started_at"],
        unique=False,
    )
    op.create_index(
        "ix_scan_sessions_location_started_at",
        "scan_sessions",
        ["location_id", "started_at"],
        unique=False,
    )
    op.create_index(
        "uq_scan_sessions_open_device",
        "scan_sessions",
        ["device_id"],
        unique=True,
        postgresql_where=sa.text("ended_at IS NULL"),
    )
    op.add_column("attendance_events", sa.Column("session_id", sa.Uuid(), nullable=True))
    op.create_index(
        "ix_attendance_events_session_id", "attendance_events", ["session_id"], unique=False
    )
    op.create_foreign_key(
        op.f("fk_attendance_events_session_id_scan_sessions"),
        "attendance_events",
        "scan_sessions",
        ["session_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_attendance_events_session_id_scan_sessions"),
        "attendance_events",
        type_="foreignkey",
    )
    op.drop_index("ix_attendance_events_session_id", table_name="attendance_events")
    op.drop_column("attendance_events", "session_id")
    op.drop_index(
        "uq_scan_sessions_open_device",
        table_name="scan_sessions",
        postgresql_where=sa.text("ended_at IS NULL"),
    )
    op.drop_index("ix_scan_sessions_location_started_at", table_name="scan_sessions")
    op.drop_index("ix_scan_sessions_device_started_at", table_name="scan_sessions")
    op.drop_table("scan_sessions")
