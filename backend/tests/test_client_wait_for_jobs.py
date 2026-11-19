"""Zegary „Klient milczy” wielu Tablic naraz (`client_clocks_for_jobs_safely`).

Ta sama osoba bywa u klienta w dwóch rekrutacjach: rozmowa, wniosek o terminy
i „Klient odpowiedział” jednej rekrutacji nie mogą przestawić zegara drugiej.
Osoby i firmy są zmyślone.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlalchemy import event

import app.models  # noqa: F401  (rejestracja wszystkich mapperów)
from app.core.database import AsyncSessionLocal, engine
from app.models.calendar_event import CalendarEvent, EventType
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.services import client_wait


def _now() -> datetime:
    return datetime.now(timezone.utc)


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


async def _seed() -> dict:
    """``both`` czeka w A i B od 20 dni; ``internal`` jest w A na screeningu.

    W A: „Klient odpowiedział” dla ``both`` 2 dni temu. W B: rozmowa
    u klienta ``both`` jutro (pauza). ``quiet`` — rekrutacja bez kart u klienta.
    """
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Cisza-{tag}")
        db.add(client)
        await db.flush()
        jobs = [
            Job(title=f"{label}-{tag}", status=JobStatus.published, client_id=client.id)
            for label in ("A", "B", "quiet")
        ]
        both = Candidate(
            name="Ola", lastname=f"Both-{tag}", email=f"b-{tag}@example.com"
        )
        internal = Candidate(
            name="Iza", lastname=f"Int-{tag}", email=f"i-{tag}@example.com"
        )
        db.add_all([*jobs, both, internal])
        await db.flush()
        job_a, job_b, quiet = jobs
        long_ago = _now() - timedelta(days=20)
        db.add_all(
            [
                CandidateStage(
                    candidate_id=both.id,
                    job_id=job_a.id,
                    stage=PipelineStage.cv_sent,
                    moved_at=long_ago,
                ),
                CandidateStage(
                    candidate_id=both.id,
                    job_id=job_b.id,
                    stage=PipelineStage.cv_sent,
                    moved_at=long_ago,
                ),
                CandidateStage(
                    candidate_id=internal.id,
                    job_id=job_a.id,
                    stage=PipelineStage.screening,
                    moved_at=long_ago,
                ),
                CalendarEvent(
                    title=f"Rozmowa-{tag}",
                    event_type=EventType.client_interview,
                    start_time=_now() + timedelta(days=1),
                    candidate_id=both.id,
                    job_id=job_b.id,
                ),
            ]
        )
        await db.flush()
        client_wait.mark(
            db, job_a.id, client_wait.ACTION_RESPONDED, [both.id], user_id=None
        )
        await db.flush()
        await db.commit()
        return {
            "a": job_a.id,
            "b": job_b.id,
            "quiet": quiet.id,
            "both": both.id,
            "internal": internal.id,
        }


async def _jobs(db, ids: list[int]) -> list[Job]:
    return [await db.get(Job, job_id) for job_id in ids]


async def test_each_job_gets_exactly_what_the_single_call_gives():
    w = await _seed()
    async with AsyncSessionLocal() as db:
        jobs = await _jobs(db, [w["a"], w["b"], w["quiet"]])
        bulk = await client_wait.client_clocks_for_jobs_safely(db, jobs)
        assert set(bulk) == {w["a"], w["b"], w["quiet"]}
        for job in jobs:
            assert bulk[job.id] == await client_wait.client_clocks_safely(db, job)

    a, b = bulk[w["a"]], bulk[w["b"]]
    # Karta wewnętrzna nie ma zegara; rekrutacja bez kart — pusty wynik.
    assert set(a) == {w["both"]} and set(b) == {w["both"]}
    assert bulk[w["quiet"]] == {}
    # „Klient odpowiedział” w A przestawia zegar tylko w A…
    assert a[w["both"]].since > b[w["both"]].since
    assert a[w["both"]].silent_workdays is None
    # …a rozmowa przed nami w B pauzuje tylko B (zegar B dalej od wejścia).
    assert b[w["both"]].silent_workdays is None
    assert b[w["both"]].since <= _now() - timedelta(days=19)


async def test_failure_empties_every_board_and_logs_once():
    w = await _seed()
    async with AsyncSessionLocal() as db:
        jobs = await _jobs(db, [w["a"], w["b"]])
        with (
            patch.object(
                client_wait, "client_clocks_for_jobs", side_effect=RuntimeError("x")
            ),
            patch.object(client_wait, "logger") as log,
        ):
            out = await client_wait.client_clocks_for_jobs_safely(db, jobs)
    assert out == {w["a"]: {}, w["b"]: {}}
    log.exception.assert_called_once()
    assert log.exception.call_args.args[1] == f"{w['a']}, {w['b']}"


async def test_query_count_does_not_grow_with_jobs():
    w = await _seed()
    async with AsyncSessionLocal() as db:
        jobs = await _jobs(db, [w["a"], w["b"], w["quiet"]])
        with count_statements() as one:
            await client_wait.client_clocks_for_jobs_safely(db, jobs[:1])
        with count_statements() as three:
            await client_wait.client_clocks_for_jobs_safely(db, jobs)
    # SAVEPOINT, karty u klienta, rozmowy, wnioski o terminy, znaczniki, RELEASE.
    assert len(one) == 6, one
    assert len(three) == len(one), (len(one), len(three))
