"""Termin rozmowy i start współpracy pary (`client_interview_terms`, 09.11.2026)."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest

from app.core.database import AsyncSessionLocal
from app.models.calendar_event import CalendarEvent, EventStatus, EventType
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_interview_slot_request import ClientInterviewSlotRequest
from app.models.contract import Contract, ContractStatus
from app.models.job import Job, JobStatus, RemotePolicy
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.services.client_interview_terms import PairTerms, load_pair_terms, term_from

_TODAY = date(2058, 5, 10)


def _at(day: int, hour: int = 12) -> datetime:
    return datetime(2058, 5, day, hour, 0, tzinfo=timezone.utc)


async def _pair() -> tuple[int, int, int]:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Terminy-{tag}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"Terminy {tag}",
            location="Warszawa",
            status=JobStatus.published,
            remote_policy=RemotePolicy.hybrid,
            client_id=client.id,
        )
        candidate = Candidate(
            name="Termin", lastname=f"Test-{tag}", email=f"terminy-{tag}@example.com"
        )
        db.add_all([job, candidate])
        await db.commit()
        return candidate.id, job.id, client.id


def _interview(
    candidate_id: int, job_id: int, start: datetime, **kwargs
) -> CalendarEvent:
    return CalendarEvent(
        title="Rozmowa u klienta",
        event_type=kwargs.pop("event_type", EventType.client_interview),
        start_time=start,
        candidate_id=candidate_id,
        job_id=job_id,
        **kwargs,
    )


async def _terms(candidate_id: int, job_id: int) -> PairTerms:
    async with AsyncSessionLocal() as db:
        found = await load_pair_terms(db, [(candidate_id, job_id)], today=_TODAY)
    return found[(candidate_id, job_id)]


def test_term_boundary_is_midnight_in_the_company_calendar() -> None:
    assert term_from(date(2026, 11, 9)).astimezone(timezone.utc) == datetime(
        2026, 11, 8, 23, 0, tzinfo=timezone.utc
    )


@pytest.mark.asyncio
async def test_no_pairs_skip_the_query() -> None:
    assert await load_pair_terms(None, [], today=_TODAY) == {}  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_nearest_upcoming_round_wins_over_earlier_and_later_ones() -> None:
    candidate_id, job_id, _ = await _pair()
    async with AsyncSessionLocal() as db:
        db.add_all(
            [
                _interview(candidate_id, job_id, _at(2)),
                _interview(candidate_id, job_id, _at(20)),
                _interview(candidate_id, job_id, _at(15)),
            ]
        )
        await db.commit()

    terms = await _terms(candidate_id, job_id)

    assert terms.next_at == _at(15)
    assert terms.last_at == _at(2)
    assert terms.interview_at == _at(15)


@pytest.mark.asyncio
async def test_only_past_rounds_show_the_latest_one() -> None:
    candidate_id, job_id, _ = await _pair()
    async with AsyncSessionLocal() as db:
        db.add_all(
            [
                _interview(candidate_id, job_id, _at(1)),
                _interview(candidate_id, job_id, _at(5)),
            ]
        )
        await db.commit()

    terms = await _terms(candidate_id, job_id)

    assert terms.next_at is None
    assert terms.interview_at == _at(5)


@pytest.mark.asyncio
async def test_this_mornings_interview_still_counts_as_upcoming() -> None:
    candidate_id, job_id, _ = await _pair()
    async with AsyncSessionLocal() as db:
        db.add(_interview(candidate_id, job_id, _at(10, 6)))
        await db.commit()

    assert (await _terms(candidate_id, job_id)).next_at == _at(10, 6)


@pytest.mark.asyncio
async def test_cancelled_rounds_and_prep_calls_are_not_interviews() -> None:
    candidate_id, job_id, _ = await _pair()
    async with AsyncSessionLocal() as db:
        db.add_all(
            [
                _interview(candidate_id, job_id, _at(15), status=EventStatus.cancelled),
                _interview(
                    candidate_id, job_id, _at(16), event_type=EventType.prep_call
                ),
            ]
        )
        await db.commit()

    assert (await _terms(candidate_id, job_id)).interview_at is None


def _slots(*days: int) -> list[dict[str, str]]:
    return [
        {
            "start": _at(day).isoformat(),
            "end": (_at(day) + timedelta(hours=1)).isoformat(),
        }
        for day in days
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "chosen_index", "days", "expected"),
    [
        ("awaiting_recruiter", None, (20, 12, 3), 12),
        ("awaiting_dl", 0, (20, 12), 20),
        ("awaiting_dl", 1, (20, 12), 12),
        ("awaiting_recruiter", None, (2, 3), None),
        ("cancelled", None, (20,), None),
    ],
)
async def test_open_request_gives_a_tentative_term(
    status: str, chosen_index: int | None, days: tuple[int, ...], expected: int | None
) -> None:
    candidate_id, job_id, _ = await _pair()
    async with AsyncSessionLocal() as db:
        db.add(
            ClientInterviewSlotRequest(
                candidate_id=candidate_id,
                job_id=job_id,
                slots=_slots(*days),
                status=status,
                chosen_index=chosen_index,
            )
        )
        await db.commit()

    terms = await _terms(candidate_id, job_id)

    assert terms.tentative_at == (_at(expected) if expected else None)


async def _add_start_data(
    candidate_id: int, job_id: int, client_id: int, contract_status: ContractStatus
) -> None:
    async with AsyncSessionLocal() as db:
        db.add_all(
            [
                Contract(
                    candidate_id=candidate_id,
                    job_id=job_id,
                    client_id=client_id,
                    start_date=date(2058, 7, 1),
                    status=contract_status,
                ),
                CandidateStage(
                    candidate_id=candidate_id,
                    job_id=job_id,
                    stage=PipelineStage.acceptance,
                    moved_at=_at(1),
                    client_accepted_on=date(2058, 5, 1),
                    planned_start_on=date(2058, 6, 15),
                ),
            ]
        )
        await db.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("contract_status", "expected"),
    [
        (ContractStatus.active, date(2058, 7, 1)),
        (ContractStatus.void, date(2058, 6, 15)),
    ],
)
async def test_start_comes_from_a_live_contract_then_the_planned_start(
    contract_status: ContractStatus, expected: date
) -> None:
    candidate_id, job_id, client_id = await _pair()
    await _add_start_data(candidate_id, job_id, client_id, contract_status)

    assert (await _terms(candidate_id, job_id)).start_on == expected


@pytest.mark.asyncio
async def test_planned_start_comes_from_the_newest_dated_acceptance_like_the_board() -> (
    None
):
    candidate_id, job_id, _ = await _pair()
    async with AsyncSessionLocal() as db:
        db.add_all(
            [
                CandidateStage(
                    candidate_id=candidate_id,
                    job_id=job_id,
                    stage=PipelineStage.acceptance,
                    moved_at=_at(1),
                    client_accepted_on=date(2058, 5, 1),
                    planned_start_on=date(2058, 7, 1),
                ),
                CandidateStage(
                    candidate_id=candidate_id,
                    job_id=job_id,
                    stage=PipelineStage.acceptance,
                    moved_at=_at(5),
                    client_accepted_on=date(2058, 5, 5),
                    planned_start_on=date(2058, 6, 15),
                ),
            ]
        )
        await db.commit()

    assert (await _terms(candidate_id, job_id)).start_on == date(2058, 6, 15)


@pytest.mark.asyncio
async def test_pair_with_nothing_has_empty_terms() -> None:
    candidate_id, job_id, _ = await _pair()

    assert await _terms(candidate_id, job_id) == PairTerms()
