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
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.services import job_similarity as sim
from app.services import trainee_call_list as lists
from app.services import trainee_rules as rules_mod

TODAY = date(2026, 9, 24)
NOW = datetime(2026, 9, 24, 10, tzinfo=timezone.utc)


def _cand(cid: int, skills, cc=1, **kw):
    base = {
        "id": cid,
        "competence_category_id": cc,
        "skills": skills,
        "expected_rate_hourly": None,
        "profile_rate_updated_at": None,
        "b2b_willingness": None,
        "work_time_preference": "also_part_time",
        "preferences": {"remote_modes": ["hybrid"]},
        "max_onsite_days_per_week": 2,
        "accepts_below_min_rate": True,
        "accepts_more_office_days": True,
        "availability_status": "open_to_offers",
        "availability_date": None,
    }
    base.update(kw)
    return SimpleNamespace(**base)


def _pool_job(jid: int, names, *, cc=1, status="published", created_at=None):
    return SimpleNamespace(
        id=jid,
        skills=sim.skill_set(names),
        competence_category_id=cc,
        status=status,
        created_at=created_at,
    )


def _reference_rank(rows, pool_jobs, rules, now):
    """Algorytm sprzed rundy 6, przepisany 1:1 — wzorzec „wynik ten sam”."""
    since = now - timedelta(days=round(int(rules["window_months"]) * 30.44))
    index = rules_mod.build_index(
        rules_mod.DemandJob(
            id=j.id,
            skills=j.skills,
            competence_category_id=j.competence_category_id,
            is_open=j.status == "published",
        )
        for j in pool_jobs
        if j.created_at is None or j.created_at >= since
    )
    ranked = []
    for row in rows:
        skills, display = lists._candidate_skills(row.skills)
        demand = rules_mod.demand_for(skills, row.competence_category_id, index)
        if demand.fits < int(rules["min_fits"]):
            continue
        missing = rules_mod.missing_codes(row, rules, now=now)
        if not missing:
            continue
        ranked.append(
            (
                rules_mod.rank_key(row.id, demand, missing),
                lists.RankedCandidate(
                    candidate_id=row.id,
                    competence_category_id=row.competence_category_id,
                    demand=demand,
                    missing=tuple(missing),
                    stack_display=tuple(display.get(s, s) for s in demand.stack),
                ),
            )
        )
    ranked.sort(key=lambda pair: pair[0])
    return [item for _, item in ranked]


def _world():
    pool_jobs = [
        _pool_job(1, ["Java", "Spring"]),
        _pool_job(2, ["Java", "Spring"], status="closed"),
        _pool_job(3, ["Java"]),
        _pool_job(4, ["Python"], cc=2),
        _pool_job(5, ["Java"], created_at=NOW - timedelta(days=4000)),
    ]
    rows = [
        _cand(10, ["Java", "Spring"]),
        _cand(11, ["Java"]),
        _cand(12, ["Python"], cc=2),
        _cand(13, ["Java", "Spring"], b2b_willingness="b2b"),  # mniej luk
        _cand(14, ["Cobol"]),  # bez popytu
        _cand(
            15,
            ["Java"],
            expected_rate_hourly=150,
            profile_rate_updated_at=NOW,
            b2b_willingness="b2b",
        ),  # bez luk
    ]
    return rows, pool_jobs


# ── PERF-1: praktykant ────────────────────────────────────────────────────


def test_rank_rows_gives_the_same_ranking_as_before() -> None:
    rows, pool_jobs = _world()
    rules = dict(rules_mod.DEFAULT_RULES, min_fits=1)
    got = lists._rank_rows(rows, pool_jobs, rules, NOW)
    assert got == _reference_rank(rows, pool_jobs, rules, NOW)
    assert [item.candidate_id for item in got][:1] == [10]
    assert {item.candidate_id for item in got}.isdisjoint({14, 15})


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


@pytest.fixture
def trainee_world(monkeypatch):
    rows, pool_jobs = _world()
    fake_pool = SimpleNamespace(jobs={j.id: j for j in pool_jobs})

    async def _fake_load_pool(_db):
        return fake_pool

    monkeypatch.setattr(sim, "_load_pool", _fake_load_pool)
    threads: list[int] = []
    original = lists._rank_rows

    def _spy(*args, **kwargs):
        threads.append(threading.get_ident())
        return original(*args, **kwargs)

    monkeypatch.setattr(lists, "_rank_rows", _spy)
    lists.reset_ranking_cache()
    yield SimpleNamespace(db=_FakeDb(rows), threads=threads)
    lists.reset_ranking_cache()


