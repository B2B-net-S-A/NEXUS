"""Punkty kolejki, sygnały, odznaki i telefony dla wielu Tablic (19.11.2026).

``GET /api/pipeline/my-next-steps`` składa do 25 Tablic. Każdy ``X_for_jobs``
(``known_queue_points``, ``review_batch_order``, ``interview_cycle``,
``screening_calls``) musi dać dla rekrutacji to samo, co stary ``X`` dla
jednej Tablicy, nie przepuścić pary z innej Tablicy i mieć tyle samo zapytań
dla 1 i dla 3 rekrutacji.
"""

import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import event

import app.models  # noqa: F401
from app.core.config import settings
from app.core.database import AsyncSessionLocal, engine
from app.core.security import hash_password
from app.models.calendar_event import (
    BOOKED_CALL_LOCATION,
    CalendarEvent,
    EventStatus,
    EventType,
)
from app.models.candidate import Candidate, CandidateStatus
from app.models.client import Client
from app.models.client_interview_slot_request import ClientInterviewSlotRequest
from app.models.job import Job, JobStatus
from app.models.note import Note
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User, UserRole
from app.services import interview_cycle, review_batch_order, screening_calls
from app.services import known_queue_points as known

pytestmark = pytest.mark.asyncio


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


async def _world() -> dict:
    """Rekrutacje A i B u jednego klienta, C u innego, „earlier” — wcześniejsza A.

    Osoby: ``x`` (Tablica A i B), ``y`` (Tablica B), ``z`` (Tablica C),
    ``w`` (Tablica A i C)."""
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"bulk-{tag}@example.com",
            password_hash=hash_password(f"Bulk_{tag}!pw"),
            name=f"Bulk {tag}",
            role=UserRole.recruiter,
            roles=[UserRole.recruiter.value],
            is_active=True,
            profile_completed=True,
        )
        client = Client(name=f"Bulk client {tag}")
        other = Client(name=f"Bulk other {tag}")
        db.add_all([user, client, other])
        await db.flush()
        jobs = {
            "a": Job(
                title=f"Bulk A {tag}", client_id=client.id, status=JobStatus.published
            ),
            "b": Job(
                title=f"Team Lead B {tag}",
                client_id=client.id,
                status=JobStatus.published,
                champion_profile={"basics": {"language": "English only"}},
            ),
            "c": Job(
                title=f"Bulk C {tag}", client_id=other.id, status=JobStatus.closed
            ),
            "earlier": Job(
                title=f"Bulk earlier {tag}",
                client_id=client.id,
                status=JobStatus.closed,
            ),
        }
        people = {
            key: Candidate(
                name=name,
                lastname=f"{lastname}-{tag}",
                status=CandidateStatus.active,
                cv_language=lang,
            )
            for key, name, lastname, lang in (
                ("x", "Anna", "Kowalska", None),
                ("y", "John", "Smith", None),
                ("z", "Ewa", "Nowak", "pl"),
                ("w", "Mark", "Brown", "en"),
            )
        }
        db.add_all([*jobs.values(), *people.values()])
        await db.commit()
        return {
            "user": user.id,
            "client": client.id,
            "other": other.id,
            "jobs": {k: j.id for k, j in jobs.items()},
            "ids": {k: p.id for k, p in people.items()},
        }


def _boards(w: dict) -> dict[int, list[int]]:
    i, j = w["ids"], w["jobs"]
    return {
        j["a"]: [i["x"], i["w"]],
        j["b"]: [i["x"], i["y"]],
        j["c"]: [i["z"], i["w"]],
    }


async def _add(*rows) -> None:
    async with AsyncSessionLocal() as db:
        db.add_all(list(rows))
        await db.commit()


# ── known_queue_points ─────────────────────────────────────────────────────


