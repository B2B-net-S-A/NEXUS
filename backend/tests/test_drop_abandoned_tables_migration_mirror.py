"""Migracja usuwająca 70 porzuconych tabel i jej lustro w `entrypoint.sh`."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
MIGRATION = BACKEND / "alembic/versions/0667_drop_abandoned_tables.py"
ENTRYPOINT = BACKEND / "entrypoint.sh"


def _migration():
    spec = importlib.util.spec_from_file_location("drop_abandoned", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _dropped(sql: str) -> set[str]:
    found: set[str] = set()
    for body in re.findall(r"DROP TABLE IF EXISTS ([^\"';]+)", sql):
        found |= {name.strip() for name in body.split(",") if name.strip()}
    return found


def test_migration_drops_exactly_the_decided_groups() -> None:
    groups = _migration().TABLE_GROUPS
    assert [len(group) for group in groups] == [22, 33, 14, 1]
    names = [name for group in groups for name in group]
    assert len(set(names)) == 70
    assert "embedding_index_queue" not in names
    assert "dr_sourcer_category_assignments" not in names
    assert "dr_przetargi_allocations" not in names


def test_mirror_matches_migration_without_cascade() -> None:
    module = _migration()
    expected = {name for group in module.TABLE_GROUPS for name in group}
    source = ENTRYPOINT.read_text(encoding="utf-8")
    assert (
        _dropped(";".join(re.findall(r'"(DROP TABLE IF EXISTS [^"]+)"', source)))
        == expected
    )
    for statement in module.OUTSIDE_FK_DROPS:
        assert statement in source
    assert "CASCADE" not in " ".join(module.drop_statements())


def test_entrypoint_no_longer_alters_signature_links() -> None:
    source = ENTRYPOINT.read_text(encoding="utf-8")
    assert "ALTER TABLE signature_links" not in source
    assert "ON signature_links" not in source
