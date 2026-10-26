"""Formularz CV klienta wypełniony dla pary osoba × rekrutacja + klucz AI.

Revision ID: 0522_candidate_client_forms
Revises: 0521_client_form_documents

PR 2 z 3 (decyzje Artura 26.10.2026): NEXUS wypełnia formularz CV klienta
z Plików rekrutacji danymi z CV, screeningu i notatek. Tabela ma jedno źródło
(``app/services/client_form_schema.py``); klucz AI ``client_form_fill``
z wierszem w ``ai_features`` — lustro w ``entrypoint.sh``.
"""

from alembic import op

from app.services import client_form_schema as schema

revision = "0522_candidate_client_forms"
down_revision = "0521_client_form_documents"
branch_labels = None
depends_on = None

_KEY = "client_form_fill"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"ALTER TYPE aifeaturekey ADD VALUE IF NOT EXISTS '{_KEY}'")
    op.execute(
        "INSERT INTO ai_features (feature, enabled, monthly_limit, created_at, updated_at) "
        f"SELECT '{_KEY}', TRUE, 0, NOW(), NOW() "
        "WHERE NOT EXISTS "
        f"(SELECT 1 FROM ai_features WHERE feature = '{_KEY}')"
    )
    for statement in schema.FILL_DDL:
        op.execute(statement)


# Wartość enumu zostaje po downgrade (Postgres nie ma DROP VALUE), a kod sprzed
# tej rewizji jej nie zna — wpis w dzienniku AI dałby 500 przy odczycie.
REFUSE_WITH_LIVE_ROWS = f"""DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM ai_usage_log WHERE feature::text = '{_KEY}') THEN
        RAISE EXCEPTION 'Downgrade 0522 odmawia: są wpisy {_KEY}, których kod sprzed tej rewizji nie odczyta.';
    END IF;
END $$"""


def downgrade() -> None:
    op.execute(REFUSE_WITH_LIVE_ROWS)
    op.execute(f"DELETE FROM ai_features WHERE feature = '{_KEY}'")
    for statement in schema.FILL_DOWNGRADE_DDL:
        op.execute(statement)
