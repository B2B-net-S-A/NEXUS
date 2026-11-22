"""Migracja 0748_drop_invoices_register (pusty rejestr faktur) i jej lustro w `entrypoint.sh`."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
MIGRATION = BACKEND / "alembic/versions/0748_drop_invoices_register.py"
ENTRYPOINT = BACKEND / "entrypoint.sh"


def _load():
    spec = importlib.util.spec_from_file_location(MIGRATION.stem, MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_drops_only_the_register_and_its_enums() -> None:
    # Najpierw tabela, potem typy, których używały jej kolumny; bez CASCADE.
    assert _load().drop_statements() == [
        "DROP TABLE IF EXISTS invoices",
        "DROP TYPE IF EXISTS invoicedirection",
        "DROP TYPE IF EXISTS invoicestatus",
    ]


def test_entrypoint_mirrors_every_statement_once() -> None:
    source = ENTRYPOINT.read_text(encoding="utf-8")
    for statement in _load().drop_statements():
        assert source.count(f'"{statement}"') == 1, statement


def test_entrypoint_no_longer_touches_the_table() -> None:
    source = ENTRYPOINT.read_text(encoding="utf-8")
    assert not re.search(r"\bALTER TABLE\s+(IF EXISTS\s+)?invoices\b", source)
    assert not re.search(r"CREATE TABLE IF NOT EXISTS\s+invoices\b", source)
    assert "table_name = 'invoices'" not in source


def test_contract_merge_no_longer_expects_the_foreign_key() -> None:
    # Audyt scalania blokuje też brakujący FK z listy, więc wpis znika z tabelą.
    from app.services.contract_merge import _KNOWN_CONTRACT_FKS

    assert "invoices" not in {table for table, _ in _KNOWN_CONTRACT_FKS}
