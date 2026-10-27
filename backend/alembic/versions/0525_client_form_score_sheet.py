"""Tabela punktowa klienta (Excel) obok formularza CV (Word).

Revision ID: 0525_client_form_score_sheet
Revises: 0525_job_p0

Decyzja Artura 27.10.2026: CEZ do formularza CV ze SWZ dokłada Excel
z punktacją (zał. 5) — jeden na osobę, wypełniany przez NEXUS jak formularz.
Rodzaj wzoru (`client_form_kind`) i rodzaj wypełnionego dokumentu (`kind`).
SQL i powód: ``app/services/client_form_schema.py``. Lustro w ``entrypoint.sh``.

Stała na 0524 równolegle z ``0525_job_p0`` (#2700); ta weszła do kolejki
druga, więc stoi za nią (jeden czubek łańcucha).
"""

from alembic import op

from app.services import client_form_schema as schema

revision = "0525_client_form_score_sheet"
down_revision = "0525_job_p0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in schema.SCORE_DDL:
        op.execute(statement)


def downgrade() -> None:
    for statement in schema.SCORE_DOWNGRADE_DDL:
        op.execute(statement)
