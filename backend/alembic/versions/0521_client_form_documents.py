"""Formularz CV klienta zamiast CV firmowego: flaga klienta i wzór w Plikach rekrutacji.

Revision ID: 0521_client_form_documents
Revises: 0520_talent_pool_team_visible

Decyzje Artura 26.10.2026 (prośba Michała, CEZ): u klienta z formularzem
NEXUS wypełnia wzór z Plików rekrutacji zamiast robić CV firmowe. SQL
i powód: ``app/services/client_form_schema.py``. Lustro w ``entrypoint.sh``.
"""

from alembic import op

from app.services import client_form_schema as schema

revision = "0521_client_form_documents"
down_revision = "0520_talent_pool_team_visible"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in schema.ALL_DDL:
        op.execute(statement)


def downgrade() -> None:
    for statement in schema.DOWNGRADE_DDL:
        op.execute(statement)
