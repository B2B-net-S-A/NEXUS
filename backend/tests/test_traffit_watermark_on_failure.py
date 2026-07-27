"""Regression tests for the Traffit sync watermark-advance decision (M2-IMP-01).

The delta cutoff ``since`` is derived from the persisted ``__daily__`` watermark
(``last_synced_at``). If a run advances that watermark even though a phase failed
(raised) or reported row-level errors, the records that did not import age out of
the ~48h lookback overlap and are silently lost forever — Nexus drifts away from
Traffit with no signal.

These tests drive ``run_traffit_sync`` with a fully mocked phase plan / DB (no
network, no Postgres) and assert the watermark-advance decision directly:

- a phase raising           → ``last_synced_at`` NOT advanced (stays previous)
- a phase with row errors   → ``last_synced_at`` NOT advanced
- a clean phase             → ``last_synced_at`` advanced to the run start

In every case the scheduling gate (``last_run_finished_at``) and the health
signal (``last_status``) still advance, so the next attempt runs on the normal
schedule (no hot-retry loop) and ``/api/health`` surfaces the failure.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.tasks import traffit_sync
from app.tasks.traffit_sync import DAILY_MARKER, FULL_MARKER, run_traffit_sync

UTC = timezone.utc
_PRIOR = datetime(2026, 7, 1, 2, 0, tzinfo=UTC)


# ── Test doubles ─────────────────────────────────────────────────────────────


class _FakeProgress:
    """Minimal phase result honouring the (as_dict / errors / *_at) contract."""

    def __init__(self, *, errors: int = 0) -> None:
        self.errors = errors
        self.started_at = datetime.now(UTC)
        self.finished_at = datetime.now(UTC)

    def as_dict(self) -> dict:
        return {"processed": 1, "inserted": 1, "errors": self.errors}


class _FakeClient:
    """Async-context stand-in for TraffitClient (no HTTP)."""

    def __init__(self, *a, **k) -> None:  # noqa: D401
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _FakeSessionCM:
    """Async-context stand-in for AsyncSessionLocal()."""

    async def __aenter__(self):
        async def _noop(*a, **k):
            return None

        return SimpleNamespace(commit=_noop, rollback=_noop, execute=_noop)

    async def __aexit__(self, *a):
        return False


def _ok_phase():
    async def _factory():
        return _FakeProgress(errors=0)

    return _factory


def _raising_phase():
    async def _factory():
        raise RuntimeError("phase boom")

    return _factory


def _row_error_phase(n: int):
    async def _factory():
        return _FakeProgress(errors=n)

    return _factory


# ── Harness ──────────────────────────────────────────────────────────────────


async def _run(monkeypatch, *, mode: str, phases) -> AsyncMock:
    """Run ``run_traffit_sync`` with a mocked phase plan/DB.

    Returns the ``_upsert_state`` AsyncMock so tests can inspect what watermark
    each marker was written with.
    """
    upserts = AsyncMock()
    monkeypatch.setattr(traffit_sync, "_upsert_state", upserts)
    monkeypatch.setattr(
        traffit_sync,
        "_get_state",
        AsyncMock(return_value=SimpleNamespace(last_synced_at=_PRIOR)),
    )
    monkeypatch.setattr(
        traffit_sync, "_phase_plan", lambda importer, since, files_since: phases
    )
    monkeypatch.setattr(traffit_sync, "TraffitImporter", lambda *a, **k: object())
    monkeypatch.setattr(traffit_sync, "TraffitClient", _FakeClient)
    monkeypatch.setattr(traffit_sync, "AsyncSessionLocal", lambda: _FakeSessionCM())
    monkeypatch.setattr(
        traffit_sync.TraffitConfig, "from_env", staticmethod(lambda: object())
    )

    await run_traffit_sync(mode)
    return upserts


def _marker_call(upserts: AsyncMock, marker: str):
    """The upsert call that targets ``marker`` (positional arg[1] == marker)."""
    for c in upserts.call_args_list:
        if len(c.args) >= 2 and c.args[1] == marker:
            return c
    return None


# ── Delta mode ───────────────────────────────────────────────────────────────


async def test_delta_watermark_frozen_when_phase_raises(monkeypatch):
    upserts = await _run(
        monkeypatch, mode="delta", phases=[("candidates", _raising_phase())]
    )
    daily = _marker_call(upserts, DAILY_MARKER)
    assert daily is not None
    # Watermark NOT advanced → COALESCE keeps the prior value on the next run.
    assert daily.kwargs["last_synced_at"] is None
    # But the schedule gate + health signal still move.
    assert daily.kwargs["last_run_finished_at"] is not None
    assert daily.kwargs["last_status"] == "errors"


async def test_delta_watermark_frozen_on_row_level_errors(monkeypatch):
    upserts = await _run(
        monkeypatch, mode="delta", phases=[("candidates", _row_error_phase(3))]
    )
    daily = _marker_call(upserts, DAILY_MARKER)
    assert daily is not None
    assert daily.kwargs["last_synced_at"] is None
    assert daily.kwargs["last_status"] == "errors"


async def test_delta_watermark_advances_on_clean_run(monkeypatch):
    upserts = await _run(
        monkeypatch, mode="delta", phases=[("candidates", _ok_phase())]
    )
    daily = _marker_call(upserts, DAILY_MARKER)
    assert daily is not None
    # Clean run → watermark advances to a concrete timestamp.
    assert isinstance(daily.kwargs["last_synced_at"], datetime)
    assert daily.kwargs["last_status"] == "ok"


# ── Full reconcile mode ──────────────────────────────────────────────────────


async def test_full_watermark_frozen_on_error_for_both_markers(monkeypatch):
    upserts = await _run(
        monkeypatch, mode="full", phases=[("candidates", _raising_phase())]
    )
    full = _marker_call(upserts, FULL_MARKER)
    daily = _marker_call(upserts, DAILY_MARKER)
    assert full is not None and daily is not None
    # A failed full reconcile must not advance EITHER watermark, or the next
    # delta would skip the range the reconcile failed to cover.
    assert full.kwargs["last_synced_at"] is None
    assert daily.kwargs["last_synced_at"] is None


async def test_full_watermark_advances_on_clean_run(monkeypatch):
    upserts = await _run(monkeypatch, mode="full", phases=[("candidates", _ok_phase())])
    full = _marker_call(upserts, FULL_MARKER)
    daily = _marker_call(upserts, DAILY_MARKER)
    assert isinstance(full.kwargs["last_synced_at"], datetime)
    assert isinstance(daily.kwargs["last_synced_at"], datetime)