async def test_rank_pool_counts_in_a_worker_thread(trainee_world) -> None:
    rules = dict(rules_mod.DEFAULT_RULES, min_fits=1)
    ranked = await lists.rank_pool(trainee_world.db, rules, today=TODAY)
    assert ranked, "pula z danymi testowymi nie może być pusta"
    assert trainee_world.threads
    assert all(t != threading.get_ident() for t in trainee_world.threads)


async def test_concurrent_rankings_are_computed_once(trainee_world) -> None:
    rules = dict(rules_mod.DEFAULT_RULES, min_fits=1)
    first, second, third = await asyncio.gather(
        lists.cached_ranking(trainee_world.db, rules, today=TODAY),
        lists.cached_ranking(trainee_world.db, rules, today=TODAY),
        lists.cached_ranking(trainee_world.db, rules, today=TODAY),
    )
    assert first == second == third
    assert len(trainee_world.threads) == 1
    assert trainee_world.db.executes == 1


async def test_pool_stats_reuses_the_given_ranking(monkeypatch) -> None:
    """Pętla poranna: statystyki z rankingu list, bez drugiego liczenia puli.
    Osoby rozdane dziś odpadają — świeże liczenie też by ich nie wzięło."""

    async def _no_second_ranking(*_a, **_k):
        raise AssertionError("pool_stats nie może liczyć puli drugi raz")

    async def _assigned(_db, _day):
        return {11}

    monkeypatch.setattr(lists, "_rank_pool_unlocked", _no_second_ranking)
    monkeypatch.setattr(lists, "_assigned_on", _assigned)

    class _Db:
        async def scalars(self, *_a, **_k):
            return SimpleNamespace(all=lambda: [SimpleNamespace(id=1, name_pl="Dev")])

    rows, pool_jobs = _world()
    rules = dict(rules_mod.DEFAULT_RULES, min_fits=1)
    ranked = lists._rank_rows(rows, pool_jobs, rules, NOW)
    assert any(item.candidate_id == 11 for item in ranked)
    stats = await lists.pool_stats(_Db(), rules, today=TODAY, ranked=ranked)
    expected = [item for item in ranked if item.candidate_id != 11]
    assert stats["size"] == len(expected)
    assert stats["open_fit"] == sum(1 for i in expected if i.demand.open_fits > 0)


async def test_rules_preview_is_single_flight_and_cached(monkeypatch) -> None:
    from app.core.cache import cache_invalidate

    await cache_invalidate("trainee_pool_preview")
    lists.reset_ranking_cache()
    computed: list[int] = []

    async def _rank(_db, rules, *, today):
        computed.append(int(rules["window_months"]))
        await asyncio.sleep(0.01)
        return []

    async def _assigned(_db, _day):
        return set()

    monkeypatch.setattr(lists, "_rank_pool_unlocked", _rank)
    monkeypatch.setattr(lists, "_assigned_on", _assigned)

    class _Db:
        def in_transaction(self):
            return False

        async def scalars(self, *_a, **_k):
            return SimpleNamespace(all=lambda: [])

    rules = dict(rules_mod.DEFAULT_RULES, window_months=17)
    other = dict(rules_mod.DEFAULT_RULES, window_months=19)
    try:
        results = await asyncio.gather(
            *(lists.preview_pool_stats(_Db(), rules, today=TODAY) for _ in range(4))
        )
        assert all(r["size"] == 0 for r in results)
        await lists.preview_pool_stats(_Db(), rules, today=TODAY)
        assert computed == [17]
        await lists.preview_pool_stats(_Db(), other, today=TODAY)
        assert computed == [17, 19]
        # Podgląd nie wyrzuca rankingu dnia, z którego praktykanci biorą listy.
        assert lists._ranked_cache == {}
    finally:
        await cache_invalidate("trainee_pool_preview")


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
        expected = sim._rank(
            pool, sim._as_pool_job(job), set(linked.get(job.id, []))
        )[: sim.MAX_SUGGESTIONS]
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
