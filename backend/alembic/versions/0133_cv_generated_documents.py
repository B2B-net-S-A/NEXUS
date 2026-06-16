"""Generator CV B2B — log wygenerowanych CV (lista w panelu + ponowne pobranie)

Revision ID: 0133_cv_generated_documents
Revises: 0132_b2b_render_payload
Create Date: 2026-06-16

Context:
    Generator CV przestaje wymuszać auto-pobranie do „Pobranych" — każda udana
    generacja loguje się tu z ``render_payload`` (candidate_data), żeby DOCX dało
    się podejrzeć/pobrać ponownie z listy „Wygenerowane CV" w panelu, bez
    ponownego (płatnego) wywołania Claude. Wzorzec 1:1 jak b2b_generated_contracts.

Safety net: idempotentne (``CREATE TABLE/INDEX IF NOT EXISTS``).
"""

from alembic import op

revision = "0133_cv_generated_documents"
down_revision = "0132_b2b_render_payload"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS cv_generated_documents (
            id              SERIAL PRIMARY KEY,
            candidate_id    INTEGER REFERENCES candidates (id) ON DELETE SET NULL,
            job_id          INTEGER REFERENCES jobs (id) ON DELETE SET NULL,
            candidate_name  VARCHAR(300) NOT NULL,
            position        VARCHAR(300),
            language        VARCHAR(2) NOT NULL DEFAULT 'pl',
            blind           BOOLEAN NOT NULL DEFAULT false,
            mode            VARCHAR(10) NOT NULL DEFAULT 'new',
            filename        VARCHAR(500) NOT NULL,
            render_payload  JSONB,
            created_by      INTEGER REFERENCES users (id) ON DELETE SET NULL,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_cv_generated_documents_candidate_id "
        "ON cv_generated_documents (candidate_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_cv_generated_documents_created_at "
        "ON cv_generated_documents (created_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS cv_generated_documents")