async def _seed_known(w: dict) -> None:
    i, j = w["ids"], w["jobs"]
    now = datetime.now(timezone.utc)
    await _add(
        # x zweryfikowany w B: punkty klienta na Tablicy A, na B już nie (własna).
        CandidateStage(
            candidate_id=i["x"], job_id=j["b"], stage=PipelineStage.verified
        ),
        Note(
            candidate_id=i["x"], content="Rozmowa", created_at=now - timedelta(days=3)
        ),
        # w odrzucony przez klienta we wcześniejszej rekrutacji: znika z A, nie z C.
        CandidateStage(
            candidate_id=i["w"], job_id=j["earlier"], stage=PipelineStage.cv_sent
        ),
        Note(
            candidate_id=i["w"], content="Rozmowa", created_at=now - timedelta(days=40)
        ),
        # y z procesem tylko w B; z z procesem w C i we wcześniejszej.
        CandidateStage(candidate_id=i["y"], job_id=j["b"], stage=PipelineStage.new),
        CandidateStage(candidate_id=i["z"], job_id=j["c"], stage=PipelineStage.new),
        CandidateStage(
            candidate_id=i["z"], job_id=j["earlier"], stage=PipelineStage.new
        ),
    )
    await _add(
        CandidateStage(
            candidate_id=i["w"],
            job_id=j["earlier"],
            stage=PipelineStage.rejected,
            ended_by="client",
        )
    )


def _known_boards(w: dict) -> dict[int, tuple[int, list[int]]]:
    j = w["jobs"]
    clients = {j["a"]: w["client"], j["b"]: w["client"], j["c"]: w["other"]}
    return {job_id: (clients[job_id], ids) for job_id, ids in _boards(w).items()}


async def test_facts_for_jobs_match_single_board_and_count_per_job():
    w = await _world()
    await _seed_known(w)
    i, j = w["ids"], w["jobs"]
    boards = _known_boards(w)
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        bulk = await known.facts_for_jobs(db, boards=boards, now=now)
        single = {
            job_id: await known.facts_for(
                db, job_id=job_id, client_id=client, candidate_ids=ids, now=now
            )
            for job_id, (client, ids) in boards.items()
        }
    assert bulk == single
    assert set(bulk[j["a"]]) == {i["x"]}
    assert bulk[j["a"]][i["x"]].verified_at_client == 1
    # Ta sama osoba na Tablicy B: weryfikacja w B to jej własna rekrutacja.
    assert bulk[j["b"]][i["x"]].verified_at_client == 0
    assert bulk[j["b"]][i["x"]].points == 8
    # Odrzucenie przez klienta A nie dotyczy Tablicy C innego klienta.
    assert set(bulk[j["c"]]) == {i["w"]}
    assert bulk[j["c"]][i["w"]].points == 2
    async with AsyncSessionLocal() as db:
        empty = await known.facts_for_jobs(
            db, boards={j["a"]: (w["client"], []), j["c"]: (None, [i["z"]])}, now=now
        )
    assert empty == {j["a"]: {}, j["c"]: {}}


async def test_facts_for_jobs_query_count_does_not_grow():
    w = await _world()
    await _seed_known(w)
    boards = _known_boards(w)
    first = next(iter(boards))
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        with count_statements() as one:
            await known.facts_for_jobs(db, boards={first: boards[first]}, now=now)
    async with AsyncSessionLocal() as db:
        with count_statements() as three:
            await known.facts_for_jobs(db, boards=boards, now=now)
    assert len(one) == len(three) == 4


async def test_without_process_for_jobs_excludes_only_own_board():
    w = await _world()
    await _seed_known(w)
    i, j = w["ids"], w["jobs"]
    boards = _boards(w)
    async with AsyncSessionLocal() as db:
        bulk = await known.without_process_for_jobs(db, boards=boards)
        single = {
            job_id: await known.without_process(db, job_id=job_id, candidate_ids=ids)
            for job_id, ids in boards.items()
        }
        with count_statements() as one:
            await known.without_process_for_jobs(db, boards={j["a"]: boards[j["a"]]})
        with count_statements() as three:
            await known.without_process_for_jobs(db, boards=boards)
    assert bulk == single
    # x i y mają wiersze tylko w B: na B bez procesu, na A x już z procesem.
    assert bulk[j["b"]] == {i["x"], i["y"]}
    assert bulk[j["a"]] == set()
    assert bulk[j["c"]] == set()
    assert len(one) == len(three) == 1


