"""Kolumny usuniętej telefonii zdjęte w migracji 0682 i w lustrze entrypointu.

Alembic na produkcji bywa osierocony, więc wdrożeniem schematu jest też
``entrypoint.sh``: każde ``DROP COLUMN`` z migracji musi tam stać 1:1, a model
nie może już deklarować tych kolumn (ORM czytałby nieistniejącą kolumnę przy
każdym odczycie użytkownika).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.models.call import Call
from app.models.user import User

pytestmark = pytest.mark.static

BACKEND = Path(__file__).resolve().parents[1]
MIGRATION = BACKEND / "alembic" / "versions" / "0682_drop_telephony_columns.py"
ENTRYPOINT = BACKEND / "entrypoint.sh"

DROPS = (
    "ALTER TABLE calls DROP COLUMN IF EXISTS cloudtalk_call_id",
    "ALTER TABLE calls DROP COLUMN IF EXISTS cloudtalk_agent_id",
    "ALTER TABLE users DROP COLUMN IF EXISTS cloudtalk_agent_id",
)


def _upgrade_body() -> str:
    source = MIGRATION.read_text(encoding="utf-8")
    return source.split("def upgrade()", 1)[1].split("def downgrade()", 1)[0]


def test_migration_and_entrypoint_drop_the_same_columns() -> None:
    upgrade = _upgrade_body()
    entrypoint = ENTRYPOINT.read_text(encoding="utf-8")
    for statement in DROPS:
        assert statement in upgrade
        assert f'"{statement}",' in entrypoint


def test_models_no_longer_declare_telephony_columns() -> None:
    assert not {c for c in Call.__table__.columns.keys() if "cloudtalk" in c}
    assert not {c for c in User.__table__.columns.keys() if "cloudtalk" in c}


def test_entrypoint_reads_dropped_columns_nowhere_else() -> None:
    """Jednorazowy cutover 0210 w lustrze nie może czytać zdjętej kolumny.

    Na świeżej bazie bez znacznika 0210 entrypoint uruchamia ten blok; odczyt
    ``users.cloudtalk_agent_id`` po DROP wywracałby go przy każdym starcie.
    """
    entrypoint = ENTRYPOINT.read_text(encoding="utf-8")
    hits = [
        line.strip()
        for line in entrypoint.splitlines()
        if re.search("cloudtalk", line, re.IGNORECASE)
    ]
    assert hits == [f'"{statement}",' for statement in DROPS]
