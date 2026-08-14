"""add_retry_count_to_notifications

Revision ID: 9c5d350d9ecb
Revises: 1a44f9eaf8c3
Create Date: 2026-08-15 06:22:16.940480
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa



revision: str = '9c5d350d9ecb'
down_revision: str | None = '1a44f9eaf8c3'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('notifications', sa.Column('retry_count', sa.Integer(), nullable=False, server_default='0'))


def downgrade() -> None:
    op.drop_column('notifications', 'retry_count')