# ── review_batch_order ─────────────────────────────────────────────────────


async def test_order_signals_for_jobs_match_single_board(monkeypatch):
    monkeypatch.setattr(settings, "REVIEW_BATCH_ENABLED", True, raising=False)
    w = await _world()
    i, j = w["ids"], w["jobs"]
    async with AsyncSessionLocal() as db:
        jobs = {job_id: await db.get(Job, job_id) for job_id in _boards(w)}
        boards = {job_id: (jobs[job_id], ids) for job_id, ids in _boards(w).items()}
        bulk = await review_batch_order.order_signals_for_jobs(db, boards)
        single = {
            job_id: await review_batch_order.order_signals_for_ids(db, job, ids)
            for job_id, (job, ids) in boards.items()
        }
        with count_statements() as one:
            await review_batch_order.order_signals_for_jobs(
                db, {j["a"]: boards[j["a"]]}
            )
        with count_statements() as three:
            await review_batch_order.order_signals_for_jobs(db, boards)
    assert bulk == single
    assert set(bulk[j["a"]]) == {i["x"], i["w"]}
    assert set(bulk[j["b"]]) == {i["x"], i["y"]}
    # B nie wymaga polskiego: wszyscy „native”; na A ta sama osoba ma swój stan.
    assert bulk[j["b"]][i["y"]][0] == "native"
    assert bulk[j["a"]][i["w"]][0] == "unknown"
    assert len(one) == len(three) == 3


async def test_order_signals_for_jobs_off_or_without_job(monkeypatch):
    monkeypatch.setattr(settings, "REVIEW_BATCH_ENABLED", False, raising=False)
    w = await _world()
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, w["jobs"]["a"])
        assert await review_batch_order.order_signals_for_jobs(
            db, {job.id: (job, [w["ids"]["x"]])}
        ) == {job.id: {}}
        monkeypatch.setattr(settings, "REVIEW_BATCH_ENABLED", True, raising=False)
        assert await review_batch_order.order_signals_for_ids(db, None, [1]) == {}
        assert await review_batch_order.order_signals_for_jobs(
            db, {job.id: (job, [])}
        ) == {job.id: {}}


# ── interview_cycle ────────────────────────────────────────────────────────


async def _seed_interviews(w: dict) -> None:
    i, j, user = w["ids"], w["jobs"], w["user"]
    now = datetime.now(timezone.utc)

    def interview(cid: int, job_id: int, days: int) -> CalendarEvent:
        return CalendarEvent(
            title="Rozmowa u klienta",
            event_type=EventType.client_interview,
            start_time=now + timedelta(days=days),
            end_time=now + timedelta(days=days, hours=1),
            created_by=user,
            candidate_id=cid,
            job_id=job_id,
        )

    await _add(
        interview(i["x"], j["a"], 5),
        interview(i["x"], j["b"], 2),
        # y ma rozmowę w A, ale na Tablicy A go nie ma — nie może przeciec.
        interview(i["y"], j["a"], 3),
        interview(i["z"], j["c"], 4),
        ClientInterviewSlotRequest(
            candidate_id=i["y"],
            job_id=j["b"],
            created_by=user,
            recruiter_id=user,
            slots=[
                {
                    "start": (now + timedelta(days=3)).isoformat(),
                    "end": (now + timedelta(days=3, hours=1)).isoformat(),
                },
            ],
            duration_minutes=60,
        ),
    )


