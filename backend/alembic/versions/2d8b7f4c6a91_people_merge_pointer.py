"""people merge pointer

Revision ID: 2d8b7f4c6a91
Revises: 4a1f0e9d6c2b
Create Date: 2026-08-03 21:05:00.000000
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2d8b7f4c6a91"
down_revision: str | None = "4a1f0e9d6c2b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("people", sa.Column("merged_into_person_id", sa.Uuid(), nullable=True))
    op.add_column("people", sa.Column("merged_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        op.f("fk_people_merged_into_person_id_people"),
        "people",
        "people",
        ["merged_into_person_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        op.f("ck_people_person_merge_not_self"),
        "people",
        "merged_into_person_id IS NULL OR merged_into_person_id <> id",
    )
    op.create_index(
        "ix_people_merged_into_person_id",
        "people",
        ["merged_into_person_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_people_merged_into_person_id", table_name="people")
    op.drop_constraint(op.f("ck_people_person_merge_not_self"), "people", type_="check")
    op.drop_constraint(op.f("fk_people_merged_into_person_id_people"), "people", type_="foreignkey")
    op.drop_column("people", "merged_at")
    op.drop_column("people", "merged_into_person_id")
