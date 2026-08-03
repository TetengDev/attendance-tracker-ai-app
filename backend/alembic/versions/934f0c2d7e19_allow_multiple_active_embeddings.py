"""allow multiple active embeddings per person

Revision ID: 934f0c2d7e19
Revises: 1f0f9a2c7b33
Create Date: 2026-08-04 07:20:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "934f0c2d7e19"
down_revision: str | Sequence[str] | None = "1f0f9a2c7b33"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_face_embeddings_active_person_model")


def downgrade() -> None:
    op.create_index(
        "uq_face_embeddings_active_person_model",
        "face_embeddings",
        ["person_id", "model_name", "model_version"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )
