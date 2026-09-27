"""Runda 10 (R10-N8-1): jeden nieudany check raportu nie psuje pozostałych.

Wszystkie checki inventory jadą po jednej sesji. Nieudany SELECT przerywa
transakcję w Postgresie; bez `rollback()` każdy kolejny check dostaje
`InFailedSQLTransaction`. Atrapa sesji odwzorowuje to zachowanie.
"""

from __future__ import annotations

import pytest

from app.api import admin_candidate_pii_orphans as pii
from app.api import admin_engagement_inventory as engagement
from app.api import admin_pipeline_inventory as pipeline


class _Mappings:
    def all(self):
        return [{"total_count": 0}]

    def one(self):
        return {"x": 1}


class _Result:
    def mappings(self):
        return _Mappings()

    def scalar(self):
        return 0


class _AbortingSession:
    """Pierwsze zapytanie pada; potem sesja działa dopiero po rollbacku."""

    def __init__(self) -> None:
        self.calls = 0
        self.aborted = False
        self.rollbacks = 0

    async def execute(self, *_args, **_kwargs):
        self.calls += 1
        if self.calls == 1:
            self.aborted = True
            raise RuntimeError("undefined table")
        if self.aborted:
            raise RuntimeError("InFailedSQLTransactionError")
        return _Result()

    async def rollback(self):
        self.rollbacks += 1
        self.aborted = False


@pytest.mark.asyncio
@pytest.mark.parametrize("module", [engagement, pipeline])
async def test_failed_check_does_not_poison_following_checks(module):
    db = _AbortingSession()
    first = await module._run_check(db, "a", "high", "d", "SELECT 1")
    second = await module._run_check(db, "b", "high", "d", "SELECT 1")
    assert first["count"] is None
    assert second["count"] == 0
    assert "error" not in second


@pytest.mark.asyncio
async def test_failed_pii_check_does_not_poison_following_checks():
    db = _AbortingSession()
    with pytest.raises(RuntimeError):
        await pii._run_check(db, "SELECT 1")
    assert await pii._run_check(db, "SELECT 1") == 0


def test_schema_drift_reads_the_migration_graph_once(monkeypatch):
    """Runda 10 (R10-N8-10): graf migracji z pamięci, nie z dysku przy każdym GET."""
    from alembic.script import ScriptDirectory

    from app.api import admin_schema_drift as drift
    from app.services import migration_health

    migration_health._load_code_revisions.cache_clear()
    monkeypatch.setattr(migration_health, "_REVISIONS_UNAVAILABLE", [])
    real = ScriptDirectory.from_config.__func__
    calls = 0

    def counting(cls, cfg):
        nonlocal calls
        calls += 1
        return real(cls, cfg)

    monkeypatch.setattr(ScriptDirectory, "from_config", classmethod(counting))
    first = drift._alembic_state_from_code()
    second = drift._alembic_state_from_code()
    migration_health._load_code_revisions.cache_clear()

    assert "code_error" not in first, first
    assert first == second
    assert first["revision_count"] > 100
    assert calls == 1
