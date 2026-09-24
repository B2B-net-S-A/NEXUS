"""0371: CHECK okresu zamówienia i ``old_currency`` mają lustro w entrypoincie.

Prod alembic bywa osierocony — ``entrypoint.sh`` JEST wdrożeniem. Więz musi
być ``NOT VALID``: produkcja ma historyczne zamówienie z odwróconym okresem,
a walidacja istniejących wierszy wywróciłaby start kontenera. Kolumnę
``old_currency`` zapisuje listener przy KAŻDEJ zmianie zamówienia — bez lustra
pada każdy zapis zamówienia.
"""

from __future__ import annotations

import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ENTRYPOINT = (BACKEND / "entrypoint.sh").read_text()
MIGRATION = (
    BACKEND / "alembic" / "versions" / "0371_order_dates_and_currency_audit.py"
).read_text()

CHECK = (
    "CHECK (start_date IS NULL OR end_date IS NULL OR end_date >= start_date) NOT VALID"
)
OLD_CURRENCY = (
    "ALTER TABLE order_change_events ADD COLUMN IF NOT EXISTS old_currency VARCHAR(3)"
)


def _collapse(sql: str) -> str:
    return re.sub(r"\s+", " ", sql)


def test_check_is_mirrored_and_not_valid():
    flat = _collapse(ENTRYPOINT)
    assert "ADD CONSTRAINT ck_client_orders_dates" in flat
    assert CHECK in flat
    assert CHECK in _collapse(MIGRATION)


def test_check_lives_in_the_constraint_list():
    block = ENTRYPOINT[ENTRYPOINT.index("_CONSTRAINT_STATEMENTS = [") :]
    assert "ck_client_orders_dates" in block


def test_old_currency_column_is_mirrored_and_on_the_model():
    from app.models.order_change_event import OrderChangeEvent

    assert OLD_CURRENCY in ENTRYPOINT
    assert OLD_CURRENCY in MIGRATION
    assert "old_currency" in OrderChangeEvent.__table__.columns


def test_migration_chains_after_teams_prep():
    assert 'revision = "0371_order_dates_and_currency_audit"' in MIGRATION
    assert 'down_revision = "0370_teams_prep_transcripts"' in MIGRATION
