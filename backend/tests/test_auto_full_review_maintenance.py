"""Nocne utrzymanie przed przeglądami (30.09.2026): statystyki krytycznych
raz w tygodniu i poniedziałkowy skrót propozycji — raz na noc, bez blokowania."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from app.services import auto_full_review as afr
from app.services import critical_skills, proposals_digest


class _Session:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def commit(self):
        return None


@pytest.fixture
def _patched(monkeypatch):
    import app.core.database as database

    monkeypatch.setattr(database, "AsyncSessionLocal", lambda: _Session())
    stale = AsyncMock(return_value=True)
    recompute = AsyncMock(return_value={})
    digest = AsyncMock(return_value=0)
    monkeypatch.setattr(critical_skills, "stats_are_stale", stale)
    monkeypatch.setattr(critical_skills, "recompute_and_store", recompute)
    monkeypatch.setattr(proposals_digest, "send_pending_proposals_digest", digest)
    afr._maintenance_done.clear()
    yield stale, recompute, digest
    afr._maintenance_done.clear()


async def test_maintenance_runs_once_per_night(_patched):
    stale, recompute, digest = _patched
    tonight = datetime(2026, 10, 5, 23, 0, tzinfo=timezone.utc)
    await afr._nightly_maintenance(tonight, tonight)
    await afr._nightly_maintenance(tonight, tonight)
    assert recompute.await_count == 1 and digest.await_count == 1


async def test_fresh_stats_are_not_recomputed(_patched):
    stale, recompute, digest = _patched
    stale.return_value = False
    tonight = datetime(2026, 10, 6, 23, 0, tzinfo=timezone.utc)
    await afr._nightly_maintenance(tonight, tonight)
    assert recompute.await_count == 0 and digest.await_count == 1


async def test_a_failing_recompute_does_not_stop_the_digest(_patched):
    stale, recompute, digest = _patched
    recompute.side_effect = RuntimeError("boom")
    tonight = datetime(2026, 10, 7, 23, 0, tzinfo=timezone.utc)
    await afr._nightly_maintenance(tonight, tonight)
    assert digest.await_count == 1
