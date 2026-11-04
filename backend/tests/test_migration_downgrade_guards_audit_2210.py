"""Audyt 22.10.2026 (F80): downgrade 0504 i 0486 odmawia przy danych.

Postgres nie usuwa etykiet enuma, a kod sprzed rewizji ich nie zna: zamknięta
rekrutacja z powodem ``duplicate``/``no_match`` albo wpis dziennika AI
``expense_document_read`` dałyby po cofnięciu 500. Wzór jak 0485/0488 i
``test_migration_downgrade_guards_round10.py``: blok DO z ``RAISE EXCEPTION``
przed resztą ``downgrade()``.
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.database import AsyncSessionLocal

_VERSIONS = Path(__file__).resolve().parents[1] / "alembic" / "versions"

GUARDS = [
    ("0504_job_close_reason_neutral.py", "REFUSE_WITH_NEUTRAL_CLOSES", "0504"),
    ("0486_approval_settlement.py", "REFUSE_WITH_USAGE", "0486"),
]


def _module(filename: str):
    spec = importlib.util.spec_from_file_location(filename, _VERSIONS / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _downgrade_calls(filename: str) -> list[str]:
    tree = ast.parse((_VERSIONS / filename).read_text(encoding="utf-8"))
    downgrade = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "downgrade"
    )
    return [ast.unparse(stmt) for stmt in downgrade.body]


@pytest.mark.parametrize(("filename", "attr", "code"), GUARDS)
def test_downgrade_refuses_before_changing_anything(filename, attr, code):
    calls = _downgrade_calls(filename)
    guard_call = f"op.execute({attr})"
    assert guard_call in calls
    # Przed strażnikiem wolno tylko inne strażniki (0486 ma też notifications).
    before = calls[: calls.index(guard_call)]
    assert all(call.startswith("op.execute(REFUSE_") for call in before)
    guard = getattr(_module(filename), attr)
    assert f"Downgrade {code} odmawia" in guard


def test_0504_guard_covers_both_neutral_reasons():
    guard = _module("0504_job_close_reason_neutral.py").REFUSE_WITH_NEUTRAL_CLOSES
    assert "close_reason::text IN ('duplicate', 'no_match')" in guard


def test_0486_guard_checks_the_ai_usage_log():
    guard = _module("0486_approval_settlement.py").REFUSE_WITH_USAGE
    assert "ai_usage_log WHERE feature::text = 'expense_document_read'" in guard


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
