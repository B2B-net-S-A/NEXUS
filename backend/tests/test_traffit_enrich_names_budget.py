"""Regression: the `"? ?"` name-recovery phase could never finish, and one
broken CV froze the GLOBAL daily watermark forever.

Two independent faults, both in `enrich_missing_names`:

1. It called the backfill with no `limit` and no cursor. The selection is NOT
   self-clearing — a candidate whose CV yields no name stays `"?"` — so every
   full pass re-paid for the same `ORDER BY id` prefix (one LLM call per row)
   and never reached the tail.

2. It assigned `progress.errors = stats["errors"]` directly, bypassing
   `add_error`. That leaves `error_refs` empty, and `_blocking_errors` counts
   every unattributable error as blocking with nothing for the quarantine to
   park — so a single permanently unparseable CV froze the daily watermark for
   all 180k records and pinned `checks.traffit=degraded`, exactly the incident
   `TRAFFIT_MAX_ROW_ATTEMPTS` was introduced to end.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

import app.services.traffit.importer as importer_mod
from app.core.config import settings
from app.services.traffit.importer import TraffitImporter
from app.tasks.traffit_sync import _blocking_errors, _next_quarantine

UTC = timezone.utc
_SINCE = datetime(2026, 8, 10, 2, 0, tzinfo=UTC)


class _Result:
    def __init__(self, rows):
        self._rows = list(rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _FakeDB:
    def __init__(self, cursor=None):
        self.cursor = cursor
        self.cursor_writes: list[dict | None] = []
        self.commits = 0

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        p = params or {}
        if "SELECT cursor_payload" in sql:
            return _Result([(self.cursor,)])
        if "INSERT INTO traffit_sync_state" in sql:
            payload = json.loads(p["cp"])
            self.cursor = payload
            self.cursor_writes.append(payload)
            return _Result([])
        if "UPDATE traffit_sync_state" in sql and "cursor_payload = NULL" in sql:
            self.cursor = None
            self.cursor_writes.append(None)
            return _Result([])
        if "traffit_sync_state" in sql:
            raise AssertionError(f"unrecognised traffit_sync_state SQL: {sql!r}")
        return _Result([])

    async def commit(self):
        self.commits += 1


def _importer(db) -> TraffitImporter:
    imp = TraffitImporter.__new__(TraffitImporter)
    imp.db = db
    imp.dry_run = False
    return imp


def _stub_backfill(monkeypatch, *, stats):
    """Capture the kwargs the phase passes to the shared backfill."""
    seen: dict = {}

    async def _fake(db, **kwargs):
        seen.update(kwargs)
        return stats

    monkeypatch.setattr(
        importer_mod,
        "backfill_missing_names",
        _fake,
        raising=False,
    )
    # The phase imports the symbol inside the function body, so patch the source
    # module too — that is the binding it actually resolves.
    import app.services.cv_backfill as cv_backfill_mod

    monkeypatch.setattr(cv_backfill_mod, "backfill_missing_names", _fake)
    return seen


@pytest.mark.asyncio
async def test_full_run_is_budgeted_and_persists_cursor(monkeypatch) -> None:
    monkeypatch.setattr(settings, "TRAFFIT_SYNC_ENRICH_NAMES_LIMIT", 3)
    db = _FakeDB()
    seen = _stub_backfill(
        monkeypatch,
        stats={
            "total": 3,
            "processed": 3,
            "resolved": 2,
            "unresolved": 1,
            "errors": 0,
            "error_ids": [],
            "last_id": 77,
        },
    )

    progress = await _importer(db).enrich_missing_names(since=None)

    assert seen["limit"] == 3  # budget actually reaches the backfill
    assert seen["after_id"] is None  # first pass starts at the beginning
    # Batch filled the budget → more to sweep → cursor persisted.
    assert db.cursor == {"after_id": 77}
    assert progress.errors == 0


@pytest.mark.asyncio
async def test_full_run_resumes_from_cursor(monkeypatch) -> None:
    monkeypatch.setattr(settings, "TRAFFIT_SYNC_ENRICH_NAMES_LIMIT", 3)
    db = _FakeDB(cursor={"after_id": 77})
    seen = _stub_backfill(
        monkeypatch,
        stats={
            "total": 3,
            "processed": 3,
            "resolved": 3,
            "unresolved": 0,
            "errors": 0,
            "error_ids": [],
            "last_id": 120,
        },
    )

    await _importer(db).enrich_missing_names(since=None)

    assert seen["after_id"] == 77  # continues past the last swept row
    assert db.cursor == {"after_id": 120}


@pytest.mark.asyncio
async def test_short_batch_retires_the_cursor(monkeypatch) -> None:
    monkeypatch.setattr(settings, "TRAFFIT_SYNC_ENRICH_NAMES_LIMIT", 10)
    db = _FakeDB(cursor={"after_id": 500})
    _stub_backfill(
        monkeypatch,
        stats={
            "total": 2,
            "processed": 2,
            "resolved": 2,
            "unresolved": 0,
            "errors": 0,
            "error_ids": [],
            "last_id": 502,
        },
    )

    await _importer(db).enrich_missing_names(since=None)

    # Swept to the end → next full run starts a fresh pass instead of parking.
    assert db.cursor is None


@pytest.mark.asyncio
async def test_delta_is_unbudgeted_and_never_touches_the_cursor(monkeypatch) -> None:
    db = _FakeDB(cursor={"after_id": 42})
    seen = _stub_backfill(
        monkeypatch,
        stats={
            "total": 1,
            "processed": 1,
            "resolved": 1,
            "unresolved": 0,
            "errors": 0,
            "error_ids": [],
            "last_id": 9,
        },
    )

    await _importer(db).enrich_missing_names(since=_SINCE)

    assert seen["limit"] is None  # delta's `since` scope is its own bound
    assert seen["after_id"] is None
    assert db.cursor_writes == []
    assert db.cursor == {"after_id": 42}


@pytest.mark.asyncio
async def test_row_failures_are_attributable_so_quarantine_can_park_them(
    monkeypatch,
) -> None:
    """The core fix: a permanently broken CV must stop freezing the watermark
    for every other record once it has been retried enough times."""
    monkeypatch.setattr(settings, "TRAFFIT_SYNC_ENRICH_NAMES_LIMIT", 10)
    db = _FakeDB()
    _stub_backfill(
        monkeypatch,
        stats={
            "total": 3,
            "processed": 3,
            "resolved": 1,
            "unresolved": 0,
            "errors": 2,
            "error_ids": [101, 202],
            "last_id": 202,
        },
    )

    progress = await _importer(db).enrich_missing_names(since=None)

    assert progress.errors == 2
    # Attributed — this is what the old code lacked entirely.
    assert progress.error_refs == {"candidate_name:101", "candidate_name:202"}
    assert progress.attributed_errors == 2

    pd = progress.as_dict()
    refs = pd["error_refs"]

    # Run 1: still retrying, so they legitimately hold the watermark.
    q1 = _next_quarantine(None, refs)
    assert _blocking_errors(progress.errors, refs, q1, 3, attributed_errors=2) == 2

    # After enough consecutive failures the rows are parked and STOP blocking —
    # under the old unattributable accounting this could never happen.
    q = q1
    for _ in range(2):
        q = _next_quarantine({"quarantine": q}.get("quarantine"), refs)
    assert _blocking_errors(progress.errors, refs, q, 3, attributed_errors=2) == 0


@pytest.mark.asyncio
async def test_unlisted_errors_still_counted(monkeypatch) -> None:
    """If the backfill ever reports more failures than ids, the count stays
    honest — an under-reported error must not vanish."""
    monkeypatch.setattr(settings, "TRAFFIT_SYNC_ENRICH_NAMES_LIMIT", 10)
    db = _FakeDB()
    _stub_backfill(
        monkeypatch,
        stats={
            "total": 5,
            "processed": 5,
            "resolved": 0,
            "unresolved": 0,
            "errors": 4,
            "error_ids": [7],
            "last_id": 7,
        },
    )

    progress = await _importer(db).enrich_missing_names(since=None)

    assert progress.errors == 4
    assert progress.error_refs == {"candidate_name:7"}
