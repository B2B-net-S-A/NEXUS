"""Pliki kandydata: „Usuń z profilu” — kto i kiedy (13.10.2026).

Revision ID: 0435_candidate_document_removed
Revises: 0434_cv_editor_command_ai_key

Admin i Head of Recruitment mogą usunąć plik z profilu kandydata. Wiersz
i plik w magazynie zostają (CV nie kasujemy nigdy) — plik chowa istniejące
`source_deleted_at`, a te dwie kolumny zapisują, że zrobił to człowiek
w NEXUSIE (synchronizacja poczty nie wskrzesza wtedy pliku).

Lustro DDL: `_COLUMN_STATEMENTS` w `entrypoint.sh`.
"""

from alembic import op

revision = "0435_candidate_document_removed"
down_revision = "0434_cv_editor_command_ai_key"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE candidate_documents "
        "ADD COLUMN IF NOT EXISTS removed_at TIMESTAMPTZ"
    )
    op.execute(
        "ALTER TABLE candidate_documents ADD COLUMN IF NOT EXISTS removed_by "
        "INTEGER REFERENCES users(id) ON DELETE SET NULL"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE candidate_documents DROP COLUMN IF EXISTS removed_by")
    op.execute("ALTER TABLE candidate_documents DROP COLUMN IF EXISTS removed_at")
