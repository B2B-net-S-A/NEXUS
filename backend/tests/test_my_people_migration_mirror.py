"""0334: tabele „Moi ludzie" mają lustro w entrypoincie.

Prod alembic bywa osierocony — `entrypoint.sh` JEST wdrożeniem. Model deklaruje
obie tabele, a `/api/health/deep` je sonduje, więc brak lustra = 503 na prodzie
przy zielonym CI (gdzie działa migracja).
"""

from __future__ import annotations

import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ENTRYPOINT = (BACKEND / "entrypoint.sh").read_text()
MIGRATION = (BACKEND / "alembic" / "versions" / "0334_my_people.py").read_text()


def _collapse(sql: str) -> str:
    return re.sub(r"\s+", " ", sql)


def test_tables_constraints_and_indexes_are_mirrored():
    flat = _collapse(ENTRYPOINT)
    for needle in (
        "CREATE TABLE IF NOT EXISTS my_people_overrides",
        "CREATE TABLE IF NOT EXISTS my_people_job_matches",
        "CONSTRAINT uq_my_people_overrides_user_candidate UNIQUE (user_id, candidate_id)",
        "CONSTRAINT ck_my_people_overrides_kind CHECK (kind IN ('snoozed', 'pinned'))",
        "CHECK (kind <> 'snoozed' OR reason IS NOT NULL)",
        "UNIQUE (user_id, job_id, candidate_id)",
        # Nazwa i definicja indeksu stoją w dwóch sklejanych literałach.
        "ix_my_people_job_matches_user_seen",
        "ON my_people_job_matches (user_id, seen_at)",
        "ix_candidate_stages_moved_by_stage ON candidate_stages (moved_by, stage)",
        "ADD VALUE IF NOT EXISTS 'my_people_match'",
    ):
        assert needle in flat, needle


def test_every_named_object_in_the_migration_exists_in_the_entrypoint():
    names = set(re.findall(r'"((?:uq|ck|ix)_[a-z_]+)"', MIGRATION))
    assert names, "migracja nie nazywa żadnych obiektów?"
    for name in names:
        assert name in ENTRYPOINT, name


def test_migration_chains_after_0333():
    assert 'revision = "0334_my_people"' in MIGRATION
    assert 'down_revision = "0333_job_proposals"' in MIGRATION
