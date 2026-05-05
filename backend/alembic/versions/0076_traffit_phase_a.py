"""Faza A: users.external_id + candidate_documents (multi-file CV)

Revision ID: 0076_traffit_phase_a
Revises: 0075_traffit_phase5b_external_ids
Create Date: 2026-05-05 14:00:00.000000

Faza A migracji Traffit→Nexus zamyka 3 luki:
1. **User attribution** — Traffit ma 141 userów, Nexus 10. `import_users` phase
   tworzy 131 brakujących jako disabled accounts (`is_active=false`,
   `password_hash='!imported-from-traffit-no-login!'`). Wymaga external_id na
   `users` żeby UPSERT był idempotentny i żebyśmy mogli odróżnić Traffit-imported
   userów od ręcznie utworzonych.
2. **Multi-file CV** — istniejący `candidates.cv_file_content` to single binary;
   Traffit ma multiple files per kandydat (np. CV.pdf + CV.docx + motivation
   letter). Nowa tabela `candidate_documents` z `is_primary` markerem zachowuje
   wszystkie pliki, każdy z `external_id = "{traffit_employee_id}-{file_id}"`.
3. (Pipelines re-run i notes promotion to osobne migracje 0077; tutaj tylko
   schema).

Idempotent (IF NOT EXISTS everywhere).
"""

from alembic import op
import sqlalchemy as sa

revision = "0076_traffit_phase_a"
down_revision = "0075_traffit_phase5b_external_ids"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. users.external_id / users.external_source
    op.execute(
        sa.text(
            """
            ALTER TABLE users
              ADD COLUMN IF NOT EXISTS external_id VARCHAR(100),
              ADD COLUMN IF NOT EXISTS external_source VARCHAR(50) DEFAULT 'manual'
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS
              ux_users_external_source_id
              ON users (external_source, external_id)
              WHERE external_id IS NOT NULL
            """
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_users_external_source "
            "ON users (external_source)"
        )
    )
    op.execute(
        sa.text("UPDATE users SET external_source='manual' WHERE external_source IS NULL")
    )

    # 2. candidate_documents — multi-file CV per kandydat
    op.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS candidate_documents (
                id              SERIAL PRIMARY KEY,
                candidate_id    INTEGER NOT NULL
                                  REFERENCES candidates(id) ON DELETE CASCADE,
                filename        VARCHAR(500) NOT NULL,
                file_content    BYTEA,
                content_type    VARCHAR(100),
                size_bytes      INTEGER,
                is_primary      BOOLEAN NOT NULL DEFAULT FALSE,
                uploaded_at     TIMESTAMP WITH TIME ZONE,
                external_id     VARCHAR(100),
                external_source VARCHAR(50) DEFAULT 'manual',
                created_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                updated_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_candidate_documents_candidate_id "
            "ON candidate_documents (candidate_id)"
        )
    )
    op.execute(
        sa.text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS
              ux_candidate_documents_external_source_id
              ON candidate_documents (external_source, external_id)
              WHERE external_id IS NOT NULL
            """
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_candidate_documents_external_source "
            "ON candidate_documents (external_source)"
        )
    )
    op.execute(
        sa.text(
            """
            CREATE INDEX IF NOT EXISTS ix_candidate_documents_primary
              ON candidate_documents (candidate_id, is_primary)
              WHERE is_primary = TRUE
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP TABLE IF EXISTS candidate_documents"))
    op.execute(sa.text("DROP INDEX IF EXISTS ix_users_external_source"))
    op.execute(sa.text("DROP INDEX IF EXISTS ux_users_external_source_id"))
    op.execute(
        sa.text(
            """
            ALTER TABLE users
              DROP COLUMN IF EXISTS external_source,
              DROP COLUMN IF EXISTS external_id
            """
        )
    )
