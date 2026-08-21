"""Nieudana invalidacja cache'u po screeningu nie może być niewidzialna.

`match_score_cache` nie ma TTL, więc kompozyt (kandydat, oferta) serwuje
przedscreeningowy `champion_fit` do czasu, aż coś innego przypadkiem oznaczy
tego kandydata jako nieświeżego. Handler połykał wyjątek bez jednej linii logu:
rekruter widział zapisany screening i niezmieniony wynik, co czyta się jako
„AI nie zgadza się z moim screeningiem", a nie „invalidacja padła" — i czego
nie da się zdiagnozować później nawet z pełnym dostępem do logów.
"""

from __future__ import annotations

import logging
import types

import pytest

from app.api import pipeline as pipeline_api


class _FakeStage:
    def __init__(self):
        self.id = 41
        self.candidate_id = 7
        self.job_id = 9
        self.screening_answers = None


class _FakeDb:
    def __init__(self, stage):
        self._stage = stage
        self.commits = 0
        self.rollbacks = 0
        self.added = []

    async def scalar(self, _query):
        return self._stage

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1

    async def refresh(self, _obj):
        return None


async def _call(db, user):
    return await pipeline_api.submit_stage_screening(
        stage_id=41,
        current_user=user,
        db=db,
        payload={"overall_fit": "fit", "answers": []},
    )


@pytest.fixture
def user():
    return types.SimpleNamespace(id=3, name="Rekruter", email="r@example.com")


async def test_padnieta_invalidacja_zostawia_ostrzezenie_i_flage(
    monkeypatch, caplog, user
):
    async def _boom(_db, _candidate_id):
        raise RuntimeError("lock timeout na match_score_cache")

    monkeypatch.setattr(
        "app.services.match_score_cache.mark_stale_for_candidate", _boom
    )
    db = _FakeDb(_FakeStage())

    with caplog.at_level(logging.WARNING, logger=pipeline_api.__name__):
        result = await _call(db, user)

    assert result["cache_invalidated"] is False
    assert db.rollbacks == 1
    messages = [r.getMessage() for r in caplog.records]
    assert any("staleness marking failed" in m for m in messages), messages
    # Log musi wskazywać kandydata — bez identyfikatora linia jest bezużyteczna.
    assert any("candidate=7" in m for m in messages), messages


async def test_udana_invalidacja_nie_szumi_w_logu(monkeypatch, caplog, user):
    calls: list[int] = []

    async def _ok(_db, candidate_id):
        calls.append(candidate_id)

    monkeypatch.setattr("app.services.match_score_cache.mark_stale_for_candidate", _ok)
    db = _FakeDb(_FakeStage())

    with caplog.at_level(logging.WARNING, logger=pipeline_api.__name__):
        result = await _call(db, user)

    assert calls == [7]
    assert result["cache_invalidated"] is True
    assert db.rollbacks == 0
    assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []
