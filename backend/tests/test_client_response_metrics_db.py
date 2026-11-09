"""Zapytania „Odpowiedź klienta” i „Pierwsze CV” na prawdziwej bazie (CI)."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job, JobStatus, RemotePolicy
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.services.client_response_metrics import (
    compute_client_response_board,
    compute_first_cv,
)

TODAY = date(2026, 11, 8)


def _at(month: int, day: int) -> datetime:
    return datetime(2026, month, day, 10, tzinfo=timezone.utc)


async def _job(db, client_id: int, tag: str, **kw) -> Job:
    job = Job(
        title=f"Rekrutacja {tag}",
        location="Warszawa",
        status=kw.pop("status", JobStatus.published),
        remote_policy=RemotePolicy.hybrid,
        client_id=client_id,
        **kw,
    )
    db.add(job)
    await db.flush()
    return job


async def _candidates(db, tag: str, count: int) -> list[int]:
    rows = [
        Candidate(name=f"K{i}", lastname=tag, email=f"cr-{tag}-{i}@example.com")
        for i in range(count)
    ]
    db.add_all(rows)
    await db.flush()
    return [row.id for row in rows]


def _stage(db, cand: int, job: int, stage: PipelineStage, when: datetime, **kw) -> None:
    db.add(
        CandidateStage(candidate_id=cand, job_id=job, stage=stage, moved_at=when, **kw)
    )


@pytest.mark.asyncio
async def test_board_counts_client_answers_and_ignores_recruiter_rejection() -> None:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Odpowiedz-{tag}")
        db.add(client)
        await db.flush()
        job = await _job(db, client.id, tag)
        c = await _candidates(db, tag, 6)
        # c0: rozmowa u klienta 7. dnia roboczego po wysyłce: odpowiedź.
        _stage(db, c[0], job.id, PipelineStage.cv_sent, _at(10, 12))
        _stage(db, c[0], job.id, PipelineStage.client_interview, _at(10, 21))
        # c1: odrzucenie przez rekrutera: nie jest odpowiedzią klienta.
        _stage(db, c[1], job.id, PipelineStage.cv_sent, _at(10, 13))
        _stage(
            db, c[1], job.id, PipelineStage.rejected, _at(10, 14), ended_by="recruiter"
        )
        # c2: odrzucenie przez klienta: odpowiedź.
        _stage(db, c[2], job.id, PipelineStage.cv_sent, _at(10, 14))
        _stage(db, c[2], job.id, PipelineStage.rejected, _at(10, 15), ended_by="client")
        # c3: odpowiedź dopiero 8. dnia roboczego: poza czasem.
        _stage(db, c[3], job.id, PipelineStage.cv_sent, _at(10, 12))
        _stage(db, c[3], job.id, PipelineStage.client_interview, _at(10, 22))
        # c4: pierwsza wysyłka przed oknem: druga wysyłka nie liczy się jako nowe CV.
        _stage(db, c[4], job.id, PipelineStage.cv_sent, _at(9, 1))
        _stage(db, c[4], job.id, PipelineStage.cv_sent, _at(10, 20))
        # c5: bez odpowiedzi, dalej czeka u klienta.
        _stage(db, c[5], job.id, PipelineStage.cv_sent, _at(10, 15))
        client_id = client.id
        await db.commit()

    async with AsyncSessionLocal() as db:
        board = await compute_client_response_board(db, TODAY, [client_id])

    assert board.response.cohort_cv == 5
    assert board.response.responded_7d == 2
    assert board.response.response_7d_pct == 40.0
    row = board.response.clients[0]
    assert row.client_id == client_id
    assert row.responded_7d == 2
    # c4 (nie liczy się w oknie, ale stoi w „Wysłane do klienta”) i c5.
    assert row.cv_in_progress == 2
    assert row.oldest_waiting_workdays is not None


@pytest.mark.asyncio
async def test_board_scope_hides_other_clients() -> None:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        mine = Client(name=f"Moj-{tag}")
        other = Client(name=f"Cudzy-{tag}")
        db.add_all([mine, other])
        await db.flush()
        job_mine = await _job(db, mine.id, tag)
        job_other = await _job(db, other.id, f"{tag}b")
        c = await _candidates(db, tag, 2)
        _stage(db, c[0], job_mine.id, PipelineStage.cv_sent, _at(10, 12))
        _stage(db, c[1], job_other.id, PipelineStage.cv_sent, _at(10, 12))
        mine_id, other_id = mine.id, other.id
        await db.commit()

    async with AsyncSessionLocal() as db:
        board = await compute_client_response_board(db, TODAY, [mine_id])

    ids = {row.client_id for row in board.response.clients}
    assert mine_id in ids
    assert other_id not in ids


@pytest.mark.asyncio
async def test_first_cv_skips_import_and_sends_before_opening() -> None:
    tag = uuid.uuid4().hex[:8]
    opened = _at(10, 12)
    async with AsyncSessionLocal() as db:
        client = Client(name=f"PierwszeCV-{tag}")
        db.add(client)
        await db.flush()
        # Import z Traffita: odpada, choć ma CV tego samego dnia.
        imported = await _job(
            db,
            client.id,
            f"{tag}i",
            external_source="traffit",
            opened_at=_at(5, 1),
        )
        imported.created_at = opened
        # Ręczna: CV sprzed otwarcia (kopia) się nie liczy, liczy się 14.10.
        manual = await _job(db, client.id, f"{tag}m", opened_at=opened)
        manual.created_at = opened
        # Ręczna bez `opened_at`: start od `created_at`, bez CV.
        no_opened = await _job(db, client.id, f"{tag}n")
        no_opened.created_at = _at(10, 13)
        c = await _candidates(db, tag, 3)
        _stage(db, c[0], imported.id, PipelineStage.cv_sent, opened)
        _stage(db, c[1], manual.id, PipelineStage.cv_sent, _at(10, 1))
        _stage(db, c[2], manual.id, PipelineStage.cv_sent, _at(10, 14))
        client_id = client.id
        await db.commit()

    async with AsyncSessionLocal() as db:
        summary = await compute_first_cv(db, TODAY, [client_id])

    assert summary.opened_jobs == 2
    assert summary.jobs_with_cv == 1
    assert summary.jobs_without_cv == 1
    assert summary.median_first_cv_workdays == 2.0
