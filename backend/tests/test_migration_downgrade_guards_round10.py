"""Runda 10 (R10-N12-4): downgrade 0363/0368/0374 odmawia przy danych.

Wzór jak 0381/0383/0388/0390: blok DO z ``RAISE EXCEPTION`` na początku
``downgrade()``. Testy z bazą działają w transakcji wycofywanej na końcu —
nie wolno zostawić wiersza, który zablokowałby inny test.
"""

from __future__ import annotations

import ast
import importlib.util
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.database import AsyncSessionLocal

_VERSIONS = Path(__file__).resolve().parents[1] / "alembic" / "versions"

GUARDS = [
    ("0363_b2b_register_import.py", "REFUSE_WITH_EXCEL_ROWS", "0363"),
    (
        "0368_contract_termination_reversal.py",
        "REFUSE_WITH_TERMINATION_SNAPSHOTS",
        "0368",
    ),
    ("0374_trainee_call_lists.py", "REFUSE_WITH_TRAINEE_DATA", "0374"),
]


def _module(filename: str):
    spec = importlib.util.spec_from_file_location(filename, _VERSIONS / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(("filename", "attr", "code"), GUARDS)
def test_downgrade_runs_guard_before_anything_else(filename, attr, code):
    tree = ast.parse((_VERSIONS / filename).read_text(encoding="utf-8"))
    downgrade = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "downgrade"
    )
    first = downgrade.body[0]
    assert isinstance(first, ast.Expr) and isinstance(first.value, ast.Call)
    assert ast.unparse(first.value) == f"op.execute({attr})"
    guard = getattr(_module(filename), attr)
    assert f"Downgrade {code} odmawia" in guard


@pytest.mark.asyncio
@pytest.mark.parametrize(("filename", "attr", "code"), GUARDS)
async def test_guards_run_on_postgres(filename, attr, code):
    """Blok przechodzi albo odmawia WŁASNYM komunikatem — nigdy błędem
    składni czy nieznanej kolumny (stan wspólnej bazy CI jest nieznany)."""
    guard = getattr(_module(filename), attr)
    async with AsyncSessionLocal() as db:
        try:
            await db.execute(text(guard))
        except DBAPIError as exc:
            assert f"Downgrade {code} odmawia" in str(exc)
        finally:
            await db.rollback()


@pytest.mark.asyncio
async def test_0363_guard_refuses_with_excel_rows():
    guard = _module("0363_b2b_register_import.py").REFUSE_WITH_EXCEL_ROWS
    async with AsyncSessionLocal() as db:
        try:
            await db.execute(
                text(
                    "INSERT INTO b2b_generated_contracts "
                    "(contract_number, source, source_key, language, "
                    " signature_status, contract_status) "
                    "VALUES ('R10-TEST', 'excel', :k, 'pl', 'unsigned', "
                    " 'in_progress')"
                ),
                {"k": uuid.uuid4().hex},
            )
            with pytest.raises(DBAPIError, match="0363"):
                async with db.begin_nested():
                    await db.execute(text(guard))
        finally:
            await db.rollback()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("filename", "attr", "table", "code"),
    [
        (
            "0368_contract_termination_reversal.py",
            "REFUSE_WITH_TERMINATION_SNAPSHOTS",
            "contract_termination_snapshots",
            "0368",
        ),
        (
            "0374_trainee_call_lists.py",
            "REFUSE_WITH_TRAINEE_DATA",
            "trainee_call_items",
            "0374",
        ),
    ],
)
async def test_table_guards_refuse_with_rows(filename, attr, table, code):
    """Tabela tymczasowa o tej samej nazwie przesłania prawdziwą (pg_temp jest
    pierwszy w ścieżce) — wiersz bez kompletu kluczy obcych, całość wycofana."""
    guard = getattr(_module(filename), attr)
    async with AsyncSessionLocal() as db:
        try:
            await db.execute(text(f"CREATE TEMP TABLE {table} (id int)"))
            await db.execute(text(f"INSERT INTO {table} VALUES (1)"))
            with pytest.raises(DBAPIError, match=code):
                async with db.begin_nested():
                    await db.execute(text(guard))
        finally:
            await db.rollback()
