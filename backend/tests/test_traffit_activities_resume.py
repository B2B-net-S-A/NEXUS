"""Stage 3 regression: `candidate_activities` resumes from a persisted page
cursor instead of restarting at page 1 after an interruption.

A large catch-up is slow; a Coolify deploy restart kills the run mid-stream.
Without a cursor it re-scans the whole window every time and never advances the
watermark → `checks.traffit=degraded` lingers. The phase now persists the last
committed page on its own `traffit_sync_state.cursor_payload` and resumes there.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import httpx
import pytest

import app.services.traffit.importer as importer_mod
from app.services.traffit.importer import PhaseProgress, TraffitImporter

UTC = timezone.utc
_SINCE = datetime(2026, 7, 29, 2, 0, tzinfo=UTC)
_SINCE_ISO = _SINCE.isoformat()


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _FakeDB:
    """Routes SQL by substring; models the cursor read/write/clear + activities
    upsert. `cursor` is the current stored value; `written_cursor` is the last
    value the phase persisted this run."""

    def __init__(self, seeded_cursor=None, *, fail_activity_at=None):
        self.cursor = seeded_cursor  # dict | None — what a SELECT returns
        self.written_cursor = seeded_cursor
        self.commits = 0
        self.rollbacks = 0
        self._activity_calls = 0
        self._fail_activity_at = fail_activity_at

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        p = params or {}
        if "SELECT cursor_payload" in sql:
            return _Result([(self.cursor,)])
        if "INSERT INTO traffit_sync_state" in sql:  # cursor UPSERT
            self.written_cursor = json.loads(p["cp"])
            self.cursor = self.written_cursor
            return _Result([])
        if "UPDATE traffit_sync_state" in sql and "cursor_payload = NULL" in sql:
            self.written_cursor = None
            self.cursor = None
            return _Result([])
        if "INSERT INTO activities" in sql:
            self._activity_calls += 1
            if (
                self._fail_activity_at
                and self._activity_calls == self._fail_activity_at
            ):
                raise RuntimeError("simulated row upsert failure")
            return _Result([(1, True)])
        return _Result([])

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


class _FakeTraffit:
    """`get_pages` honours `start_page` (skips earlier pages) and can raise a
    ReadTimeout before a given page to simulate a mid-stream interruption."""

    def __init__(self, pages, *, raise_at_page=None):
        self.pages = pages  # list[(page_no, items_list)]
        self.raise_at_page = raise_at_page
        self.start_pages: list[int] = []

    async def total_count(self, path):
        return 99999

    async def get_pages(self, path, *, page_size=100, filter_=None, start_page=1, **kw):
        self.start_pages.append(start_page)
        for page_no, items in self.pages:
            if page_no < start_page:
                continue
            if self.raise_at_page is not None and page_no >= self.raise_at_page:
                raise httpx.ReadTimeout("simulated interrupt")
            yield page_no, items


def _pages(n_pages: int, per_page: int = 100, *, last_short: bool = True):
    pages = []
    for i in range(1, n_pages + 1):
        size = per_page if not (last_short and i == n_pages) else per_page // 2
        pages.append((i, [{"id": i * 1000 + j} for j in range(size)]))
    return pages


def _make_importer(db, traffit, monkeypatch) -> TraffitImporter:
    imp = TraffitImporter(traffit, db, dry_run=False, batch_size=100)
    monkeypatch.setattr(
        imp, "_build_candidate_external_id_map", AsyncMock(return_value={})
    )
    monkeypatch.setattr(imp, "build_user_id_map", AsyncMock(return_value={}))
    monkeypatch.setattr(imp, "promote_notes", AsyncMock(return_value=0))
    monkeypatch.setattr(
        importer_mod,
        "traffit_activity_to_activity",
        lambda raw, c, u: {
            "external_id": str(raw["id"]),
            "entity_type": "candidate",
            "entity_id": 1,
            "action": "note",
            "details": {},
            "user_id": None,
        },
    )
    monkeypatch.setattr(
        importer_mod,
        "backfill_rejection_notes_from_activities",
        AsyncMock(return_value=0),
    )
    monkeypatch.setattr(
        importer_mod,
        "backfill_rejection_descriptions_from_activities",
        AsyncMock(return_value=0),
    )
    return imp


@pytest.mark.asyncio
async def test_run1_interrupt_persists_page_cursor(monkeypatch) -> None:
    # 6 uniform pages of 100; interrupt before page 6. Commit fires at 500 rows
    # (page 5) → cursor persisted at page 5; then the ReadTimeout freezes.
    db = _FakeDB()
    traffit = _FakeTraffit(_pages(6, last_short=False), raise_at_page=6)
    imp = _make_importer(db, traffit, monkeypatch)

    progress = await imp.import_candidate_activities(since=_SINCE)

    assert isinstance(progress, PhaseProgress)
    # Stage-2 freeze preserved: unattributable pagination error.
    assert progress.errors >= 1
    assert progress.error_refs == set()
    # Cursor persisted at the last committed page, keyed to this run's filter.
    assert db.written_cursor == {"page": 5, "since": _SINCE_ISO, "page_size": 100}


@pytest.mark.asyncio
async def test_run2_resumes_from_cursor_then_clears(monkeypatch) -> None:
    seeded = {"page": 5, "since": _SINCE_ISO, "page_size": 100}
    db = _FakeDB(seeded_cursor=seeded)
    # Remaining pages 5..7 (7 is short → last). No interrupt → clean completion.
    traffit = _FakeTraffit(_pages(7), raise_at_page=None)
    imp = _make_importer(db, traffit, monkeypatch)

    progress = await imp.import_candidate_activities(since=_SINCE)

    # Resumed at the cursor's page (inclusive), not page 1.
    assert traffit.start_pages == [5]
    # Only pages >= 5 were processed (5:100, 6:100, 7:50) = 250 rows.
    assert progress.processed == 250
    # Full pass → cursor cleared.
    assert db.cursor is None
    assert progress.error_refs == set()


@pytest.mark.asyncio
async def test_cursor_invalidated_on_since_mismatch(monkeypatch) -> None:
    seeded = {"page": 9, "since": "1999-01-01T00:00:00+00:00", "page_size": 100}
    db = _FakeDB(seeded_cursor=seeded)
    traffit = _FakeTraffit(_pages(2), raise_at_page=None)
    imp = _make_importer(db, traffit, monkeypatch)

    await imp.import_candidate_activities(since=_SINCE)

    # Mismatched `since` → cursor ignored → fresh scan from page 1.
    assert traffit.start_pages == [1]


@pytest.mark.asyncio
async def test_cursor_invalidated_on_page_size_mismatch(monkeypatch) -> None:
    seeded = {"page": 9, "since": _SINCE_ISO, "page_size": 50}
    db = _FakeDB(seeded_cursor=seeded)
    traffit = _FakeTraffit(_pages(2), raise_at_page=None)
    imp = _make_importer(db, traffit, monkeypatch)

    await imp.import_candidate_activities(since=_SINCE)

    assert traffit.start_pages == [1]


@pytest.mark.asyncio
async def test_full_scan_since_none_ignores_delta_cursor(monkeypatch) -> None:
    # A delta cursor (since="…") must not be reused by a full run (since=None).
    seeded = {"page": 9, "since": _SINCE_ISO, "page_size": 100}
    db = _FakeDB(seeded_cursor=seeded)
    traffit = _FakeTraffit(_pages(2), raise_at_page=None)
    imp = _make_importer(db, traffit, monkeypatch)

    await imp.import_candidate_activities(since=None)  # must not crash

    assert traffit.start_pages == [1]
