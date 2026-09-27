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
