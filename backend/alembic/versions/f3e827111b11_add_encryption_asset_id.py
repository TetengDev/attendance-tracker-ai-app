"""add encryption_asset_id

Revision ID: f3e827111b11
Revises: dade611d4072
Create Date: 2026-08-11 17:33:00.000000

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'f3e827111b11'
down_revision = 'dade611d4072'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add column as nullable first
    op.add_column('face_embeddings', sa.Column('encryption_asset_id', postgresql.UUID(as_uuid=True), nullable=True))
    
    # Backfill using the existing asset_id (if it is null, we can't do much, but we assume it's mostly present for active ones)
    op.execute("UPDATE face_embeddings SET encryption_asset_id = asset_id WHERE asset_id IS NOT NULL")
    
    # In case there are NULL asset_ids, we need a placeholder UUID just to pass the NOT NULL constraint, 
    # though those records are technically broken anyway without AAD. We use a zero UUID.
    op.execute("UPDATE face_embeddings SET encryption_asset_id = '00000000-0000-0000-0000-000000000000'::uuid WHERE encryption_asset_id IS NULL")

    op.alter_column('face_embeddings', 'encryption_asset_id', nullable=False)


def downgrade() -> None:
    op.drop_column('face_embeddings', 'encryption_asset_id')
