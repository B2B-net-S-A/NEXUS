"""0353: odhaczenia zmian i pobrania PDF-ów mają lustro w entrypoincie.

Prod alembic bywa osierocony — `entrypoint.sh` JEST wdrożeniem. Model deklaruje
obie tabele, a `/api/health/deep` je sonduje, więc brak lustra = 503 na prodzie
przy zielonym CI (gdzie działa migracja) i padnięty checkbox „Zrobione”.
"""

from __future__ import annotations

import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ENTRYPOINT = (BACKEND / "entrypoint.sh").read_text()
MIGRATION = (
    BACKEND / "alembic" / "versions" / "0353_order_change_checks.py"
).read_text()


def _collapse(sql: str) -> str:
    return re.sub(r"\s+", " ", sql)


def test_tables_and_constraints_are_mirrored():
    flat = _collapse(ENTRYPOINT)
    migration = _collapse(MIGRATION)
    for needle in (
        "CREATE TABLE IF NOT EXISTS order_change_checks",
        "CREATE TABLE IF NOT EXISTS order_pdf_downloads",
        "CHECK (action IN ('checked', 'unchecked'))",
        "CHECK (tab IN ('changes', 'entries', 'exits', 'ending', 'gaps'))",
        "PRIMARY KEY (user_id, file_kind, file_id)",
        "CHECK (file_kind IN ('order', 'group', 'amendment'))",
        "ON order_change_checks (item_key, id)",
    ):
        assert needle in flat, needle
        assert needle in migration, needle


def test_every_named_object_in_the_migration_exists_in_the_entrypoint():
    names = set(re.findall(r"\b((?:ck|ix)_order_[a-z_]+)", MIGRATION))
    assert names, "migracja nie nazywa żadnych obiektów?"
    for name in names:
        assert name in ENTRYPOINT, name


def test_migration_chains_after_0352():
    assert 'revision = "0353_order_change_checks"' in MIGRATION
    assert 'down_revision = "0352_pipeline_v4"' in MIGRATION
