"""Resume cursor for `import_candidates` + visibility for dropped /sources/ pages.

`import_candidates` is the largest feed (~49k) and the phase every later one
depends on — a Coolify restart (every push to main) threw the run away and
re-scanned from page 1 next time.

The `/sources/` half is deliberately NOT a cursor. That phase aggregates every
row into an in-memory dict and writes only at the end, so a cursor pointing at
page N would skip pages 1..N-1 whose data was never applied — the "same
mechanical pattern" would introduce data loss. What it gets instead is
visibility: pages dropped by `skip_on_5xx` used to vanish without a single
number anywhere (no error → no quarantine → watermark advanced), and are now
counted into `skipped_pages`, which the orchestrator surfaces in /sync/status.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

import app.services.traffit.importer as importer_mod
from app.services.traffit.importer import PhaseProgress, TraffitImporter

UTC = timezone.utc
_SINCE = datetime(2026, 8, 10, 2, 0, tzinfo=UTC)
_SINCE_ISO = _SINCE.isoformat()


class _Result:
    def __init__(self, rows):
        self._rows = list(rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)

    def __iter__(self):
        return iter(self._rows)

    def all(self):
        return list(self._rows)


class _FakeDB:
    def __init__(self, seeded_cursor=None):
        self.cursor = seeded_cursor
        self.cursor_writes: list[dict | None] = []

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        p = params or {}
        if "SELECT cursor_payload" in sql:
            return _Result([(self.cursor,)])
        if "INSERT INTO traffit_sync_state" in sql:
            self.cursor = json.loads(p["cp"])
            self.cursor_writes.append(self.cursor)
            return _Result([])
        if "UPDATE traffit_sync_state" in sql and "cursor_payload = NULL" in sql:
            self.cursor = None
            self.cursor_writes.append(None)
            return _Result([])
        if "traffit_sync_state" in sql:
            raise AssertionError(f"unrecognised traffit_sync_state SQL: {sql!r}")
        if "INSERT INTO candidates" in sql:
            return _Result([(1, True)])
        return _Result([])

    async def commit(self):
        pass

    async def rollback(self):
        pass


class _FakeTraffit:
    def __init__(self, pages):
        self.pages = pages
        self.start_pages: list[int] = []

    async def total_count(self, path):
        return 99999

    async def get_pages(self, path, *, page_size=100, filter_=None, start_page=1, **kw):
        self.start_pages.append(start_page)
        for page_no, items in self.pages:
            if page_no < start_page:
                continue
            yield page_no, items


def _pages(n_pages: int, per_page: int = 100):
    return [
        (i, [{"id": i * 1000 + j} for j in range(per_page)])
        for i in range(1, n_pages + 1)
    ]


def _make_importer(db, traffit, monkeypatch) -> TraffitImporter:
    imp = TraffitImporter(traffit, db, dry_run=False, batch_size=100)
    monkeypatch.setattr(imp, "build_user_id_map", AsyncMock(return_value={}))
    monkeypatch.setattr(
        imp, "_record_new_candidate_index_intent", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        importer_mod,
        "traffit_employee_to_candidate",
        lambda raw, user_map: {
            "external_id": str(raw["id"]),
            "email": None,
            "name": "A",
            "lastname": "B",
        },
    )
    return imp


@pytest.mark.asyncio
async def test_candidates_resumes_from_the_persisted_page(monkeypatch) -> None:
    db = _FakeDB(
        seeded_cursor={"delta": {"page": 4, "since": _SINCE_ISO, "page_size": 100}}
    )
    traffit = _FakeTraffit(_pages(5))
    imp = _make_importer(db, traffit, monkeypatch)

    await imp.import_candidates(since=_SINCE)

    assert traffit.start_pages == [4]  # not 1


@pytest.mark.asyncio
async def test_candidates_stale_since_window_ignores_the_cursor(monkeypatch) -> None:
    """`since` moves every night; the mode slot alone does not separate windows."""
    db = _FakeDB(
        seeded_cursor={
            "delta": {
                "page": 4,
                "since": "2026-08-09T02:00:00+00:00",
                "page_size": 100,
            }
        }
    )
    traffit = _FakeTraffit(_pages(2))
    imp = _make_importer(db, traffit, monkeypatch)

    await imp.import_candidates(since=_SINCE)

    assert traffit.start_pages == [1]


@pytest.mark.asyncio
async def test_candidates_clean_run_retires_only_its_own_slot(monkeypatch) -> None:
    full_slot = {"page": 120, "since": None, "page_size": 100}
    db = _FakeDB(
        seeded_cursor={
            "full": full_slot,
            "delta": {"page": 2, "since": _SINCE_ISO, "page_size": 100},
        }
    )
    traffit = _FakeTraffit(_pages(2))
    imp = _make_importer(db, traffit, monkeypatch)

    await imp.import_candidates(since=_SINCE)

    assert db.cursor == {"full": full_slot}


# ── /sources/ dropped pages are counted, not silent ──────────────────────────


def test_phase_progress_reports_skipped_pages() -> None:
    progress = PhaseProgress(phase="candidate_sources")
    assert progress.as_dict()["skipped_pages"] == 0

    progress.skipped_pages += 2
    assert progress.as_dict()["skipped_pages"] == 2
    # Crucially NOT an error: an unattributable error would block the watermark
    # forever on a known-flaky endpoint.
    assert progress.errors == 0
    assert progress.error_refs == set()


def test_summarize_surfaces_skipped_pages_in_sync_status() -> None:
    from app.tasks.traffit_sync import _summarize

    progress = PhaseProgress(phase="candidate_sources")
    progress.skipped_pages = 3

    assert _summarize(progress.as_dict())["skipped_pages"] == 3
