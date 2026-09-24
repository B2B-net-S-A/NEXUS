"""Prepy w Teams (0370): lustro migracji w entrypoint.sh i rejestracje.

Prod alembic bywa osierocony — entrypoint JEST wdrożeniem schematu, więc
tabele, indeksy, wartości enumów i seed klucza AI muszą być w nim 1:1.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def _migration_ddl() -> list[str]:
    ns: dict = {}
    source = (ROOT / "alembic/versions/0370_teams_prep_transcripts.py").read_text()
    exec(compile(source.replace("from alembic import op", ""), "m", "exec"), ns)
    return [
        ns[name]
        for name in (
            "CREATE_PREP_MEETINGS",
            "CREATE_PREP_TRANSCRIPTS",
            "CREATE_PREP_REVIEWS",
            "CREATE_FETCH_QUEUE_INDEX",
            "CREATE_PAIR_INDEX",
        )
    ]


def test_every_ddl_statement_is_mirrored_in_entrypoint() -> None:
    entry = _squash((ROOT / "entrypoint.sh").read_text())
    for ddl in _migration_ddl():
        assert _squash(ddl) in entry, ddl.splitlines()[0]


def test_enum_values_and_ai_seed_are_mirrored() -> None:
    entry = (ROOT / "entrypoint.sh").read_text()
    assert "ALTER TYPE aifeaturekey ADD VALUE IF NOT EXISTS 'prep_review'" in entry
    assert (
        "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'prep_attention'" in entry
    )
    assert "SELECT 'prep_review', TRUE, 0" in entry


def test_tables_are_probed_by_deep_health() -> None:
    main = (ROOT / "app/main.py").read_text()
    for table in ("prep_meetings", "prep_transcripts", "prep_reviews"):
        assert f'("{table}",' in main


def test_every_personal_data_table_cascades_with_the_candidate() -> None:
    for ddl in _migration_ddl()[:3]:
        assert (
            "candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE"
            in _squash(ddl)
        )
