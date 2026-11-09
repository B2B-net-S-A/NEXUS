"""Runda 6 audytu — ciężkie CPU poza pętlą zdarzeń jedynego procesu API.

Backend to jeden proces uvicorna: sekundy CPU liczone na pętli zatrzymują
całe API razem z ``/api/health/live`` (healthcheck 5 s × 3). Każdy test
sprawdza dwie rzeczy: wynik jest ten sam co przed zmianą, a ciężka praca
idzie przez wątek (``asyncio.to_thread``) albo liczy się raz (single-flight).
Bez bazy — sesja jest atrapą.
"""

from __future__ import annotations

import asyncio
import threading
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest

from app.services import job_similarity as sim

TODAY = date(2026, 9, 24)
NOW = datetime(2026, 9, 24, 10, tzinfo=timezone.utc)


# ── PERF-1: praktykant ────────────────────────────────────────────────────


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class _FakeDb:
    def __init__(self, rows):
        self.rows = rows
        self.executes = 0

    async def execute(self, *_a, **_k):
        self.executes += 1
        await asyncio.sleep(0)
        return _Result(self.rows)


# ── PERF-2: podobne rekrutacje ────────────────────────────────────────────


def _job_row(jid, title, skills, *, cc=1, client=1, status="published"):
    return SimpleNamespace(
        id=jid,
        title=title,
        client_id=client,
        reference_number=f"R-{jid}",
        status=status,
        competence_category_id=cc,
        must_skills=skills,
        champion_profile=None,
        created_at=None,
    )


_JOB_ROWS = [
    _job_row(1, "Java Developer", ["Java", "Spring"]),
    _job_row(2, "Senior Java Developer", ["Java", "Spring", "Kafka"]),
    _job_row(3, "Java Engineer", ["Java", "Spring"], client=2),
    _job_row(4, "Python Developer", ["Python"], cc=2),
    _job_row(5, "Tester manualny", ["Selenium"], cc=3, status="closed"),
]


@pytest.fixture
def similarity_world(monkeypatch):
    sim.reset_pool_cache()
    threads: list[int] = []
    original = sim._build_pool

    def _spy(rows):
        threads.append(threading.get_ident())
        return original(rows)

    monkeypatch.setattr(sim, "_build_pool", _spy)
    yield SimpleNamespace(db=_FakeDb(_JOB_ROWS), threads=threads)
    sim.reset_pool_cache()


async def test_pool_reload_is_single_flight_and_built_in_a_thread(
    similarity_world,
) -> None:
    pools = await asyncio.gather(
        *(sim._load_pool(similarity_world.db) for _ in range(5))
    )
    assert all(pool is pools[0] for pool in pools)
    assert similarity_world.db.executes == 1
    assert len(similarity_world.threads) == 1
    assert similarity_world.threads[0] != threading.get_ident()
    assert set(pools[0].jobs) == {1, 2, 3, 4, 5}


async def test_suggestion_summaries_rank_in_a_thread_and_keep_the_result(
    similarity_world, monkeypatch
) -> None:
    async def _sent(_db, ids):
        return {job_id: 1 for job_id in ids}

    monkeypatch.setattr(sim, "sent_counts", _sent)

    async def _no_vectors(_db, _pool, _refs, **_k):
        # Żadna rekrutacja nie ma wektora — ranking leksykalny w wątku
        # (ranking wektorowy: test_job_similar_vector.py).
        return {}

    monkeypatch.setattr(sim, "_vector_neighbours", _no_vectors)
    rank_threads: list[int] = []
    original = sim._rank_many

    def _spy(pool, work):
        rank_threads.append(threading.get_ident())
        return original(pool, work)

    monkeypatch.setattr(sim, "_rank_many", _spy)
    jobs = [
        SimpleNamespace(
            id=row.id,
            title=row.title,
            client_id=row.client_id,
            reference_number=row.reference_number,
            status=row.status,
            competence_category_id=row.competence_category_id,
            must_skills=row.must_skills,
            champion_profile=None,
            created_at=None,
        )
        for row in _JOB_ROWS
    ]
    linked = {2: [3]}
    first = await sim.suggestion_summaries(similarity_world.db, jobs, linked)

    pool = await sim._load_pool(similarity_world.db)
    for job in jobs:
        if job.status == "closed":
            assert job.id not in first
            continue
        expected = sim._rank(pool, sim._as_pool_job(job), set(linked.get(job.id, [])))[
            : sim.MAX_SUGGESTIONS
        ]
        if expected:
            assert first[job.id]["count"] == len(expected)
            assert first[job.id]["first"]["id"] == expected[0][0]
        else:
            assert job.id not in first
    assert first, "dane testowe muszą dać choć jedną sugestię"
    assert rank_threads and rank_threads[0] != threading.get_ident()

    second = await sim.suggestion_summaries(similarity_world.db, jobs, linked)
    assert second == first
    assert len(rank_threads) == 1, "druga strona z pamięci puli, bez liczenia"


# ── PERF-3: ponowny zapis zużycia AI ──────────────────────────────────────


def _declared_with_pending(monkeypatch):
    from app.models.ai_feature import AIFeatureKey
    from app.services import ai_metering, ai_quota

    threads: list[int] = []

    def _persist(event):
        threads.append(threading.get_ident())
        return True

    monkeypatch.setattr(ai_metering, "persist_response", _persist)
    state = ai_quota.QuotaState(used=1, limit=0, period_start=date(2026, 9, 1))

    def _run():
        with ai_quota.declared_call(AIFeatureKey.uop_check, user_id=None, state=state):
            ai_quota.current_ai_call().pending_responses.append(
                {"event_key": "synthetic"}
            )

    return ai_quota, threads, _run


async def test_pending_usage_retry_leaves_the_event_loop(monkeypatch) -> None:
    ai_quota, threads, run = _declared_with_pending(monkeypatch)
    run()
    await asyncio.gather(*list(ai_quota._background_persists))
    assert threads and threads[0] != threading.get_ident()


def test_pending_usage_retry_stays_synchronous_in_a_worker_thread(
    monkeypatch,
) -> None:
    _ai_quota, threads, run = _declared_with_pending(monkeypatch)
    run()
    assert threads == [threading.get_ident()]


# ── PERF-4: import rejestru umów ──────────────────────────────────────────


async def test_register_parser_runs_in_a_thread(monkeypatch) -> None:
    from app.services.b2b_register_import import service

    threads: list[int] = []

    class _Stop(Exception):
        pass

    def _parse(_payload):
        threads.append(threading.get_ident())
        raise _Stop

    monkeypatch.setattr(service, "parse_register", _parse)
    with pytest.raises(_Stop):
        await service.run_import(
            None, payload=b"x", filename="r.xlsx", user_id=1, dry_run=True
        )
    assert threads and threads[0] != threading.get_ident()
