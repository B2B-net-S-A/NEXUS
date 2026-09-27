"""Runda 8 (R8-N15-1/2): blok odmowy downgrade wykonany na Postgresie.

Blok DO sprawdzamy w transakcji wycofywanej na końcu — nie wolno zostawić
w bazie CI wiersza, który zablokowałby inny test.
"""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.database import AsyncSessionLocal

_VERSIONS = Path(__file__).resolve().parents[1] / "alembic" / "versions"

pytestmark = pytest.mark.asyncio


def _module(filename: str):
    spec = importlib.util.spec_from_file_location(filename, _VERSIONS / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


async def test_0388_guard_refuses_with_tombstones():
    guard = _module("0388_purged_candidates.py").REFUSE_WITH_TOMBSTONES
    async with AsyncSessionLocal() as db:
        try:
            await db.execute(
                text(
                    "INSERT INTO purged_candidates (external_source, external_id_hash) "
                    "VALUES ('traffit', :h)"
                ),
                {"h": uuid.uuid4().hex + uuid.uuid4().hex},
            )
            with pytest.raises(DBAPIError, match="0388"):
                async with db.begin_nested():
                    await db.execute(text(guard))
        finally:
            await db.rollback()


@pytest.mark.parametrize(
    ("filename", "attr", "code"),
    [
        (
            "0383_legacy_interview_questions.py",
            "REFUSE_WITH_NEW_ENUM_ROWS",
            "0383",
        ),
        (
            "0381_job_boards_jjit_rocketjobs.py",
            "REFUSE_WITH_ROCKETJOBS_POSTINGS",
            "0381",
        ),
    ],
)
async def test_enum_guards_run_on_postgres(filename, attr, code):
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
