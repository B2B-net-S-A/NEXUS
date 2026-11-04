"""Audyt eksportu kandydatów niesie liczbę osób w pliku (audyt 22.10, F24/F97).

Alarm masowego przeglądania CV (0508) liczy osoby w eksportach jako
``coalesce(row_count, selected_count, 0)``. Eksport „wszystkich z filtrem”
nie przyjmuje ``candidate_ids``, więc ``selected_count`` jest tam zawsze 0 —
bez ``row_count`` największe eksporty (do 100 tys. osób) wnosiły do progu 0.
Bez bazy: trasa wołana wprost, zapytania podmienione.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import select

import app.models  # noqa: F401
from app.api import candidates as candidates_api
from app.models.candidate import Candidate


class _FakeDb:
    def __init__(self, total: int):
        self.total = total

    async def scalar(self, _query):
        return self.total

    async def commit(self):
        return None


@pytest.fixture
def recorded(monkeypatch):
    events: list[dict] = []

    def record(db, **kwargs):
        events.append(kwargs)

    async def no_semantic(db, filters):
        return None, None

    async def plain_query(db, filters, **kwargs):
        return select(Candidate), []

    monkeypatch.setattr(
        candidates_api.candidate_audit, "record_candidate_audit", record
    )
    monkeypatch.setattr(candidates_api, "_resolve_semantic_text", no_semantic)
    monkeypatch.setattr(candidates_api, "_build_candidate_filtered_query", plain_query)
    monkeypatch.setattr(
        candidates_api, "_apply_candidate_sort", lambda query, *a, **k: query
    )
    return events


@pytest.mark.asyncio
async def test_filtered_export_audit_carries_row_count(recorded) -> None:
    payload = candidates_api.CandidateExportRequest(
        scope="filtered",
        filters=candidates_api.CandidateFilterSpec(sort="newest"),
    )
    await candidates_api.export_candidates_v2(
        payload, SimpleNamespace(id=7), _FakeDb(total=8_000)
    )
    (event,) = recorded
    assert event["action"] == "export_requested"
    assert event["details"]["scope"] == "filtered"
    assert event["details"]["row_count"] == 8_000
    assert event["details"]["selected_count"] == 0


@pytest.mark.asyncio
async def test_selected_export_audit_row_count_is_the_selection(recorded) -> None:
    payload = candidates_api.CandidateExportRequest(
        scope="selected", candidate_ids=[3, 3, 5]
    )
    await candidates_api.export_candidates_v2(
        payload, SimpleNamespace(id=7), _FakeDb(total=2)
    )
    (event,) = recorded
    assert event["details"]["row_count"] == 2
    assert event["details"]["selected_count"] == 2
