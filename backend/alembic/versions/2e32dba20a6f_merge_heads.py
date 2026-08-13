"""merge heads

Revision ID: 2e32dba20a6f
Revises: 934f0c2d7e19, f3e827111b11
Create Date: 2026-08-11 20:36:00.301546
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa



revision: str = '2e32dba20a6f'
down_revision: str | None = ('934f0c2d7e19', 'f3e827111b11')
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
