"""Audyt 22.09 r2 (INTG-03): delta `pipelines` czyta tylko ogon historii.

Filtr `created_at` nie zawężał odpowiedzi /recruitment_history, więc każda
delta przemiatała ~199 tys. wpisów (godziny) i deploy ubijał ją przed końcem.
Delta ogonowa sortuje `id DESC` i kończy na pierwszej stronie, na której
pojawił się wpis starszy niż `since`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

import app.services.traffit.importer as importer_mod
from app.services.traffit.importer import TraffitImporter, WithdrawnReasonFallback

UTC = timezone.utc
_SINCE = datetime(2026, 9, 20, 0, 0, tzinfo=UTC)


class _Result:
    def fetchone(self):
        return None


class _FakeDB:
    def __init__(self):
        self.cursor_sql: list[str] = []

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        if "traffit_sync_state" in sql:
            self.cursor_sql.append(sql)
        return _Result()

    async def commit(self):
        pass

    async def rollback(self):
        pass


class _FakeTraffit:
    def __init__(self, pages):
        self.pages = pages
        self.calls: list[dict] = []
        self.pages_served = 0

    async def total_count(self, path):
        return 99999

    async def get_pages(self, path, **kw):
        self.calls.append(kw)
        for page_no, items in self.pages:
            if page_no < kw.get("start_page", 1):
                continue
            self.pages_served += 1
            yield page_no, items


def _entry(ident: int, created: str) -> dict:
    return {"id": ident, "created_at": created}


def _importer(traffit, db, monkeypatch):
    imp = TraffitImporter(traffit, db, dry_run=False, batch_size=3)
    monkeypatch.setattr(importer_mod.settings, "TRAFFIT_PIPELINES_DELTA_TAIL", True)
    for name, value in (
        ("_build_candidate_external_id_map", {}),
        ("_build_job_external_id_map", {}),
        ("_build_managed_job_ids", set()),
        ("_build_stage_def_lookup", ({}, {})),
        ("build_user_id_map", {}),
        ("_build_withdrawn_fallback_reason_map", WithdrawnReasonFallback()),
    ):
        monkeypatch.setattr(imp, name, AsyncMock(return_value=value))
    upserted: list[str] = []

    async def _upsert(payload, reason):
        upserted.append(payload["external_id"])
        return True

    monkeypatch.setattr(imp, "_upsert_stage_row", _upsert)
    monkeypatch.setattr(imp, "_flush_stage_batch", AsyncMock())
    monkeypatch.setattr(
        importer_mod,
        "traffit_recruitment_history_to_stage",
        lambda raw, *a: {
            "external_id": str(raw["id"]),
            "candidate_id": 1,
            "job_id": 2,
            "stage_def_id": 3,
            "stage_legacy_enum": "applied",
        },
    )
    return imp, upserted


@pytest.mark.asyncio
async def test_delta_stops_at_the_first_page_older_than_since(monkeypatch):
    pages = [
        # Czas lokalny Traffita (CEST): 21.09 10:00 = 08:00Z > since.
        (1, [_entry(9, "2026-09-21 10:00:00"), _entry(8, "2026-09-21 09:00:00")]),
        (2, [_entry(7, "2026-09-20 12:00:00"), _entry(6, "2026-09-19 23:00:00")]),
        (3, [_entry(5, "2026-09-18 10:00:00"), _entry(4, "2026-09-17 10:00:00")]),
    ]
    traffit = _FakeTraffit(pages)
    db = _FakeDB()
    imp, upserted = _importer(traffit, db, monkeypatch)

    progress = await imp.import_pipelines(since=_SINCE)

    assert traffit.calls[0]["sort_desc"] is True
    assert traffit.pages_served == 2  # strona 3 nie jest już pobierana
    assert upserted == ["9", "8", "7"]
    assert progress.skipped_before_since == 1
    assert progress.as_dict()["skipped_before_since"] == 1
    # Delta ogonowa nie zapisuje kursora stron (tylko czyści stary slot).
    assert not any("INSERT INTO traffit_sync_state" in s for s in db.cursor_sql)


@pytest.mark.asyncio
async def test_ignored_desc_sort_falls_back_to_the_full_delta_scan(monkeypatch):
    pages = [
        (1, [_entry(1, "2026-09-21 10:00:00"), _entry(2, "2026-09-21 11:00:00")]),
        (2, [_entry(3, "2026-09-21 12:00:00")]),
    ]
    traffit = _FakeTraffit(pages)
    imp, upserted = _importer(traffit, _FakeDB(), monkeypatch)

    await imp.import_pipelines(since=_SINCE)

    assert len(traffit.calls) == 2
    assert traffit.calls[1].get("sort_desc", False) is False
    assert upserted == ["1", "2", "3"]


@pytest.mark.asyncio
async def test_full_reconcile_does_not_use_the_tail(monkeypatch):
    pages = [(1, [_entry(1, "2020-01-01 10:00:00")])]
    traffit = _FakeTraffit(pages)
    imp, upserted = _importer(traffit, _FakeDB(), monkeypatch)

    await imp.import_pipelines(since=None)

    assert traffit.calls[0].get("sort_desc", False) is False
    assert upserted == ["1"]
