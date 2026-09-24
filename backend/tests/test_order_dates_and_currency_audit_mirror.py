"""0373: ``old_currency`` ma lustro w entrypoincie; okres zamówienia NIE jest więzem.

Prod alembic bywa osierocony — ``entrypoint.sh`` JEST wdrożeniem. Okres
(koniec nie przed startem) pilnuje API: CHECK — także ``NOT VALID`` — Postgres
sprawdza przy każdym UPDATE wiersza, a produkcja ma historyczne zamówienie
z odwróconym okresem (blokowałoby zapis i masowe przebiegi skanera). Kolumnę
``old_currency`` zapisuje listener przy KAŻDEJ zmianie zamówienia — bez lustra
pada każdy zapis zamówienia.
"""

from __future__ import annotations

import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ENTRYPOINT = (BACKEND / "entrypoint.sh").read_text()
MIGRATION = (
    BACKEND / "alembic" / "versions" / "0373_order_dates_and_currency_audit.py"
).read_text()

OLD_CURRENCY = (
    "ALTER TABLE order_change_events ADD COLUMN IF NOT EXISTS old_currency VARCHAR(3)"
)


def _collapse(sql: str) -> str:
    return re.sub(r"\s+", " ", sql)


def test_order_period_is_not_a_database_constraint():
    assert "ADD CONSTRAINT ck_client_orders_dates" not in _collapse(ENTRYPOINT)
    assert "ADD CONSTRAINT ck_client_orders_dates" not in _collapse(MIGRATION)


def test_old_currency_column_is_mirrored_and_on_the_model():
    from app.models.order_change_event import OrderChangeEvent

    assert OLD_CURRENCY in ENTRYPOINT
    assert OLD_CURRENCY in MIGRATION
    assert "old_currency" in OrderChangeEvent.__table__.columns


def test_migration_chains_after_candidate_followups():
    assert 'revision = "0373_order_dates_and_currency_audit"' in MIGRATION
    assert 'down_revision = "0372_candidate_followups"' in MIGRATION
