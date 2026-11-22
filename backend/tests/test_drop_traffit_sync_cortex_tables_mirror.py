"""Migracja 0714_drop_traffit_sync_cortex_trace (9 nieużywanych tabel Traffita i Cortexa) i jej lustro w `entrypoint.sh`."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
VERSIONS = BACKEND / "alembic/versions"
MIGRATION = VERSIONS / "0714_drop_traffit_sync_cortex_trace.py"
EARLIER = VERSIONS / "0667_drop_abandoned_tables.py"
# Późniejsze usunięcia z lustrem w tej samej liście (pusty rejestr faktur,
# stan dawnej pętli Compassa).
LATER = (
    VERSIONS / "0748_drop_invoices_register.py",
    VERSIONS / "0752_drop_compass_workdays_sync_state.py",
)
ENTRYPOINT = BACKEND / "entrypoint.sh"


def _load(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _names(module) -> set[str]:
    return {name for group in module.TABLE_GROUPS for name in group}


def _entrypoint_drops() -> set[str]:
    source = ENTRYPOINT.read_text(encoding="utf-8")
    found: set[str] = set()
    for body in re.findall(r'"DROP TABLE IF EXISTS ([^"]+)"', source):
        found |= {name.strip() for name in body.split(",") if name.strip()}
    return found


def test_migration_drops_exactly_the_decided_tables() -> None:
    groups = _load(MIGRATION).TABLE_GROUPS
    assert [len(group) for group in groups] == [7, 2]
    names = _names(_load(MIGRATION))
    assert len(names) == 9
    # Te cztery czyta kod: scalanie kandydatów, skrzynka webhooków, wyszukiwarka
    # i Słownik umiejętności.
    for kept in (
        "traffit_entity_links",
        "traffit_webhook_events",
        "cortex_skill_facts",
        "cortex_unmatched_terms",
    ):
        assert kept not in names


def test_every_entrypoint_drop_comes_from_a_decided_migration() -> None:
    later = set().union(*(_names(_load(path)) for path in LATER))
    assert _entrypoint_drops() == (
        _names(_load(EARLIER)) | _names(_load(MIGRATION)) | later
    )
    assert "CASCADE" not in " ".join(_load(MIGRATION).drop_statements())


def test_entrypoint_no_longer_creates_the_dropped_tables() -> None:
    source = ENTRYPOINT.read_text(encoding="utf-8")
    for name in _names(_load(MIGRATION)):
        assert not re.search(rf"CREATE TABLE IF NOT EXISTS\s+{name}\b", source), name
        assert not re.search(rf"\bON\s+{name}\b", source), name


def test_dropped_tables_have_no_model() -> None:
    """`create_all` w entrypoincie założyłby tabelę z modelu z powrotem po DROP."""
    import app.models  # noqa: F401
    from app.core.database import Base

    assert not _names(_load(MIGRATION)) & set(Base.metadata.tables)
