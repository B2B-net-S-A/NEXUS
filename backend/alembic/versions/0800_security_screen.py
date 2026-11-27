"""Ekran Ustawienia → Bezpieczeństwo: znaleziska, zdarzenia, rutyny.

Revision ID: 0800_security_screen
Revises: 0799_cp_document_invoice_fields

Decyzja Artura z 27.11.2026 (research „Tarcza NEXUSA”, polecenie „zbuduj
wszystko z raportu”): tabele ``security_findings``, ``security_events``,
``security_routines`` (z zasiewem pięciu rutyn) i ``security_source_states``
oraz dzwonek ``security_routine_overdue`` dla adminów.

Same dodania — stary kod działa na nowym schemacie. Jedno źródło DDL:
``app/services/security_schema.py``; lustro w ``entrypoint.sh`` — pilnuje
``tests/test_security_schema.py``.
"""

from alembic import op

from app.services import security_schema as schema

revision = "0800_security_screen"
down_revision = "0799_cp_document_invoice_fields"
branch_labels = None
depends_on = None

# Etykiety enuma zostają (Postgres ich nie usuwa); kod sprzed tej rewizji nie
# zna typu dzwonka, więc downgrade odmawia przy żywych wierszach.
REFUSE_WITH_LIVE_ROWS = """DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM notifications
        WHERE notification_type::text = 'security_routine_overdue'
    ) THEN
        RAISE EXCEPTION 'Downgrade 0800 odmawia: są dzwonki security_routine_overdue, których kod sprzed tej rewizji nie odczyta.';
    END IF;
END $$"""


def upgrade() -> None:
    with op.get_context().autocommit_block():
        for statement in schema.ENUM_STATEMENTS:
            op.execute(statement)
    for statement in schema.TABLE_DDL + schema.SEED_DDL:
        op.execute(statement)


def downgrade() -> None:
    op.execute(REFUSE_WITH_LIVE_ROWS)
    for statement in schema.DOWNGRADE_DDL:
        op.execute(statement)
