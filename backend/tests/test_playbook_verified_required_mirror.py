"""0495: kolumna karty klienta ma lustro 1:1 w ``entrypoint.sh``.

Alembic na produkcji bywa osierocony — wdrożeniem schematu jest entrypoint.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def _migration():
    path = BACKEND / "alembic/versions/0495_playbook_verified_required.py"
    spec = importlib.util.spec_from_file_location("m0495", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_entrypoint_mirrors_the_migration() -> None:
    entrypoint = (BACKEND / "entrypoint.sh").read_text(encoding="utf-8")
    mirrored = (
        '"ALTER TABLE client_playbooks "\n'
        '    "ADD COLUMN IF NOT EXISTS verified_required_fields JSONB NULL"'
    )
    assert mirrored in entrypoint
    module = _migration()
    assert module.revision == "0495_playbook_verified_required"
    assert module.UPGRADE_SQL == (
        "ALTER TABLE client_playbooks "
        "ADD COLUMN IF NOT EXISTS verified_required_fields JSONB NULL"
    )
