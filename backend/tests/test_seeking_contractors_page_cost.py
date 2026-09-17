"""„Szukają projektu": koszt strony nie może rosnąć z liczbą wierszy (UAT B06).

Retest produkcji 14–15.09.2026: „Pokaż kolejnych 50" trwało ~10 s. Pula (dwa
lekkie zapytania i sort liczb) była tania — koszt siedział w pętli po wierszach
strony: embedding + Qdrant PO KOLEI dla każdego kandydata oraz ~6 100 zapytań
SQL na stronę 50 osób (2 na kandydata w filtrach konfliktów + 2 na KAŻDĄ
ocenianą parę kandydat × oferta w scoringu).

Pomiar lokalny (1 000 syntetycznych kandydatów, 60 ofert, atrapa wyszukiwania
z opóźnieniem 150 ms): przed — 10,7–11,4 s i 6 107 zapytań na stronę; po —
1,2–1,7 s i 10 zapytań.

Baza testowa jest WSPÓŁDZIELONA z innymi plikami, więc testy nie zakładają
składu puli: własni kandydaci dostają kontrakty kończące się w dalekiej
przeszłości (pula sortuje się po dacie końca — lądują na początku), a asercje
dotyczą wyłącznie własnych id. Wszystkie dane są syntetyczne.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, event, select

from app.core.database import AsyncSessionLocal, engine
from app.models.candidate import AvailabilityStatus, Candidate, CandidateStatus
from app.models.candidate_conflict import CandidateConflict, ConflictType
from app.models.client import Client
from app.models.contract import Contract, ContractStatus, ContractType, RateUnit
from app.models.job import Job, JobStatus, RemotePolicy
from app.models.recruitment_pipeline import CandidateStage, PipelineStage

URL = "/api/recommendations/seeking-contractors"
# Daleko przed jakąkolwiek realną datą końca — własni kandydaci sortują się
# jako pierwsi niezależnie od tego, co inne pliki zostawiły w bazie.
_ANCIENT_END = date(1990, 1, 1)


async def _seed(n_candidates: int, n_jobs: int, *, ending_first: bool) -> dict:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"PageCostCo-{tag}")
        db.add(client)
        await db.flush()
        jobs = [
            Job(
                title=f"PageCost job {i}",
                description="syntetyczna oferta",
                location="Warszawa",
                remote_policy=RemotePolicy.remote,
                status=JobStatus.published,
                must_skills=[{"name": "Python"}],
                nice_skills=[],
                client_id=client.id,
            )
            for i in range(n_jobs)
        ]
        cands = [
            Candidate(
                name=f"PageCost{i}",
                lastname=tag,
                availability_status=AvailabilityStatus.actively_looking,
                status=CandidateStatus.active,
                skills=[{"name": "Python"}],
                years_it_experience=5,
            )
            for i in range(n_candidates)
        ]
        db.add_all(jobs + cands)
        await db.flush()
        if ending_first:
            db.add_all(
                [
                    Contract(
                        candidate_id=cand.id,
                        client_id=client.id,
                        start_date=_ANCIENT_END - timedelta(days=365),
                        end_date=_ANCIENT_END + timedelta(days=i),
                        status=ContractStatus.active,
                        contract_type=ContractType.b2b,
                        rate_unit=RateUnit.monthly,
                        rate_candidate=15000,
                        rate_client=20000,
                    )
                    for i, cand in enumerate(cands)
                ]
            )
        await db.commit()
        return {
            "tag": tag,
            "client_id": client.id,
            "job_ids": [j.id for j in jobs],
            "candidate_ids": [c.id for c in cands],
        }


async def _cleanup(seed: dict, *, extra_client_ids: tuple[int, ...] = ()) -> None:
    async with AsyncSessionLocal() as db:
        ids = seed["candidate_ids"]
        await db.execute(
            delete(CandidateStage).where(CandidateStage.candidate_id.in_(ids))
        )
        await db.execute(
            delete(CandidateConflict).where(CandidateConflict.candidate_id.in_(ids))
        )
        await db.execute(delete(Contract).where(Contract.candidate_id.in_(ids)))
        await db.execute(delete(Job).where(Job.id.in_(seed["job_ids"])))
        await db.execute(delete(Candidate).where(Candidate.id.in_(ids)))
        await db.execute(
            delete(Client).where(Client.id.in_([seed["client_id"], *extra_client_ids]))
        )
        await db.commit()


def _hits(job_ids: list[int]) -> list[dict]:
    return [{"job_id": jid, "score": 0.5, "payload": {}} for jid in job_ids]


def _patch_search(monkeypatch, hits: list[dict], *, delay: float = 0.0, fail_for=None):
    from app.services.embedding_service import SemanticSearchUnavailable

    state = {"inflight": 0, "max_inflight": 0, "hits": hits}

    async def _fake_search(query, top_k=20, **kwargs):
        state["inflight"] += 1
        state["max_inflight"] = max(state["max_inflight"], state["inflight"])
        try:
            if delay:
                await asyncio.sleep(delay)
            if fail_for is not None and fail_for(query):
                raise SemanticSearchUnavailable("atrapa: awaria providera")
            return state["hits"]
        finally:
            state["inflight"] -= 1

    monkeypatch.setattr("app.api.recommendations.search_jobs_semantic", _fake_search)
    return state


async def _page_cost(client: AsyncClient, headers: dict, page_size: int) -> tuple:
    counter = {"n": 0}

    def _inc(*_args, **_kwargs):
        counter["n"] += 1

    event.listen(engine.sync_engine, "before_cursor_execute", _inc)
    try:
        resp = await client.get(
            URL, params={"horizon_days": 1, "page_size": page_size}, headers=headers
        )
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", _inc)
    assert resp.status_code == 200, resp.text
    return counter["n"], resp.json()


def _own_rows(body: dict, own: list[int]) -> dict[int, dict]:
    own_set = set(own)
    return {
        it["candidate"]["id"]: it
        for it in body["items"]
        if it["candidate"]["id"] in own_set
    }


@pytest.mark.asyncio
async def test_sql_per_page_does_not_grow_with_rows_or_scored_pairs(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    seed = await _seed(n_candidates=12, n_jobs=15, ending_first=True)
    own = seed["candidate_ids"]
    try:
        state = _patch_search(monkeypatch, _hits(seed["job_ids"]))
        # Rozgrzewka: cache profilu wag itp. nie może zaburzyć porównania.
        await _page_cost(app_client, app_auth_headers, 10)

        # (a) Stały rozmiar strony, 5× więcej ocenianych par kandydat × oferta.
        state["hits"] = _hits(seed["job_ids"][:3])
        few_pairs, body_few = await _page_cost(app_client, app_auth_headers, 10)
        state["hits"] = _hits(seed["job_ids"])
        many_pairs, body_many = await _page_cost(app_client, app_auth_headers, 10)
        rows = _own_rows(body_many, own)
        assert set(rows) == set(own[:10]), "własni kandydaci nie otwierają puli"
        assert all(it["top_matches"] for it in rows.values()), "scoring nie ruszył"
        assert len(_own_rows(body_few, own)) == 10
        # Przed poprawką: +2 zapytania na KAŻDĄ dodatkową parę (10 × 12 = +240).
        assert many_pairs - few_pairs <= 2, (few_pairs, many_pairs)

        # (b) Ta sama pula ofert, 5× więcej wierszy na stronie.
        small, _ = await _page_cost(app_client, app_auth_headers, 2)
        big, _ = await _page_cost(app_client, app_auth_headers, 10)
        assert big - small <= 2, (small, big)
        assert big < 30, big
    finally:
        await _cleanup(seed)


@pytest.mark.asyncio
async def test_semantic_retrieval_runs_concurrently_and_degrades_per_candidate(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    seed = await _seed(n_candidates=6, n_jobs=3, ending_first=True)
    own = seed["candidate_ids"]
    try:
        async with AsyncSessionLocal() as db:
            first = await db.get(Candidate, own[0])
            first.skills = []
            first.competence_category = None
            first.years_it_experience = None
            first.ai_summary = None
            await db.commit()
        # Kandydat bez umiejętności/podsumowania ma zapytanie z imieniem.
        failing_query = f"PageCost0 {seed['tag']}"
        state = _patch_search(
            monkeypatch,
            _hits(seed["job_ids"]),
            delay=0.05,
            fail_for=lambda q: failing_query in q,
        )

        _, body = await _page_cost(app_client, app_auth_headers, len(own))
        assert state["max_inflight"] > 1, "wyszukiwania nadal idą po kolei"
        rows = _own_rows(body, own)
        assert set(rows) == set(own), "własni kandydaci nie otwierają puli"
        failed, *ok = own
        assert rows[failed]["top_matches"] == []
        assert all(rows[cid]["top_matches"] for cid in ok), (
            "awaria przeciekła na sąsiadów"
        )
        assert body["meta"] == {"degraded": True, "reason": "semantic_unavailable"}
    finally:
        await _cleanup(seed)


def _stage(cand_id: int, job_id: int, moved_at: datetime, answers: dict):
    return CandidateStage(
        candidate_id=cand_id,
        job_id=job_id,
        stage=PipelineStage.screening,
        moved_at=moved_at,
        screening_answers=answers,
    )


@pytest.mark.asyncio
async def test_batched_scoring_matches_the_per_pair_path():
    """Hurtowy kontekst i hurtowe konflikty dają DOKŁADNIE ten sam wynik."""
    from app.services.recommendation_filters import (
        RecommendationFilters,
        apply_user_filters,
        load_active_conflicts_bulk,
    )
    from app.services.scoring_service import (
        build_jobs_scoring_contexts,
        rank_jobs_for_candidate,
    )

    seed = await _seed(n_candidates=3, n_jobs=4, ending_first=False)
    other_client_id: int | None = None
    try:
        c0, c1, c2 = seed["candidate_ids"]
        j0, j1, j2, j_closed = seed["job_ids"]
        now = datetime.now(timezone.utc).replace(microsecond=0)
        async with AsyncSessionLocal() as db:
            other = Client(name=f"PageCostOther-{uuid.uuid4().hex[:6]}")
            db.add(other)
            await db.flush()
            other_client_id = other.id
            (await db.get(Job, j_closed)).status = JobStatus.closed

            # (c0, j0): wygrać ma NOWSZY etap.
            db.add(_stage(c0, j0, now - timedelta(days=3), {"overall_fit": "fit"}))
            db.add(_stage(c0, j0, now - timedelta(days=1), {"overall_fit": "miss"}))
            # (c2, j0): remis `moved_at` — rozstrzyga WYŻSZE id.
            db.add(
                _stage(
                    c2,
                    j0,
                    now,
                    {
                        "overall_fit": "uncertain",
                        "answers": [{"question_id": "q1", "response": "tak"}],
                    },
                )
            )
            await db.flush()
            db.add(
                _stage(
                    c2,
                    j0,
                    now,
                    {
                        "overall_fit": "fit",
                        "answers": [{"question_id": "q1", "response": "tak"}],
                    },
                )
            )
            # j1: dwóch kandydatów z etapami na TEJ SAMEJ ofercie — realny
            # wynik (1 z 2 odpowiedzi, fit → 50%) i dealbreaker.
            db.add(
                _stage(
                    c1,
                    j1,
                    now,
                    {
                        "overall_fit": "fit",
                        "answers": [
                            {"question_id": "q1", "response": "tak"},
                            {"question_id": "q2", "response": ""},
                        ],
                    },
                )
            )
            db.add(
                _stage(
                    c2,
                    j1,
                    now,
                    {
                        "overall_fit": "fit",
                        "answers": [
                            {
                                "question_id": "q1",
                                "response": "nie",
                                "deal_breaker_hit": True,
                            }
                        ],
                    },
                )
            )
            # Etap na ofercie spoza przekazanej listy — nie wchodzi do kontekstu.
            db.add(_stage(c0, j_closed, now, {"overall_fit": "fit"}))
            db.add_all(
                [
                    # c1: aktywny konflikt z klientem ofert → ostrzeżenie (od
                    # 17.09.2026 bez zerowania wyniku i bez odcięcia).
                    CandidateConflict(
                        candidate_id=c1,
                        client_id=seed["client_id"],
                        type=ConflictType.nda,
                        active=True,
                    ),
                    # c2: konflikt po terminie wypada z filtrów; nieaktywny — też.
                    CandidateConflict(
                        candidate_id=c2,
                        client_id=seed["client_id"],
                        type=ConflictType.competitor,
                        active=True,
                        expires_at=now - timedelta(days=1),
                    ),
                    CandidateConflict(
                        candidate_id=c2,
                        client_id=other.id,
                        type=ConflictType.blacklist,
                        active=False,
                    ),
                    CandidateConflict(
                        candidate_id=c0,
                        client_id=other.id,
                        type=ConflictType.current_employment,
                        active=True,
                        expires_at=now + timedelta(days=30),
                    ),
                ]
            )
            await db.commit()

        async with AsyncSessionLocal() as db:
            cands = (
                (
                    await db.execute(
                        select(Candidate)
                        .where(Candidate.id.in_(seed["candidate_ids"]))
                        .order_by(Candidate.id)
                    )
                )
                .scalars()
                .all()
            )
            jobs = (
                (
                    await db.execute(
                        select(Job).where(Job.id.in_([j0, j1, j2])).order_by(Job.id)
                    )
                )
                .scalars()
                .all()
            )
            by_cand = {c.id: c for c in cands}
            # j2: oferta bez klienta — konflikt nie może dać kary. `jobs.client_id`
            # jest NOT NULL w bazie, więc taki obiekt istnieje tylko w pamięci
            # (np. oferta efemeryczna); odpinamy go od sesji, żeby nic nie zapisać.
            job_without_client = next(j for j in jobs if j.id == j2)
            db.expunge(job_without_client)
            job_without_client.client_id = None

            bulk_conflicts = await load_active_conflicts_bulk(db, list(by_cand))
            assert bulk_conflicts[c0] == {
                other_client_id: ConflictType.current_employment
            }
            assert bulk_conflicts[c1] == {seed["client_id"]: ConflictType.nda}
            assert bulk_conflicts[c2] == {}

            contexts = await build_jobs_scoring_contexts(db, jobs, list(by_cand))
            assert set(contexts) == {j0, j1, j2}
            assert j_closed not in contexts
            assert set(contexts[j1].screening_by_candidate) == {c1, c2}

            filters = RecommendationFilters()
            sims = {j.id: 0.4 for j in jobs}
            bulk_by_pair = {}
            for cand in cands:
                kept_single, stats_single = await apply_user_filters(
                    cand, jobs, filters, db
                )
                kept_bulk, stats_bulk = await apply_user_filters(
                    cand, jobs, filters, db, conflicts=bulk_conflicts[cand.id]
                )
                assert kept_bulk == kept_single and stats_bulk == stats_single

                single = await rank_jobs_for_candidate(
                    cand, jobs, db, similarity_map=sims
                )
                bulk = await rank_jobs_for_candidate(
                    cand, jobs, db, similarity_map=sims, contexts=contexts
                )
                shape = lambda rows: [  # noqa: E731
                    (
                        b.job_id,
                        round(b.total, 6),
                        b.penalties,
                        b.warnings,
                        b.champion_fit.reason,
                        round(b.champion_fit.points, 6),
                    )
                    for b in rows
                ]
                assert shape(bulk) == shape(single)
                bulk_by_pair.update({(cand.id, b.job_id): b for b in bulk})

            # Przypadki muszą naprawdę zajść, inaczej równość powyżej nic nie mówi.
            assert bulk_by_pair[(c0, j0)].champion_fit.reason.startswith("miss")
            assert bulk_by_pair[(c2, j0)].champion_fit.reason == "fit · 100%"
            assert bulk_by_pair[(c1, j1)].champion_fit.reason == "fit · 50%"
            assert bulk_by_pair[(c1, j1)].champion_fit.points > 0
            assert bulk_by_pair[(c2, j1)].champion_fit.reason == "deal-breaker"
            # 17.09.2026: konflikt z klientem to OSTRZEŻENIE — nie kara.
            assert "active_conflict" in bulk_by_pair[(c1, j0)].warnings
            assert "active_conflict" not in bulk_by_pair[(c1, j0)].penalties
            assert bulk_by_pair[(c1, j0)].total > 0
            assert "active_conflict" not in bulk_by_pair[(c1, j2)].warnings
            # Konflikt po terminie (c2 × klient ofert) nie jest ostrzeżeniem —
            # ani w kontekście hurtowym, ani na ścieżce per para (równość wyżej).
            assert "active_conflict" not in bulk_by_pair[(c2, j0)].warnings
            assert bulk_by_pair[(c0, j2)].champion_fit.reason == "brak screeningu"
    finally:
        await _cleanup(
            seed,
            extra_client_ids=(other_client_id,) if other_client_id else (),
        )
