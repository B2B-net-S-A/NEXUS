"""Resumability regression for `candidates_cv`.

The phase swept unbounded with no cursor. Its selection is only PARTLY
self-clearing: a successful download fills `cv_storage_key` and drops out, but a
candidate with no CV in Traffit at all is counted `skipped` and stays a target
forever. So every full pass re-paid for the same `ORDER BY id` prefix — one
/files call each — and never reached the tail, and a Coolify restart mid-sweep
lost the position entirely.

The sibling fault in `candidate_activities` (delta wiping full's resume cursor)
is covered end-to-end in `test_traffit_activities_resume.py`, against the real
phase rather than a replayed copy of its condition.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.services.traffit.importer import TraffitImporter

UTC = timezone.utc
_SINCE = datetime(2026, 8, 10, 2, 0, tzinfo=UTC)


class _Row(SimpleNamespace):
    pass


class _Result:
    def __init__(self, rows):
        self._rows = list(rows)

    def __iter__(self):
        return iter(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _CursorDB:
    """Minimal DB that models only the cursor row."""

    def __init__(self, cursor=None, candidates=None):
        self.cursor = cursor
        self.cursor_writes: list[dict | None] = []
        self.candidates = candidates or []
        self.commits = 0
        self.last_scan_params: dict = {}

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
        if "FROM candidates" in sql:
            self.last_scan_params = dict(p)
            rows = [_Row(id=cid, external_id=ext) for cid, ext in self.candidates]
            if "after_id" in p:
                rows = [r for r in rows if r.id > p["after_id"]]
            if "limit" in p:
                rows = rows[: p["limit"]]
            return _Result(rows)
        return _Result([])

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        pass


class _FakeResp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class _NoFilesTraffit:
    """Every candidate lists zero usable files — the `skipped` path that keeps
    them in the target set forever."""

    def __init__(self):
        self.listed: list[str] = []
        self._http = object()

    async def _get_raw(self, path, page=1, page_size=50):
        self.listed.append(path.split("/")[2])
        return _FakeResp(payload=[])


def _cv_importer(db, traffit) -> TraffitImporter:
    imp = TraffitImporter.__new__(TraffitImporter)
    imp.db = db
    imp.traffit = traffit
    imp.dry_run = False
    return imp


@pytest.mark.asyncio
async def test_cv_full_scan_is_budgeted_and_persists_cursor(monkeypatch) -> None:
    monkeypatch.setattr(settings, "TRAFFIT_SYNC_FULL_FILES_LIMIT", 2)
    db = _CursorDB(candidates=[(1, "100"), (2, "200"), (3, "300")])
    traffit = _NoFilesTraffit()

    await _cv_importer(db, traffit).import_candidates_cv(since=None)

    assert traffit.listed == ["100", "200"]  # budget respected
    assert db.cursor == {"after_id": 2}


@pytest.mark.asyncio
async def test_cv_full_scan_resumes_and_retires_cursor(monkeypatch) -> None:
    monkeypatch.setattr(settings, "TRAFFIT_SYNC_FULL_FILES_LIMIT", 10)
    db = _CursorDB(cursor={"after_id": 2}, candidates=[(1, "100"), (3, "300")])
    traffit = _NoFilesTraffit()

    await _cv_importer(db, traffit).import_candidates_cv(since=None)

    assert traffit.listed == ["300"]  # resumed past the swept prefix
    assert db.cursor is None  # short batch → pass complete


@pytest.mark.asyncio
async def test_cv_delta_ignores_the_cursor(monkeypatch) -> None:
    db = _CursorDB(cursor={"after_id": 99}, candidates=[(1, "100")])
    traffit = _NoFilesTraffit()

    await _cv_importer(db, traffit).import_candidates_cv(since=_SINCE)

    assert traffit.listed == ["100"]
    assert "after_id" not in db.last_scan_params
    assert db.cursor_writes == []
    assert db.cursor == {"after_id": 99}
