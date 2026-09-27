"""Runda 7 (R7-N10-1): KPI „na dziś” liczą kamienie milowe jednym CTE na minutę.

Do 26.09 każda z trzech metryk (weryfikacje, CV wysłane, placementy) puszczała
osobne pełne `VERIFIER_ANCHORED_CTE` przy każdym wejściu na widżet i dla każdej
osoby w przebiegu coacha.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core import cache as cache_module
from app.models.user import User, UserRole
from app.services import kpi_engine


def _user(user_id: int) -> User:
    return User(
        id=user_id,
        email=f"kpi-{user_id}@example.com",
        name=f"Osoba {user_id}",
        role=UserRole.recruiter,
        roles=[UserRole.recruiter.value],
        is_active=True,
        profile_completed=True,
    )


@pytest.fixture(autouse=True)
def _clean_cache():
    cache_module._cache.clear()
    yield
    cache_module._cache.clear()


@pytest.mark.asyncio
async def test_two_users_share_one_milestone_query(monkeypatch) -> None:
    async def _targets(_db, users, ids):
        return {user.id: {kpi_id: 5 for kpi_id in ids} for user in users}

    monkeypatch.setattr(kpi_engine, "resolve_kpi_targets_bulk", _targets)
    monkeypatch.setattr(
        kpi_engine, "kpi_available", lambda k: k.metric.value != "completed_calls"
    )
    now = datetime(2026, 9, 23, 12, 0, tzinfo=kpi_engine.WARSAW)
    windows = {
        k.period
        for k in kpi_engine.KPI_CATALOG
        if k.in_coach and k.metric in kpi_engine._MILESTONE_STAGE
    }
    ordered = sorted(windows, key=lambda p: p.value)

    def _row(uid: int, stage: str, counts: dict[str, int]) -> dict:
        row = {"credit_user": uid, "stage": stage}
        for index, period in enumerate(ordered):
            row[f"p{index}"] = counts.get(period.value, 0)
        return row

    snapshot = MagicMock()
    snapshot.mappings.return_value.all.return_value = [
        _row(11, "verified", {"day": 3, "week": 3, "month": 3}),
        _row(12, "verified", {"day": 1, "week": 1, "month": 1}),
        _row(12, "hired", {"month": 2}),
    ]
    db = AsyncMock()
    db.execute.return_value = snapshot
    db.scalar.return_value = 0

    first = await kpi_engine.evaluate_user_kpis(db, user=_user(11), now=now)
    second = await kpi_engine.evaluate_user_kpis(db, user=_user(12), now=now)

    assert db.execute.await_count == 1
    sql = str(db.execute.await_args.args[0])
    assert "credit_user = :uid" not in sql
    by_first = {r.kpi_id: r.current for r in first}
    by_second = {r.kpi_id: r.current for r in second}
    assert by_first["daily_first_verifications"] == 3
    assert by_second["daily_first_verifications"] == 1
    assert by_second["monthly_placements"] == 2
    assert by_first["monthly_placements"] == 0


# ── Runda 9 (R9-N6-1): klucz bez „teraz” z mikrosekundami ─────────────────


def _patch_engine(monkeypatch) -> None:
    async def _targets(_db, users, ids):
        return {user.id: {kpi_id: 5 for kpi_id in ids} for user in users}

    monkeypatch.setattr(kpi_engine, "resolve_kpi_targets_bulk", _targets)
    monkeypatch.setattr(
        kpi_engine, "kpi_available", lambda k: k.metric.value != "completed_calls"
    )


def _empty_db() -> AsyncMock:
    snapshot = MagicMock()
    snapshot.mappings.return_value.all.return_value = []
    db = AsyncMock()
    db.execute.return_value = snapshot
    db.scalar.return_value = 0
    return db


@pytest.mark.asyncio
async def test_live_calls_without_now_share_one_query(monkeypatch) -> None:
    _patch_engine(monkeypatch)
    db = _empty_db()

    await kpi_engine.evaluate_user_kpis(db, user=_user(11))
    await kpi_engine.evaluate_user_kpis(db, user=_user(12))

    assert db.execute.await_count == 1


@pytest.mark.asyncio
async def test_cache_keys_do_not_grow_with_each_call(monkeypatch) -> None:
    from datetime import timedelta

    _patch_engine(monkeypatch)
    db = _empty_db()
    base = datetime(2026, 9, 23, 12, 0, 0, 1, tzinfo=kpi_engine.WARSAW)

    for offset in range(30):
        now = base + timedelta(seconds=offset, microseconds=offset * 37)
        await kpi_engine.evaluate_user_kpis(db, user=_user(11), now=now)
    assert db.execute.await_count == 1

    # Nowy dzień i „teraz” spoza TTL — przeliczenie, ale nadal jeden wpis.
    for later in (
        base + timedelta(minutes=5),
        base + timedelta(days=1),
        base - timedelta(days=3),
    ):
        await kpi_engine.evaluate_user_kpis(db, user=_user(11), now=later)
    milestone_keys = [k for k in cache_module._cache if k.startswith("kpi:milestones:")]
    assert len(milestone_keys) == 1
    assert db.execute.await_count == 4
