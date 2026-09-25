"""Faza `jobs` commituje paczkami (audyt 25.09.2026).

Do tej zmiany cała faza szła w JEDNEJ transakcji, a w środku pętli leciało
~4,3 tys. zapytań HTTP o detal rekrutacji (pełny bieg) — transakcja i blokady
wierszy `jobs` trzymane przez kwadrans. Teraz faza commituje co 200 zapisanych
rekrutacji, a zdarzenia dla automatów, intencje indeksu, archiwum i kategorie
idą z KAŻDĄ paczką (w tej samej transakcji co jej wiersze): migawka „przed
importem” jest ze startu fazy, więc rekrutacja zatwierdzona w przerwanym biegu
nie dostałaby ich już nigdy.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

import app.services.auto_match_outbox as auto_match_outbox_mod
import app.services.index_outbox_service as index_outbox_mod
import app.services.job_cc as job_cc_mod
import app.services.job_delivery_lead_fill as dl_fill_mod
import app.services.traffit.importer as importer_mod
import app.services.traffit_job_archive as archive_mod
from app.services.traffit.importer import TraffitImporter


class _Result:
    def __init__(self, row=None, rows=()):
        self._row = row
        self._rows = list(rows)

    def fetchone(self):
        return self._row

    def fetchall(self):
        return self._rows


class _Nested:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _FakeDB:
    def __init__(self) -> None:
        self.commits = 0
        self.upserts_at_commit: list[int] = []
        self._upserts = 0
        self._next_id = 0

    def begin_nested(self):
        return _Nested()

    async def execute(self, stmt, params=None):
        if params and "custom_fields" in params:  # `_UPSERT_JOB`
            self._upserts += 1
            self._next_id += 1
            # (id, was_insert, managed_in_nexus)
            return _Result(row=(self._next_id, True, False))
        return _Result()

    async def commit(self) -> None:
        self.commits += 1
        self.upserts_at_commit.append(self._upserts)

    async def rollback(self) -> None:
        pass


class _FakeTraffit:
    def __init__(self, n: int) -> None:
        self.n = n

    async def get_paginated(self, path, **kw):
        for i in range(self.n):
            yield {"id": 5000 + i}


@pytest.mark.asyncio
async def test_jobs_phase_commits_in_batches_with_side_effects(monkeypatch) -> None:
    db = _FakeDB()
    imp = TraffitImporter(_FakeTraffit(450), db, dry_run=False, batch_size=100)
    for name, value in {
        "_probe_total": AsyncMock(return_value=450),
        "_build_client_external_id_map": AsyncMock(return_value={}),
        "_build_workflow_external_id_map": AsyncMock(return_value={}),
        "_hide_orphan_client_if_visible": AsyncMock(return_value=1),
        "_build_job_client_map": AsyncMock(return_value={}),
        "build_user_id_map": AsyncMock(return_value={}),
        "_build_job_owner_set": AsyncMock(return_value=set()),
    }.items():
        monkeypatch.setattr(imp, name, value)
    monkeypatch.setattr(
        importer_mod,
        "traffit_recruitment_to_job",
        lambda raw, *a: {
            "external_id": str(raw["id"]),
            "client_id": 1,
            "recruiter_id": None,
            "reference_number": None,
            "status": "published",
            "title": f"Rekrutacja {raw['id']}",
            "custom_fields": {},
        },
    )
    reindex_batches: list[int] = []

    async def _record(db_, entity_type, ids):
        reindex_batches.append(len(ids))
        return len(ids)

    monkeypatch.setattr(index_outbox_mod, "record_bulk_reindex", _record)
    monkeypatch.setattr(auto_match_outbox_mod, "enqueue_job", AsyncMock())
    monkeypatch.setattr(archive_mod, "archive_traffit_jobs", AsyncMock(return_value=0))
    classify_batches: list[int] = []

    async def _classify(db_, ids):
        classify_batches.append(len(ids))
        return 0

    monkeypatch.setattr(job_cc_mod, "classify_missing_job_ccs", _classify)
    monkeypatch.setattr(
        dl_fill_mod, "fill_missing_job_delivery_leads", AsyncMock(return_value=0)
    )

    progress = await imp.import_jobs(since=None)

    assert progress.inserted == 450
    # 200 + 200 + 50 w paczkach, plus końcowy commit po uzupełnieniu DL.
    assert db.upserts_at_commit[:3] == [200, 400, 450]
    # Intencje indeksu i kategorie idą z każdą paczką, nie raz na końcu fazy.
    assert reindex_batches == [200, 200, 50]
    assert classify_batches == [200, 200, 50]
    assert progress.index_intents == 450
