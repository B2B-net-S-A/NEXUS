"""Warianty „wiele Tablic naraz” helperów ``build_kanban_view`` (19.11.2026).

``GET /api/pipeline/my-next-steps`` składa do 25 Tablic; każdy helper pytał
osobno o każdą rekrutację (ok. 47 zapytań na Tablicę). Warianty ``*_for_jobs``
robią tyle zapytań, ile stary helper dla jednej rekrutacji, a stary deleguje
do nowego. Tu sprawdzamy na trzech rekrutacjach: wynik hurtowy = wynik
pojedynczy dla każdej rekrutacji, dane pary spoza Tablicy nie przeciekają
i liczba zapytań nie rośnie z liczbą rekrutacji.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import event

import app.models  # noqa: F401  (zarejestruj wszystkie mappery)
from app.core.database import AsyncSessionLocal, engine
from app.core.security import hash_password
from app.models.b2b_generated_contract import B2BGeneratedContract
from app.models.candidate import Candidate
from app.models.candidate_job_owner import CandidateJobOwner
from app.models.candidate_rate_change import CandidateRateChange
from app.models.client import Client
from app.models.cv_generated_document import CvGeneratedDocument
from app.models.job import Job, JobStatus
from app.models.job_champion import JobChampion
from app.models.pair_departure_care import PairDepartureCare
from app.models.pre_contract import PreContractRequest
from app.models.recommendation_card import RecommendationCard
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User, UserRole
from app.services import (
    agreement_status,
    candidate_rate_change,
    cv_auto_review,
    departure_care,
    job_champions,
    pair_owner,
    pre_contracts,
    recommendation_cards,
)

pytestmark = pytest.mark.asyncio

T0 = datetime(2026, 11, 2, 9, 0, tzinfo=timezone.utc)


@contextmanager
def count_statements():
    seen: list[str] = []

    def _on(conn, cursor, statement, parameters, context, executemany):
        seen.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", _on)
    try:
        yield seen
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", _on)


async def _user(db, role: str, *, active: bool = True) -> User:
    tag = uuid.uuid4().hex[:8]
    user = User(
        email=f"bulk-{tag}@example.com",
        password_hash=hash_password(f"T3st_{tag}!Bulk"),
        name=f"Osoba Przykładowa {tag}",
        role=UserRole(role),
        roles=[role],
        is_active=active,
    )
    db.add(user)
    await db.flush()
    return user


async def _world() -> dict[str, Any]:
    """Trzy rekrutacje jednego klienta.

    Tablice: J0 = [c0, c1], J1 = [c0, c2], J2 = [c3]. Osoba c1 ma w J2 umowę,
    przedwstępną, kartę i stawkę na etapie, ale nie stoi na Tablicy J2 — to
    przeciek, którego wariant hurtowy nie może pokazać. J0 ma dane dla
    każdego helpera (pełny zestaw zapytań przy pomiarze).
    """
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        rec_a = await _user(db, "recruiter")
        rec_b = await _user(db, "recruiter")
        gone = await _user(db, "recruiter", active=False)
        dl = await _user(db, "delivery_lead")
        client = Client(name=f"Hurt {tag}")
        db.add(client)
        await db.flush()
        jobs = [
            Job(
                title=f"Hurt {tag} {i}", client_id=client.id, status=JobStatus.published
            )
            for i in range(3)
        ]
        db.add_all(jobs)
        cands = [Candidate(name="Jan", lastname=f"Hurt-{tag}-{i}") for i in range(4)]
        db.add_all(cands)
        await db.flush()
        j0, j1, j2 = (j.id for j in jobs)
        c0, c1, c2, c3 = (c.id for c in cands)

        def stage(cid: int, jid: int, code: PipelineStage, rate=None) -> CandidateStage:
            row = CandidateStage(
                candidate_id=cid,
                job_id=jid,
                stage=code,
                moved_by=rec_a.id,
                moved_at=T0,
                expected_rate_value=rate,
            )
            db.add(row)
            return row

        s00 = stage(c0, j0, PipelineStage.screening, Decimal("150"))
        stage(c1, j0, PipelineStage.new)
        s01 = stage(c0, j1, PipelineStage.cv_sent)
        stage(c2, j1, PipelineStage.new, Decimal("140"))
        stage(c3, j2, PipelineStage.new)
        stage(c1, j2, PipelineStage.new, Decimal("130"))
        await db.flush()

        for cid, jid, owner in (
            (c0, j0, rec_a),
            (c0, j1, rec_b),
            (c3, j2, rec_a),
            (c1, j0, gone),
            (c2, j1, gone),
        ):
            db.add(
                CandidateJobOwner(
                    candidate_id=cid,
                    job_id=jid,
                    owner_user_id=owner.id,
                    assigned_by=dl.id,
                    reason="test",
                    created_at=T0,
                    updated_at=T0,
                )
            )
        for cid, jid in ((c1, j0), (c2, j1)):
            db.add(
                PairDepartureCare(
                    candidate_id=cid,
                    job_id=jid,
                    departed_user_id=gone.id,
                    caretaker_user_id=dl.id,
                    via="job_dl",
                )
            )
        for n, (cid, jid, status) in enumerate(
            ((c0, j0, "in_progress"), (c0, j1, "active"), (c1, j2, "active"))
        ):
            db.add(
                B2BGeneratedContract(
                    candidate_id=cid,
                    job_id=jid,
                    contract_number=f"HURT/{tag}/{n}",
                    contract_status=status,
                )
            )
        for cid, jid in ((c0, j0), (c2, j1), (c1, j2)):
            db.add(
                PreContractRequest(
                    candidate_id=cid, job_id=jid, needed_before="cv_sent"
                )
            )
        db.add_all(
            [
                JobChampion(job_id=j0, candidate_id=c0, marked_at=T0),
                JobChampion(job_id=j1, candidate_id=c2, marked_at=T0),
                JobChampion(
                    job_id=j0,
                    candidate_id=c1,
                    marked_at=T0,
                    cleared_at=T0,
                    cleared_reason="manual",
                ),
            ]
        )
        for cid, jid, stage_row, status in (
            (c0, j0, s00, "ready"),
            (c0, j1, s01, "processing"),
        ):
            db.add(
                CvGeneratedDocument(
                    candidate_id=cid,
                    job_id=jid,
                    candidate_name="x",
                    language="pl",
                    mode="new",
                    content_mode="polished",
                    filename="",
                    status=status,
                    origin="auto",
                    stage_id=stage_row.id,
                )
            )
        for cid, jid, status, negotiator in (
            (c0, j0, "requested", None),
            (c0, j1, "negotiating", rec_b.id),
        ):
            db.add(
                CandidateRateChange(
                    candidate_id=cid,
                    job_id=jid,
                    requested_amount=Decimal("160"),
                    requested_unit="hour",
                    requested_hourly=Decimal("160"),
                    source="manual",
                    status=status,
                    negotiator_id=negotiator,
                    created_at=T0,
                    updated_at=T0,
                )
            )
        for cid, jid in ((c0, j0), (c0, j1), (c1, j2)):
            db.add(
                RecommendationCard(
                    candidate_id=cid,
                    job_id=jid,
                    fields_notes={"availability": {"value": "od zaraz"}},
                    fields_manual={},
                    note_answers={},
                )
            )
        await db.commit()
    return {
        "jobs": [j0, j1, j2],
        "boards": {j0: [c0, c1], j1: [c0, c2], j2: [c3]},
        "c": [c0, c1, c2, c3],
    }


def _started(boards: dict[int, list[int]]) -> dict[int, dict[int, Any]]:
    return {
        job: {cid: T0 - timedelta(days=1) for cid in ids} for job, ids in boards.items()
    }


async def _bulk(db, jobs: list[int], boards: dict[int, list[int]]) -> dict[str, Any]:
    """Wszystkie warianty hurtowe dla podanych rekrutacji."""
    sub = {job: boards[job] for job in jobs}
    care = await departure_care.open_care(db, job_ids=jobs)
    return {
        "owners": await pair_owner.owners_for_jobs(db, jobs),
        "care": {job: [r for r in care if r.job_id == job] for job in jobs},
        "agreements": await agreement_status.agreement_status_for_jobs(db, boards=sub),
        "pre_contracts": await pre_contracts.kanban_badges_for_jobs(db, sub),
        "champions": await job_champions.live_candidate_ids_for_jobs(db, jobs),
        "auto_cv": await cv_auto_review.job_stages_auto_cv_for_jobs(
            db, jobs, with_processing=True
        ),
        "rate_changes": await candidate_rate_change.open_badges_for_jobs(
            db, job_ids=jobs
        ),
        "cards": await recommendation_cards.summaries_for_jobs(
            db, started_by_job=_started(sub)
        ),
    }


async def _single(db, job: int, ids: list[int]) -> dict[str, Any]:
    """Stare helpery jednej rekrutacji — ten sam kształt co ``_bulk[...][job]``."""
    return {
        "owners": await pair_owner.owners_for_job(db, job),
        "care": await departure_care.open_care(db, job_id=job),
        "agreements": await agreement_status.agreement_status_for_pairs(
            db, job_id=job, candidate_ids=ids
        ),
        "pre_contracts": await pre_contracts.kanban_badges(db, job, ids),
        "champions": await job_champions.live_candidate_ids(db, job),
        "auto_cv": await cv_auto_review.job_stages_auto_cv(
            db, job, with_processing=True
        ),
        "rate_changes": await candidate_rate_change.open_badges_for_job(db, job_id=job),
        "cards": await recommendation_cards.summaries_for_job(
            db, job_id=job, started_by_candidate=_started({job: ids})[job]
        ),
    }


async def test_bulk_equals_single_board_for_every_job():
    world = await _world()
    jobs, boards = world["jobs"], world["boards"]
    async with AsyncSessionLocal() as db:
        bulk = await _bulk(db, jobs, boards)
        for job in jobs:
            single = await _single(db, job, boards[job])
            for name, value in single.items():
                assert bulk[name][job] == value, (name, job)


async def test_seeded_data_lands_on_its_own_board_only():
    world = await _world()
    jobs, boards = world["jobs"], world["boards"]
    j0, j1, j2 = jobs
    c0, c1, c2, c3 = world["c"]
    async with AsyncSessionLocal() as db:
        bulk = await _bulk(db, jobs, boards)
    # Każda rekrutacja z wejścia ma klucz, także bez danych.
    for name, by_job in bulk.items():
        assert set(by_job) == set(jobs), name
    assert set(bulk["owners"][j0]) == {c0, c1}
    assert set(bulk["owners"][j1]) == {c0, c2}
    assert bulk["owners"][j0][c0].owner_user_id != bulk["owners"][j1][c0].owner_user_id
    assert [(r.candidate_id, r.job_id) for r in bulk["care"][j0]] == [(c1, j0)]
    assert [(r.candidate_id, r.job_id) for r in bulk["care"][j1]] == [(c2, j1)]
    assert bulk["care"][j2] == []
    assert bulk["agreements"][j0][c0]["contract_status"] == "in_progress"
    assert bulk["agreements"][j1][c0]["contract_status"] == "active"
    # c1 ma umowę, przedwstępną i kartę w J2, ale nie stoi na Tablicy J2.
    assert bulk["agreements"][j2] == {}
    assert set(bulk["pre_contracts"][j0]) == {c0}
    assert set(bulk["pre_contracts"][j1]) == {c2}
    assert bulk["pre_contracts"][j2] == {}
    assert bulk["champions"] == {j0: {c0}, j1: {c2}, j2: set()}
    ready0, processing0 = bulk["auto_cv"][j0]
    ready1, processing1 = bulk["auto_cv"][j1]
    assert len(ready0) == 1 and processing0 == set()
    assert ready1 == set() and len(processing1) == 1
    assert bulk["auto_cv"][j2] == (set(), set())
    assert bulk["rate_changes"][j0][c0]["status"] == "requested"
    assert bulk["rate_changes"][j1][c0]["status"] == "negotiating"
    assert bulk["rate_changes"][j2] == {}
    # J0: c0 ma kartę i stawkę; J1: c0 kartę, c2 samą stawkę na etapie.
    assert set(bulk["cards"][j0]) == {c0}
    assert set(bulk["cards"][j1]) == {c0, c2}
    assert bulk["cards"][j2] == {}


async def test_empty_input_gives_empty_results_without_queries():
    world = await _world()
    j0 = world["jobs"][0]
    async with AsyncSessionLocal() as db:
        with count_statements() as seen:
            assert await departure_care.open_care(db, job_ids=[]) == []
            assert await pair_owner.owners_for_jobs(db, []) == {}
            assert await agreement_status.agreement_status_for_jobs(
                db, boards={j0: []}
            ) == {j0: {}}
            assert await pre_contracts.kanban_badges_for_jobs(db, {j0: []}) == {j0: {}}
            assert await job_champions.live_candidate_ids_for_jobs(db, []) == {}
            assert (
                await cv_auto_review.job_stages_auto_cv_for_jobs(
                    db, [], with_processing=True
                )
                == {}
            )
            assert (
                await candidate_rate_change.open_badges_for_jobs(db, job_ids=[]) == {}
            )
            assert await recommendation_cards.summaries_for_jobs(
                db, started_by_job={j0: {}}
            ) == {j0: {}}
    assert seen == []


async def test_query_count_does_not_grow_with_job_count():
    world = await _world()
    jobs, boards = world["jobs"], world["boards"]
    j0 = jobs[0]
    async with AsyncSessionLocal() as db:
        # Rozgrzewka: pierwsze wywołanie procesu może czytać ustawienia.
        await _bulk(db, jobs, boards)
        with count_statements() as single_seen:
            await _single(db, j0, boards[j0])
        with count_statements() as one_seen:
            await _bulk(db, [j0], boards)
        with count_statements() as three_seen:
            await _bulk(db, jobs, boards)
    print(
        f"zapytania: stare dla J0={len(single_seen)}, "
        f"hurt 1 rekrutacja={len(one_seen)}, hurt 3 rekrutacje={len(three_seen)}"
    )
    assert len(one_seen) == len(single_seen), (len(single_seen), len(one_seen))
    assert len(three_seen) == len(one_seen), (len(one_seen), len(three_seen))
