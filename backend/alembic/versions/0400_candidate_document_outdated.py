"""Pliki kandydata: plakietka „nieaktualne” i autor wgrania.

Revision ID: 0400_candidate_document_outdated
Revises: 0399_notes_pin_replies

Decyzja 29.09.2026: stare CV zostaje w teczce (nic nie kasuje CV), ale
rekruter może je oznaczyć jako nieaktualne — plakietka na liście plików
i blokada ustawienia go jako głównego. Wyszukiwanie, `raw_cv_text`
i wektory się nie zmieniają. `uploaded_by` = kto wgrał plik (starsze
wiersze zostają puste; lista pokazuje wtedy samą datę albo „z Traffita”).

Lustro DDL: `_COLUMN_STATEMENTS` w `entrypoint.sh`.
"""

from alembic import op

revision = "0400_candidate_document_outdated"
down_revision = "0399_notes_pin_replies"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE candidate_documents "
        "ADD COLUMN IF NOT EXISTS outdated_at TIMESTAMPTZ"
    )
    op.execute(
        "ALTER TABLE candidate_documents ADD COLUMN IF NOT EXISTS outdated_by "
        "INTEGER REFERENCES users(id) ON DELETE SET NULL"
    )
    op.execute(
        "ALTER TABLE candidate_documents ADD COLUMN IF NOT EXISTS uploaded_by "
        "INTEGER REFERENCES users(id) ON DELETE SET NULL"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE candidate_documents DROP COLUMN IF EXISTS uploaded_by")
    op.execute("ALTER TABLE candidate_documents DROP COLUMN IF EXISTS outdated_by")
    op.execute("ALTER TABLE candidate_documents DROP COLUMN IF EXISTS outdated_at")
