"""Powrót osoby do tej samej rekrutacji a pola karty (28.10.2026).

Zgłoszenie: kandydat odrzucony „Za wysokie oczekiwania finansowe” i dodany
ponownie 17 h później trafił do Cpro z pustymi warunkami („Brakuje pól: 9”),
choć odpowiedzi na pytania przeszły. Decyzja Artura (wariant A): próba otwarta
nie później niż 30 dni po zamknięciu poprzedniej to ta sama rozmowa — pola
karty liczą się dalej, tak jak arkusz (``screening_window``).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.services import recommendation_card_rules as rules
from app.services import recommendation_cards as cards

OPENED = datetime(2026, 10, 27, 9, 27, tzinfo=timezone.utc)
FIRST_OPENED = datetime(2026, 10, 26, 14, 17, tzinfo=timezone.utc)


def _process(**overrides):
    values = {
        "attempt_no": 2,
        "opened_at": OPENED,
        "created_at": OPENED,
        "previous_closed_at": OPENED - timedelta(hours=17),
        "previous_opened_at": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_first_attempt_counts_everything():
    assert cards.attempt_started(_process(attempt_no=1)) is None


def test_quick_return_after_first_attempt_keeps_its_fields():
    assert cards.attempt_started(_process()) is None


def test_quick_return_after_later_attempt_starts_at_that_attempt():
    earlier = OPENED - timedelta(days=3)
    process = _process(attempt_no=3, previous_opened_at=earlier)
    assert cards.attempt_started(process) == earlier


def test_return_after_more_than_30_days_is_a_new_conversation():
    process = _process(previous_closed_at=OPENED - timedelta(days=30, minutes=1))
    assert cards.attempt_started(process) == OPENED


def test_return_exactly_30_days_later_still_carries():
    process = _process(previous_closed_at=OPENED - timedelta(days=30))
    assert cards.attempt_started(process) is None


def test_unknown_previous_process_keeps_the_old_rule():
    assert cards.attempt_started(_process(previous_closed_at=None)) == OPENED


def test_card_fields_from_the_first_attempt_are_current_after_quick_return():
    manual = {
        "location": {"raw": "Warszawa", "at": "2026-10-26T15:03:24+00:00", "by": 101},
        "english": {"raw": "B2", "at": "2026-10-26T15:03:24+00:00", "by": 101},
    }
    current, previous = rules.split_fields(
        {}, manual, attempt_started=cards.attempt_started(_process())
    )
    assert set(current) == {"location", "english"}
    assert previous == {}


# ── Na bazie: kolumny poprzedniej próby ładują się z procesem ──────────────


@pytest.mark.asyncio
async def test_previous_attempt_columns_load_with_the_process(app_client):
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate, CandidateStatus
    from app.models.client import Client
    from app.models.job import Job, JobStatus
    from app.models.recruitment_process import ProcessStatus, RecruitmentProcess

    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        cli = Client(name=f"Reattempt-{tag}")
        cand = Candidate(
            name="Powrót",
            lastname=f"Reattempt-{tag}",
            email=f"reattempt-{tag}@example.com",
            status=CandidateStatus("active"),
        )
        db.add_all([cli, cand])
        await db.flush()
        job = Job(
            title=f"Reattempt {tag}", status=JobStatus.published, client_id=cli.id
        )
        db.add(job)
        await db.flush()
        first = RecruitmentProcess(
            candidate_id=cand.id,
            job_id=job.id,
            status=ProcessStatus.closed,
            attempt_no=1,
            opened_at=FIRST_OPENED,
            closed_at=OPENED - timedelta(hours=17),
        )
        db.add(first)
        await db.flush()
        second = RecruitmentProcess(
            candidate_id=cand.id,
            job_id=job.id,
            status=ProcessStatus.open,
            attempt_no=2,
            previous_process_id=first.id,
            opened_at=OPENED,
        )
        db.add(second)
        await db.flush()
        # Świeżo dodany proces nie ma jeszcze wczytanych kolumn — reguła
        # wraca wtedy do początku próby zamiast sięgać do bazy.
        assert cards.attempt_started(second) == OPENED
        await db.commit()
        second_id = second.id

    async with AsyncSessionLocal() as db:
        loaded = (
            await db.execute(
                select(RecruitmentProcess).where(RecruitmentProcess.id == second_id)
            )
        ).scalar_one()
        assert loaded.previous_closed_at == OPENED - timedelta(hours=17)
        assert loaded.previous_opened_at is None
        assert cards.attempt_started(loaded) is None
