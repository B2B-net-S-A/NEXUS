"""Regression: the full reconcile must revisit candidates that ALREADY have
files, or missing CVs are unrecoverable.

Until 2026-08-10 the full-mode target query gated on
``HAVING count(cd.id) = 0``, so owning at least one document was a permanent
exemption from the weekly sweep. A candidate whose migration pulled 2 of 5 files
(the rest lost to a /content non-200 or a timeout) was never looked at again:
delta only visits candidates Traffit itself changed, and historical rows never
change. Net effect on prod — Nexus holds fewer CVs than Traffit and the daily
sync, however healthy, can never close the gap.

The sweep now visits everyone, budgeted by ``TRAFFIT_SYNC_FULL_FILES_LIMIT`` and
resumable through an ``after_id`` cursor on the phase's own
``traffit_sync_state`` row, so it survives the Coolify redeploy that would
otherwise kill a ~2.7 h scan and restart it from the first candidate forever.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import app.services.object_storage as object_storage_mod
from app.core.config import settings
from app.services.traffit.importer import TraffitImporter

UTC = timezone.utc
_SINCE = datetime(2026, 8, 9, 2, 0, tzinfo=UTC)


class _Row(SimpleNamespace):
    pass


class _Result:
    def __init__(self, rows):
        self._rows = list(rows)

    def __iter__(self):
        return iter(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _Nested:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeDB:
    """Routes SQL by substring: target scan, existing-doc preload, cursor
    read/write/clear and the document upsert."""

    def __init__(self, candidates, existing_docs=None, cursor=None):
        # candidates: list[(candidate_id, traffit_external_id)]
        self.candidates = candidates
        # existing_docs: {candidate_id: {external_id, ...}}
        self.existing_docs = existing_docs or {}
        self.cursor = cursor
        self.cursor_writes: list[dict | None] = []
        self.upserted: list[str] = []  # external_id of each document upsert
        self.scan_sql: list[str] = []  # target-scan statements, for shape assertions
        self.commits = 0
        self.rollbacks = 0

    def begin_nested(self):
        return _Nested()

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

        if "FROM candidates c" in sql:
            self.scan_sql.append(sql)
            rows = [_Row(id=cid, external_id=ext) for cid, ext in self.candidates]
            if "after_id" in p:  # full sweep — honour cursor + budget
                rows = [r for r in rows if r.id > p["after_id"]][: p["limit"]]
            return _Result(rows)

        if "FROM candidate_documents" in sql:
            rows = [
                _Row(candidate_id=cid, external_id=ext)
                for cid, exts in self.existing_docs.items()
                for ext in exts
            ]
            return _Result(rows)

        if "INSERT INTO candidate_documents" in sql:
            self.upserted.append(p["external_id"])
            return _Result([])

        return _Result([])  # demote UPDATE and anything else

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


class _FakeResp:
    def __init__(self, status_code=200, payload=None, content=b""):
        self.status_code = status_code
        self._payload = payload
        self.content = content
        self.headers = {"content-type": "application/pdf"}

    def json(self):
        return self._payload


class _FakeHttp:
    async def get(self, url, headers=None):
        return _FakeResp(content=b"%PDF-1.4 fake")


class _FakeTraffit:
    """Serves /employees/<emp>/files listings and records which were requested."""

    def __init__(self, files_by_emp):
        self.files_by_emp = files_by_emp
        self.listed: list[str] = []
        self._http = _FakeHttp()
        self.config = SimpleNamespace(api_base="https://traffit.test/api")

    async def _get_raw(self, path, page=1, page_size=50):
        emp = path.split("/")[2]
        self.listed.append(emp)
        return _FakeResp(payload=self.files_by_emp.get(emp, []))

    async def _ensure_token(self):
        return "token"

    async def _throttle(self):
        return None


def _files(*file_ids):
    return [{"id": fid, "name": f"cv-{fid}.pdf"} for fid in file_ids]


@pytest.fixture(autouse=True)
def _no_object_storage(monkeypatch):
    monkeypatch.setattr(
        object_storage_mod,
        "upload_cv",
        lambda content=None, filename=None, content_type=None: "s3://fake-key",
    )


def _importer(db, traffit) -> TraffitImporter:
    return TraffitImporter(traffit, db, dry_run=False, batch_size=100)


@pytest.mark.asyncio
async def test_full_sweep_visits_candidates_that_already_have_files() -> None:
    """The regression itself: candidate 2 owns one document, so the old
    ``HAVING count = 0`` gate skipped it entirely and its second file could
    never arrive. The sweep must list it and fetch only the missing file."""
    db = _FakeDB(
        candidates=[(1, "100"), (2, "200")],
        existing_docs={2: {"200-1"}},
    )
    traffit = _FakeTraffit({"100": _files(1), "200": _files(1, 2)})

    progress = await _importer(db, traffit).import_candidate_files(since=None)

    # The scan itself must not exempt anyone by document count. Asserted on the
    # SQL shape because that IS the regression: a fake DB cannot reproduce
    # `HAVING count(cd.id) = 0`, so behaviour alone would look identical here
    # while prod quietly skipped every candidate that owns a file.
    assert len(db.scan_sql) == 1
    assert "HAVING" not in db.scan_sql[0].upper()
    assert "candidate_documents" not in db.scan_sql[0]
    # Both candidates listed — the exempted one is no longer invisible.
    assert traffit.listed == ["100", "200"]
    # Only genuinely missing files are downloaded; "200-1" is already local.
    assert db.upserted == ["100-1", "200-2"]
    assert progress.inserted == 2
    assert progress.skipped == 1
    assert progress.errors == 0


@pytest.mark.asyncio
async def test_budget_stops_the_scan_and_persists_cursor(monkeypatch) -> None:
    monkeypatch.setattr(settings, "TRAFFIT_SYNC_FULL_FILES_LIMIT", 2)
    db = _FakeDB(candidates=[(1, "100"), (2, "200"), (3, "300")])
    traffit = _FakeTraffit({"100": _files(1), "200": _files(1), "300": _files(1)})

    await _importer(db, traffit).import_candidate_files(since=None)

    # Budget honoured: the third candidate is left for the next run…
    assert traffit.listed == ["100", "200"]
    # …and the cursor says exactly where to pick up.
    assert db.cursor == {"after_id": 2}


@pytest.mark.asyncio
async def test_resume_continues_from_cursor_then_clears_on_completion(
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "TRAFFIT_SYNC_FULL_FILES_LIMIT", 10)
    db = _FakeDB(
        candidates=[(1, "100"), (2, "200"), (3, "300")],
        cursor={"after_id": 2},
    )
    traffit = _FakeTraffit({"300": _files(7)})

    await _importer(db, traffit).import_candidate_files(since=None)

    # Resumed past the first two, no redundant re-listing.
    assert traffit.listed == ["300"]
    assert db.upserted == ["300-7"]
    # Short batch = swept to the end → cursor retired so the next full run
    # starts a fresh pass instead of parking at the tail forever.
    assert db.cursor is None


@pytest.mark.asyncio
async def test_cursor_past_the_last_candidate_is_cleared(monkeypatch) -> None:
    """Empty batch must retire the cursor too — otherwise the phase would be a
    permanent no-op, which is the bug this whole change exists to remove."""
    monkeypatch.setattr(settings, "TRAFFIT_SYNC_FULL_FILES_LIMIT", 10)
    db = _FakeDB(candidates=[(1, "100")], cursor={"after_id": 999})
    traffit = _FakeTraffit({})

    progress = await _importer(db, traffit).import_candidate_files(since=None)

    assert traffit.listed == []
    assert progress.total_source == 0
    assert db.cursor is None


@pytest.mark.asyncio
async def test_cursor_is_staged_mid_run_not_only_at_the_end(monkeypatch) -> None:
    """A run killed by a Coolify redeploy must keep the progress it committed:
    the cursor is written alongside each periodic commit (every 50 candidates),
    not just in the closing transaction."""
    monkeypatch.setattr(settings, "TRAFFIT_SYNC_FULL_FILES_LIMIT", 500)
    cands = [(i, str(i)) for i in range(1, 61)]
    db = _FakeDB(candidates=cands)
    traffit = _FakeTraffit({str(i): _files(1) for i in range(1, 61)})

    await _importer(db, traffit).import_candidate_files(since=None)

    # commit_every=50 → the 50th candidate stages its position before committing.
    assert {"after_id": 50} in db.cursor_writes
    # Whole base swept (60 < 500) → cursor retired at the end.
    assert db.cursor is None


@pytest.mark.asyncio
async def test_delta_mode_leaves_the_sweep_cursor_untouched() -> None:
    """Delta is scoped to candidates Traffit just changed; it must not read or
    move the full sweep's cursor, or a redeploy-driven delta would fast-forward
    the reconcile past candidates it never looked at."""
    db = _FakeDB(candidates=[(1, "100")], cursor={"after_id": 42})
    traffit = _FakeTraffit({"100": _files(1)})

    await _importer(db, traffit).import_candidate_files(since=_SINCE)

    assert db.upserted == ["100-1"]
    assert db.cursor_writes == []
    assert db.cursor == {"after_id": 42}
