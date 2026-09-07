"""Digest dopasowań — kontrakty harmonogramu, progu, świeżości i BRAMKI.

Bramka dopuszczalności + dealbreakery (2026-08-20) mają jedno uzasadnienie:
liczba w powiadomieniu ma dać się odnaleźć w zakładce, do której powiadomienie
linkuje. Testy 11-14 idą przez REALNY Postgres i realną
`filter_eligible_candidates` — atrapa bramki dowiodłaby tylko, że wołamy
funkcję o tej nazwie, a defekt polegał na tym, że nie wołaliśmy jej wcale.
"""

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select

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

    # Atrapa oferty MUSI nieść pola czytane przez bramkę i dealbreakery:
    # `client_id` (konflikty klienta), `hiring_manager_contact_id` (weto),
    # `rate_budget_hourly` (sufit budżetu). `SimpleNamespace` nie ma atrybutów
    # domyślnych, więc ich brak to `AttributeError` — dokładnie ta awaria,
    # którą Talent Radar zaliczył na produkcji 13.08.
    job = SimpleNamespace(
        id=77,
        title="Analityk",
        client_id=1,
        hiring_manager_contact_id=None,
        rate_budget_hourly=None,
        must_skills=None,
        nice_skills=None,
    )

    async def fake_pool(
        db, text, top_k, query_variants=None, bm25_query=None, must_groups=None
    ):
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
        # Bramka jest tu ZAMOCKOWANA (patrz niżej) właśnie po to, żeby nie
        # dokładała własnych `execute` i nie przesuwała tej numeracji; o samej
        # bramce są testy przez realny Postgres na dole pliku.
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

    async def passthrough_gate(db, *, job, candidates, now):
        return list(candidates)

    monkeypatch.setattr(
        "app.services.retrieval_pool.retrieve_candidate_pool", fake_pool
    )
    monkeypatch.setattr(
        "app.services.pipeline_eligibility.filter_eligible_candidates",
        passthrough_gate,
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


# ── Bramka dopuszczalności + dealbreakery — przez REALNY Postgres ────────────
#
# Powiadomienie linkuje do `/jobs/{id}`, czyli do zakładki, która filtruje
# zawieranie (blacklista, NDA, konflikt konkurencyjny, weto HM) i stosuje twardy
# sufit budżetu. Digest, który liczy inaczej, obiecuje pracę, której nie ma.


async def _seed_job(rate_budget_hourly: float | None = None) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client
    from app.models.job import Job, JobStatus

    async with AsyncSessionLocal() as db:
        client = Client(name=f"DigestClient-{uuid.uuid4().hex[:6]}")
        db.add(client)
        await db.commit()
        await db.refresh(client)
        job = Job(
            title=f"Digest-Job-{uuid.uuid4().hex[:6]}",
            status=JobStatus.published,
            client_id=client.id,
            rate_budget_hourly=rate_budget_hourly,
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return job.id


async def _seed_candidate(
    *, status: str = "active", expected_rate_hourly: float | None = None
) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate, CandidateStatus

    async with AsyncSessionLocal() as db:
        candidate = Candidate(
            name="Digest",
            lastname=f"Cand-{uuid.uuid4().hex[:6]}",
            email=f"digest-{uuid.uuid4().hex[:8]}@example.com",
            status=CandidateStatus(status),
            expected_rate_hourly=expected_rate_hourly,
        )
        db.add(candidate)
        await db.commit()
        await db.refresh(candidate)
        return candidate.id


def _wire_digest(monkeypatch, candidate_ids: list[int], scored: list) -> None:
    """Podepnij pulę, profil i scoring; bramka i dealbreakery zostają PRAWDZIWE.

    `scored` jest listą, do której trafiają kandydaci przekazani do scoringu —
    dzięki temu można asertować KOLEJNOŚĆ (bramka przed `bulk_get_or_compute`),
    a nie tylko wynik. Sam wynik nie odróżnia „odfiltrowany" od „odfiltrowany
    po zapłaceniu za scoring i zatruciu cache".
    """

    async def fake_pool(
        db, text, *, top_k, query_variants=None, bm25_query=None, must_groups=None
    ):
        return [{"candidate_id": cid, "score": 0.9} for cid in candidate_ids]

    async def fake_profile(db):
        return "profil"

    async def fake_bulk(job_arg, candidates, db, *, similarity_map, profile):
        scored.extend(candidates)
        return [SimpleNamespace(candidate_id=c.id, total=90.0) for c in candidates]

    monkeypatch.setattr(
        "app.services.retrieval_pool.retrieve_candidate_pool", fake_pool
    )
    monkeypatch.setattr(
        "app.services.scoring_service.resolve_active_profile", fake_profile
    )
    monkeypatch.setattr("app.services.match_score_cache.bulk_get_or_compute", fake_bulk)
    monkeypatch.setattr(settings, "MATCH_DIGEST_MIN_SCORE", 55.0, raising=False)
    monkeypatch.setattr(settings, "MATCH_DIGEST_TOP_N", 5, raising=False)


@pytest.mark.asyncio
async def test_ineligible_candidate_never_reaches_scoring(monkeypatch):
    """Zablokowany globalnie nie wchodzi do digestu ANI do scoringu."""
    from app.core.database import AsyncSessionLocal
    from app.models.job import Job
    from app.tasks.match_digest import _fresh_top_matches as fresh

    job_id = await _seed_job()
    ok_id = await _seed_candidate()
    blocked_id = await _seed_candidate(status="blacklisted")
    scored: list = []
    _wire_digest(monkeypatch, [ok_id, blocked_id], scored)

    async with AsyncSessionLocal() as db:
        job = await db.scalar(select(Job).where(Job.id == job_id))
        top = await fresh(db, job)

    assert [cid for cid, _ in top] == [ok_id]
    assert [c.id for c in scored] == [ok_id], (
        "bramka MUSI stać przed scoringiem — inaczej płacimy za ludzi, których "
        "nie pokażemy, i zapisujemy ich do wspólnego cache"
    )


@pytest.mark.asyncio
async def test_known_rate_above_budget_is_dropped_unknown_passes(monkeypatch):
    """Twardy sufit budżetu: znana stawka powyżej odpada, nieznana PRZECHODZI.

    Równość mieści się w budżecie — „dokładnie w budżecie" to nie jest
    przekroczenie.
    """
    from app.core.database import AsyncSessionLocal
    from app.models.job import Job
    from app.tasks.match_digest import _fresh_top_matches as fresh

    job_id = await _seed_job(rate_budget_hourly=120)
    too_expensive = await _seed_candidate(expected_rate_hourly=250)
    exactly_in = await _seed_candidate(expected_rate_hourly=120)
    unknown = await _seed_candidate()
    scored: list = []
    _wire_digest(monkeypatch, [too_expensive, exactly_in, unknown], scored)

    async with AsyncSessionLocal() as db:
        job = await db.scalar(select(Job).where(Job.id == job_id))
        top = await fresh(db, job)

    assert {cid for cid, _ in top} == {exactly_in, unknown}
    assert too_expensive not in {c.id for c in scored}


@pytest.mark.asyncio
async def test_digest_uses_the_same_dealbreaker_parameters_as_the_default_tab(
    monkeypatch,
):
    """Test na OBIETNICĘ z powiadomienia, nie na implementację.

    Widget startuje z budżetem ON i biurem OFF, a przy tych wartościach nie
    robi żywego zapytania — serwuje snapshot z `compute_proposals`. Digest musi
    liczyć tą samą parą. Gdyby ktoś przestawił go na parametry `/recommendations`
    z query, ten test powie dlaczego nie.
    """
    from app.core.database import AsyncSessionLocal
    from app.models.job import Job
    from app.services import dealbreaker_filters as df
    from app.tasks.match_digest import _fresh_top_matches as fresh

    job_id = await _seed_job(rate_budget_hourly=333)
    candidate_id = await _seed_candidate()
    scored: list = []
    _wire_digest(monkeypatch, [candidate_id], scored)

    seen: dict = {}
    real_apply = df.apply_dealbreakers

    def spy(candidates, **kwargs):
        seen.update(kwargs)
        return real_apply(candidates, **kwargs)

    monkeypatch.setattr(df, "apply_dealbreakers", spy)

    async with AsyncSessionLocal() as db:
        job = await db.scalar(select(Job).where(Job.id == job_id))
        await fresh(db, job)

    assert seen["inputs"].budget_hourly == 333.0
    assert seen.get("exclude_over_budget", True) is True
    assert seen.get("exclude_remote_only", False) is False


@pytest.mark.asyncio
async def test_empty_after_filters_sends_nothing(monkeypatch):
    """Pusto po filtrach ⇒ `[]` i ZERO wywołań scoringu."""
    from app.core.database import AsyncSessionLocal
    from app.models.job import Job
    from app.tasks.match_digest import _fresh_top_matches as fresh

    job_id = await _seed_job()
    blocked_id = await _seed_candidate(status="blacklisted")
    scored: list = []
    _wire_digest(monkeypatch, [blocked_id], scored)

    async with AsyncSessionLocal() as db:
        job = await db.scalar(select(Job).where(Job.id == job_id))
        top = await fresh(db, job)

    assert top == []
    assert scored == [], "pusta lista nie może kosztować wywołania scoringu"
