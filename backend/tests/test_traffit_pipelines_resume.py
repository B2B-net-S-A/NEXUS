"""Resumability regression for `import_pipelines`.

This is the second-largest Traffit feed (~166k stage moves) and it sits 12th of
14 in the phase plan, so it is the phase most likely to be cut short. Until now
it paginated without any resume cursor: a Coolify restart — which happens on
every push to main — threw the whole run away and started again from page 1 the
following week. With deploys more frequent than the weekly full reconcile, the
tail of this feed could never be reached, and the tail is candidate stages, i.e.
the recruitment history itself.

Slots are per mode for the same reason as `candidate_activities`: delta page
numbers are filtered by `since` and full's are not, so a shared slot lets the
nightly delta overwrite and then clear the full sweep's parked position.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import httpx
import pytest

import app.services.traffit.importer as importer_mod
from app.services.traffit.importer import TraffitImporter, WithdrawnReasonFallback

UTC = timezone.utc
_SINCE = datetime(2026, 8, 10, 2, 0, tzinfo=UTC)
_SINCE_ISO = _SINCE.isoformat()


class _Result:
    def __init__(self, rows):
        self._rows = list(rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None


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
        return _Result([])

    async def commit(self):
        pass

    async def rollback(self):
        pass


class _FakeTraffit:
    def __init__(self, pages, *, raise_at_page=None):
        self.pages = pages
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


def _pages(n_pages: int, per_page: int = 100):
    return [
        (i, [{"id": i * 1000 + j} for j in range(per_page)])
        for i in range(1, n_pages + 1)
    ]


def _make_importer(db, traffit, monkeypatch) -> TraffitImporter:
    imp = TraffitImporter(traffit, db, dry_run=False, batch_size=100)
    monkeypatch.setattr(
        imp, "_build_candidate_external_id_map", AsyncMock(return_value={})
    )
    monkeypatch.setattr(imp, "_build_job_external_id_map", AsyncMock(return_value={}))
    monkeypatch.setattr(
        imp, "_build_stage_def_lookup", AsyncMock(return_value=({}, {}))
    )
    monkeypatch.setattr(imp, "build_user_id_map", AsyncMock(return_value={}))
    monkeypatch.setattr(
        imp,
        "_build_withdrawn_fallback_reason_map",
        AsyncMock(return_value=WithdrawnReasonFallback()),
    )
    monkeypatch.setattr(imp, "_upsert_stage_row", AsyncMock(return_value=True))
    # Batch durability is `_flush_stage_batch`'s job and is covered elsewhere;
    # here it only has to not commit, so the cursor writes stay observable.
    monkeypatch.setattr(imp, "_flush_stage_batch", AsyncMock())
    monkeypatch.setattr(
        importer_mod,
        "traffit_recruitment_history_to_stage",
        lambda raw, *a: {
            "external_id": str(raw["id"]),
            "candidate_id": 1,
            "job_id": 2,
            "stage_def_id": 3,
            "stage_legacy_enum": "applied",  # not `withdrawn` → no reason needed
        },
    )
    return imp


@pytest.mark.asyncio
async def test_interrupt_persists_the_last_flushed_page(monkeypatch) -> None:
    db = _FakeDB()
    # Pages 1 and 2 each fill a 100-row batch → two flushes; page 3 interrupts.
    traffit = _FakeTraffit(_pages(3), raise_at_page=3)
    imp = _make_importer(db, traffit, monkeypatch)

    # The phase does not swallow transport errors — the orchestrator catches
    # them, stamps the phase `error` and freezes the watermark.
    with pytest.raises(httpx.ReadTimeout):
        await imp.import_pipelines(since=_SINCE)

    assert db.cursor == {"delta": {"page": 2, "since": _SINCE_ISO, "page_size": 100}}


@pytest.mark.asyncio
async def test_resumes_from_the_persisted_page(monkeypatch) -> None:
    db = _FakeDB(
        seeded_cursor={"delta": {"page": 5, "since": _SINCE_ISO, "page_size": 100}}
    )
    traffit = _FakeTraffit(_pages(6))
    imp = _make_importer(db, traffit, monkeypatch)

    await imp.import_pipelines(since=_SINCE)

    assert traffit.start_pages == [5]  # not 1


@pytest.mark.asyncio
async def test_clean_run_retires_only_its_own_slot(monkeypatch) -> None:
    full_slot = {"page": 300, "since": None, "page_size": 100}
    db = _FakeDB(
        seeded_cursor={
            "full": full_slot,
            "delta": {"page": 2, "since": _SINCE_ISO, "page_size": 100},
        }
    )
    traffit = _FakeTraffit(_pages(2))
    imp = _make_importer(db, traffit, monkeypatch)

    await imp.import_pipelines(since=_SINCE)

    # Delta finished → its slot is gone; the interrupted full sweep keeps its
    # position for the weekly reconcile.
    assert db.cursor == {"full": full_slot}


@pytest.mark.asyncio
async def test_page_size_mismatch_ignores_the_cursor(monkeypatch) -> None:
    db = _FakeDB(
        seeded_cursor={"delta": {"page": 9, "since": _SINCE_ISO, "page_size": 50}}
    )
    traffit = _FakeTraffit(_pages(2))
    imp = _make_importer(db, traffit, monkeypatch)

    await imp.import_pipelines(since=_SINCE)

    assert traffit.start_pages == [1]
