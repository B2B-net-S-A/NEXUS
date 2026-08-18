"""Digest dopasowań — kontrakty harmonogramu, progu i świeżości."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.models.notification import NotificationType
from app.tasks.match_digest import _fresh_top_matches, _is_due


def test_notification_type_registered():
    assert NotificationType.match_digest.value == "match_digest"


def test_is_due_weekly_monday_window(monkeypatch):
    monkeypatch.setattr(settings, "MATCH_DIGEST_WEEKDAY", 0, raising=False)
    monkeypatch.setattr(settings, "MATCH_DIGEST_HOUR_UTC", 6, raising=False)

    monday_7am = datetime(2026, 8, 24, 7, 0, tzinfo=timezone.utc)
    assert monday_7am.weekday() == 0
    assert _is_due(None, monday_7am) is True, "pierwszy bieg od razu"
    assert _is_due(monday_7am - timedelta(days=7), monday_7am) is True
    assert _is_due(monday_7am - timedelta(days=6, hours=23), monday_7am) is True

    tuesday = datetime(2026, 8, 25, 7, 0, tzinfo=timezone.utc)
    assert _is_due(monday_7am - timedelta(days=7), tuesday) is False
    monday_5am = datetime(2026, 8, 24, 5, 0, tzinfo=timezone.utc)
    assert _is_due(monday_5am - timedelta(days=7), monday_5am) is False
    assert _is_due(monday_7am - timedelta(days=2), monday_7am) is False


@pytest.mark.asyncio
async def test_fresh_top_filters_staged_and_floor(monkeypatch):
    """Świeżość (spoza pipeline'u) + próg score + top-N — jedna ścieżka."""
    import app.tasks.match_digest as md

    job = SimpleNamespace(id=77, title="Analityk")

    async def fake_pool(db, text, top_k):
        return [
            {"candidate_id": 1, "score": 0.9},  # staged — odpada
            {"candidate_id": 2, "score": 0.8},  # score 70 — wchodzi
            {"candidate_id": 3, "score": 0.7},  # score 40 — pod progiem
            {"candidate_id": 4, "score": 0.6},  # score 60 — wchodzi
        ]

    class FakeResult:
        def __init__(self, values):
            self._values = values

        def scalars(self):
            return self

        def all(self):
            return self._values

        def scalar_one_or_none(self):
            return self._values

    class FakeDb:
        # Stanowy dispatch po KOLEJNOŚCI wywołań, nie po treści SQL —
        # `"candidate_stages" in str(stmt)` pękłoby cicho przy zmianie nazwy
        # tabeli/aliasu. Kontrakt _fresh_top_matches: najpierw SELECT staged,
        # potem SELECT kandydatów; zmiana kolejności = czerwony test, jawnie.
        def __init__(self):
            self.calls = 0

        async def execute(self, stmt):
            self.calls += 1
            if self.calls == 1:
                return FakeResult([1])
            return FakeResult([SimpleNamespace(id=cid) for cid in (2, 3, 4)])

    async def fake_profile(db):
        return "profil"

    async def fake_bulk(job_arg, candidates, db, *, similarity_map, profile):
        scores = {2: 70.0, 3: 40.0, 4: 60.0}
        return [
            SimpleNamespace(candidate_id=c.id, total=scores[c.id]) for c in candidates
        ]

    monkeypatch.setattr(
        "app.services.retrieval_pool.retrieve_candidate_pool", fake_pool
    )
    monkeypatch.setattr(
        "app.services.scoring_service.resolve_active_profile", fake_profile
    )
    monkeypatch.setattr("app.services.match_score_cache.bulk_get_or_compute", fake_bulk)
    monkeypatch.setattr(
        "app.services.embedding_service._build_job_text", lambda j: "tekst"
    )
    monkeypatch.setattr(settings, "MATCH_DIGEST_MIN_SCORE", 55.0, raising=False)
    monkeypatch.setattr(settings, "MATCH_DIGEST_TOP_N", 5, raising=False)

    top = await md._fresh_top_matches(FakeDb(), job)
    assert top == [(2, 70.0), (4, 60.0)], (
        "staged odpada, pod progiem odpada, reszta malejąco po score"
    )
    assert _fresh_top_matches is md._fresh_top_matches
