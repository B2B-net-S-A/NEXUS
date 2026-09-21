"""0336: tabela własnego pulpitu ma lustro w entrypoincie.

Prod alembic bywa osierocony — `entrypoint.sh` JEST wdrożeniem. Model deklaruje
tabelę, a `/api/health/deep` ją sonduje, więc brak lustra = 503 na prodzie
przy zielonym CI (gdzie działa migracja).
"""

from __future__ import annotations

import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ENTRYPOINT = (BACKEND / "entrypoint.sh").read_text()
MIGRATION = (BACKEND / "alembic" / "versions" / "0336_user_dashboards.py").read_text()


def _collapse(sql: str) -> str:
    return re.sub(r"\s+", " ", sql)


def test_table_is_mirrored():
    flat = _collapse(ENTRYPOINT)
    for needle in (
        "CREATE TABLE IF NOT EXISTS user_dashboards",
        "user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE",
        "layout JSONB NOT NULL DEFAULT '{\"tiles\": []}'::jsonb",
        "version INTEGER NOT NULL DEFAULT 0",
        "CONSTRAINT ck_user_dashboards_version CHECK (version >= 0)",
    ):
        assert needle in flat, needle


def test_every_named_object_in_the_migration_exists_in_the_entrypoint():
    names = set(re.findall(r'"((?:uq|ck|ix)_[a-z_]+)"', MIGRATION))
    assert names, "migracja nie nazywa żadnych obiektów?"
    for name in names:
        assert name in ENTRYPOINT, name


def test_migration_chains_after_0335():
    assert 'revision = "0336_user_dashboards"' in MIGRATION
    assert 'down_revision = "0335_recruitment_automations"' in MIGRATION
