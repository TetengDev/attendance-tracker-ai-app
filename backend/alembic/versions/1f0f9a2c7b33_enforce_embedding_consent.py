"""enforce embedding consent

Revision ID: 1f0f9a2c7b33
Revises: 8c9914b0f51b
Create Date: 2026-08-04 06:31:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "1f0f9a2c7b33"
down_revision: str | None = "8c9914b0f51b"
branch_labels: str | None = None
depends_on: str | None = None


TRIGGER_FUNCTION = """
CREATE OR REPLACE FUNCTION enforce_face_embedding_biometric_consent()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    write_time timestamptz;
BEGIN
    write_time := statement_timestamp();

    IF NOT EXISTS (
        SELECT 1
        FROM consents c
        WHERE c.id = NEW.consent_id
          AND c.person_id = NEW.person_id
          AND c.consent_type = 'biometric_processing'
          AND c.policy_version = NEW.policy_version
          AND c.granted_at <= write_time
          AND (c.revoked_at IS NULL OR write_time < c.revoked_at)
    ) THEN
        RAISE EXCEPTION
            'active biometric enrollment consent is required for the current policy version'
            USING ERRCODE = '23514',
                  CONSTRAINT = 'ck_face_embeddings_active_biometric_consent';
    END IF;

    RETURN NEW;
END;
$$;
"""


def upgrade() -> None:
    op.add_column(
        "face_embeddings", sa.Column("policy_version", sa.String(length=64), nullable=True)
    )
    op.execute(
        """
        UPDATE face_embeddings fe
        SET policy_version = c.policy_version
        FROM consents c
        WHERE c.id = fe.consent_id
        """
    )
    op.alter_column("face_embeddings", "policy_version", nullable=False)
    op.create_check_constraint(
        op.f("ck_face_embeddings_policy_version_non_empty"),
        "face_embeddings",
        "policy_version <> ''",
    )
    op.execute(TRIGGER_FUNCTION)
    op.execute(
        """
        CREATE TRIGGER ck_face_embeddings_active_biometric_consent
        BEFORE INSERT OR UPDATE OF person_id, consent_id, policy_version, created_at
        ON face_embeddings
        FOR EACH ROW
        EXECUTE FUNCTION enforce_face_embedding_biometric_consent()
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS ck_face_embeddings_active_biometric_consent ON face_embeddings"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_face_embedding_biometric_consent()")
    op.drop_constraint(
        op.f("ck_face_embeddings_policy_version_non_empty"),
        "face_embeddings",
        type_="check",
    )
    op.drop_column("face_embeddings", "policy_version")
