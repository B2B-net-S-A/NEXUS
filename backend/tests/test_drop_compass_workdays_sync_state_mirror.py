"""Migracja 0752_drop_compass_workdays_sync_state (ślad Compassa) i jej lustro w `entrypoint.sh`."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
MIGRATION = BACKEND / "alembic/versions/0752_drop_compass_workdays_sync_state.py"
ENTRYPOINT = BACKEND / "entrypoint.sh"
TABLE = "compass_workdays_sync_state"


def _load():
    spec = importlib.util.spec_from_file_location(MIGRATION.stem, MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_drops_only_the_compass_state_table_and_keys() -> None:
    module = _load()
    # Bez CASCADE: nieznana zależność ma przerwać migrację głośno.
    assert module.drop_statements() == [f"DROP TABLE IF EXISTS {TABLE}"]
    assert module.delete_settings_statement() == (
        "DELETE FROM app_settings WHERE key IN "
        "('compass_lifecycle_state', 'service_account_retired_key_ids')"
    )


def test_entrypoint_mirrors_the_drop_once_and_no_longer_creates_the_table() -> None:
    source = ENTRYPOINT.read_text(encoding="utf-8")
    for statement in _load().drop_statements():
        assert source.count(f'"{statement}"') == 1, statement
    assert not re.search(rf"CREATE TABLE IF NOT EXISTS\s+{TABLE}\b", source)
    assert not re.search(rf"INSERT INTO\s+{TABLE}\b", source)


def test_dropped_table_has_no_model() -> None:
    """`create_all` w entrypoincie założyłby tabelę z modelu z powrotem po DROP."""
    import app.models  # noqa: F401
    from app.core.database import Base

    assert TABLE not in Base.metadata.tables


def test_retired_setting_keys_have_no_reader() -> None:
    """Klucze kasuje migracja, więc żaden moduł `app/` nie może ich czytać."""
    keys = _load().RETIRED_SETTING_KEYS
    for path in (BACKEND / "app").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for key in keys:
            assert key not in text, f"{path.relative_to(BACKEND)}: {key}"
