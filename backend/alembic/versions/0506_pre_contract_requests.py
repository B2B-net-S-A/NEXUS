"""Prośby o umowę przedwstępną przy osobie w rekrutacji (21.10.2026).

Revision ID: 0506_pre_contract_requests
Revises: 0505_prep_review_configs

* ``pre_contract_requests`` — prośba DL / HoR / rekrutera o przedwstępną dla
  pary (kandydat, rekrutacja), jej droga do podpisu i ważność; najwyżej jedna
  w toku na parę (indeks częściowy),
* ``pre_contract_watchers`` — kto widzi stan i dostaje dzwonki,
* ``pre_contract_events`` — historia kroków,
* typ powiadomienia ``pre_contract``.

SQL w ``app/services/pre_contract_schema.py`` — jedno źródło z lustrem
w ``entrypoint.sh`` (alembic na prodzie bywa osierocony).
"""

from alembic import op

from app.services import pre_contract_schema as schema

revision = "0506_pre_contract_requests"
down_revision = "0505_prep_review_configs"
branch_labels = None
depends_on = None

# Wartość enuma zostaje po downgrade (Postgres nie ma DROP VALUE), a kod
# sprzed tej rewizji jej nie zna — powiadomienie takiego typu dałoby 500.
REFUSE_WITH_LIVE_ROWS = """DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM notifications
        WHERE notification_type::text = 'pre_contract'
    ) THEN
        RAISE EXCEPTION 'Downgrade 0506 odmawia: notifications ma wpisy o przedwstępnych, których kod sprzed tej rewizji nie odczyta.';
    END IF;
END $$"""


def upgrade() -> None:
    # ADD VALUE wymaga autocommitu (nie może żyć w transakcji migracji).
    with op.get_context().autocommit_block():
        op.execute(schema.ENUM_DDL)
    for statement in schema.ALL_DDL:
        op.execute(statement)


def downgrade() -> None:
    op.execute(REFUSE_WITH_LIVE_ROWS)
    for statement in schema.DOWNGRADE_DDL:
        op.execute(statement)