async def test_interview_badges_for_jobs_match_single_board():
    w = await _world()
    await _seed_interviews(w)
    i, j = w["ids"], w["jobs"]
    boards = _boards(w)
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        bulk = await interview_cycle.interview_badges_for_jobs(
            db, boards=boards, now=now
        )
        single = {
            job_id: await interview_cycle.interview_badges_for_job(
                db, job_id=job_id, candidate_ids=ids, now=now
            )
            for job_id, ids in boards.items()
        }
    assert bulk == single
    assert set(bulk[j["a"]]) == {i["x"]}
    assert set(bulk[j["b"]]) == {i["x"], i["y"]}
    assert bulk[j["b"]][i["y"]]["kind"] == "choose_slot"
    # Ta sama osoba w dwóch rekrutacjach: każda Tablica ma swoją rozmowę.
    assert (
        bulk[j["a"]][i["x"]]["interview_event_id"]
        != bulk[j["b"]][i["x"]]["interview_event_id"]
    )
    # Zamknięta C (stan czytany z bazy, gdy ``closed_job_ids=None``) — jak dziś.
    assert set(bulk[j["c"]]) == {i["z"]}


async def test_interview_badges_for_jobs_with_board_state_and_query_count():
    w = await _world()
    await _seed_interviews(w)
    j = w["jobs"]
    boards = _boards(w)
    now = datetime.now(timezone.utc)
    latest = {
        (cid, job_id): (PipelineStage.client_interview, now)
        for job_id, ids in boards.items()
        for cid in ids
    }
    async with AsyncSessionLocal() as db:
        bulk = await interview_cycle.interview_badges_for_jobs(
            db, boards=boards, now=now, latest_stages=latest, closed_job_ids={j["c"]}
        )
        single = {
            job_id: await interview_cycle.interview_badges_for_job(
                db,
                job_id=job_id,
                candidate_ids=ids,
                now=now,
                latest_stages={k: v for k, v in latest.items() if k[1] == job_id},
                job_closed=job_id == j["c"],
            )
            for job_id, ids in boards.items()
        }
        assert bulk == single
        with count_statements() as one:
            await interview_cycle.interview_badges_for_jobs(
                db, boards={j["a"]: boards[j["a"]]}, now=now
            )
        with count_statements() as three:
            await interview_cycle.interview_badges_for_jobs(db, boards=boards, now=now)
        assert await interview_cycle.interview_badges_for_jobs(
            db, boards={j["a"]: []}
        ) == {j["a"]: {}}
    assert len(one) == len(three) == 8


# ── screening_calls ────────────────────────────────────────────────────────


async def test_starts_by_candidate_for_jobs_match_single_board():
    w = await _world()
    i, j, user = w["ids"], w["jobs"], w["user"]
    now = datetime.now(timezone.utc)

    def call(cid: int, job_id: int, *, status=EventStatus.scheduled) -> CalendarEvent:
        return CalendarEvent(
            title="Telefon",
            event_type=EventType.screening,
            location=BOOKED_CALL_LOCATION,
            operational_owner_id=user,
            status=status,
            start_time=now + timedelta(days=1),
            end_time=now + timedelta(days=1, minutes=15),
            created_by=user,
            candidate_id=cid,
            job_id=job_id,
        )

    await _add(
        call(i["x"], j["a"]),
        call(i["x"], j["b"]),
        # y ma telefon w A, ale na Tablicy A go nie ma.
        call(i["y"], j["a"]),
        call(i["z"], j["c"], status=EventStatus.cancelled),
    )
    boards = _boards(w)
    async with AsyncSessionLocal() as db:
        bulk = await screening_calls.starts_by_candidate_for_jobs(db, boards)
        single = {
            job_id: await screening_calls.starts_by_candidate(db, job_id, ids)
            for job_id, ids in boards.items()
        }
        with count_statements() as one:
            await screening_calls.starts_by_candidate_for_jobs(
                db, {j["a"]: boards[j["a"]]}
            )
        with count_statements() as three:
            await screening_calls.starts_by_candidate_for_jobs(db, boards)
    assert {k: {c: e.id for c, e in v.items()} for k, v in bulk.items()} == {
        k: {c: e.id for c, e in v.items()} for k, v in single.items()
    }
    assert set(bulk[j["a"]]) == {i["x"]}
    assert set(bulk[j["b"]]) == {i["x"]}
    assert bulk[j["a"]][i["x"]].job_id == j["a"]
    assert bulk[j["b"]][i["x"]].job_id == j["b"]
    assert bulk[j["c"]] == {}
    assert len(one) == len(three) == 1
