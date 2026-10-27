"""Tabela punktowa klienta (Excel) obok formularza CV (Word).

Revision ID: 0525_client_form_score_sheet
Revises: 0524_agreement_admin_details

Decyzja Artura 27.10.2026: CEZ do formularza CV ze SWZ dokłada Excel
z punktacją (zał. 5) — jeden na osobę, wypełniany przez NEXUS jak formularz.
Rodzaj wzoru (`client_form_kind`) i rodzaj wypełnionego dokumentu (`kind`).
SQL i powód: ``app/services/client_form_schema.py``. Lustro w ``entrypoint.sh``.

Równolegle #2700 (``0525_job_p0``) też stoi na 0524; rewizja, która wejdzie do
kolejki druga, przepina ``down_revision``.
"""

from alembic import op

from app.services import client_form_schema as schema

revision = "0525_client_form_score_sheet"
down_revision = "0524_agreement_admin_details"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in schema.SCORE_DDL:
        op.execute(statement)


def downgrade() -> None:
    for statement in schema.SCORE_DOWNGRADE_DDL:
        op.execute(statement)
