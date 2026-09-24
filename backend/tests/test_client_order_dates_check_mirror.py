"""0371: CHECK okresu zamówienia ma lustro w entrypoincie (audyt 24.09.2026, S7).

Prod alembic bywa osierocony — ``entrypoint.sh`` JEST wdrożeniem. Więz musi
być ``NOT VALID``: produkcja ma historyczne zamówienie z odwróconym okresem,
a walidacja istniejących wierszy wywróciłaby start kontenera.
"""

from __future__ import annotations

import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ENTRYPOINT = (BACKEND / "entrypoint.sh").read_text()
MIGRATION = (
    BACKEND / "alembic" / "versions" / "0371_client_order_dates_check.py"
).read_text()

CHECK = (
    "CHECK (start_date IS NULL OR end_date IS NULL OR end_date >= start_date) NOT VALID"
)


def _collapse(sql: str) -> str:
    return re.sub(r"\s+", " ", sql)


def test_check_is_mirrored_and_not_valid():
    flat = _collapse(ENTRYPOINT)
    assert "ADD CONSTRAINT ck_client_orders_dates" in flat
    assert CHECK in flat
    assert CHECK in _collapse(MIGRATION)


def test_mirror_lives_in_the_constraint_list():
    block = ENTRYPOINT[ENTRYPOINT.index("_CONSTRAINT_STATEMENTS = [") :]
    assert "ck_client_orders_dates" in block


def test_migration_chains_after_teams_prep():
    assert 'revision = "0371_client_order_dates_check"' in MIGRATION
    assert 'down_revision = "0370_teams_prep_transcripts"' in MIGRATION
