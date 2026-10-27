"""Odrzucenie osoby od systemu na cały klient (decyzja Artura 27.10.2026) — Postgres.

Analiza 133 odrzuceń: 13 z 20 „Inne” to klient, nie osoba („pracuje
w Nordei przez inną kontraktownię”, „nie chce do Nordei”), a ci sami ludzie
czekali jeszcze na 45 kartach w innych rekrutacjach tego klienta. Kontrakty:

- „Pracuje u tego klienta” i „Nie chce do tego klienta” z zaznaczonym
  „cały klient” zdejmują nietknięte karty tej osoby od systemu z innych
  rekrutacji klienta (droga „Usuń z rekrutacji”, archiwum bez autora);
- karty ruszone przez człowieka, inne osoby i inni klienci zostają;
- silnik więcej tej osoby temu klientowi nie podsuwa — ale innemu tak,
  a bez „cały klient” tylko w tej jednej rekrutacji.

Baza testowa jest wspólna i nieczyszczona: asercje dotyczą własnych wierszy.
"""

import uuid

from sqlalchemy import select

import app.models  # noqa: F401
from app.core.database import AsyncSessionLocal
from app.models.autofill_feedback import AutofillFeedback
from app.models.candidate import Candidate
from app.models.candidate_stage_removal import CandidateStageRemoval
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.recruitment_process import ProcessStatus, RecruitmentProcess
from app.services import autofill_feedback, autofill_withdraw
from app.services import new_column_autofill as autofill
from tests.test_autofill_feedback import _world as _feedback_world
from tests.test_autofill_feedback import api_client  # noqa: F401 — fixture
from tests.test_new_column_autofill import _fill, _pool, _user


async def _client_with_jobs(jobs: int) -> tuple[int, list[int]]:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"WC client {tag}")
        db.add(client)
        await db.flush()
        rows = [
            Job(
                title=f"WC job {i} {tag}",
                client_id=client.id,
                status=JobStatus.published,
                work_state="searching",
            )
            for i in range(jobs)
        ]
        db.add_all(rows)
        await db.commit()
        return client.id, [j.id for j in rows]


async def _people(n: int) -> list[int]:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        rows = [Candidate(name="Klient", lastname=f"{i}-{tag}") for i in range(n)]
        db.add_all(rows)
        await db.commit()
        return [c.id for c in rows]


async def _feedback(cid: int, job_id: int, reason: str, *, whole_client: bool) -> None:
    async with AsyncSessionLocal() as db:
        db.add(
            AutofillFeedback(
                job_id=job_id,
                candidate_id=cid,
                reason=reason,
                learned_from="call",
                bucket=autofill_feedback.bucket_for(
                    reason, snapshot=None, budget_hourly=None
                ),
                whole_client=whole_client,
            )
        )
        await db.commit()


async def _open_system_jobs(cid: int) -> set[int]:
    async with AsyncSessionLocal() as db:
        return set(
            (
                await db.scalars(
                    select(RecruitmentProcess.job_id).where(
                        RecruitmentProcess.candidate_id == cid,
                        RecruitmentProcess.entry_source == "system",
                        RecruitmentProcess.status == ProcessStatus.open,
                    )
                )
            ).all()
        )


def test_client_reasons_land_in_their_buckets():
    bucket = autofill_feedback.bucket_for
    assert bucket("client_employed", snapshot=None, budget_hourly=None) == "data"
    assert bucket("client_refused", snapshot=None, budget_hourly=None) == "person"
    assert autofill_feedback.CLIENT_WIDE_REASONS == frozenset(
        {"client_employed", "client_refused"}
    )


async def test_withdraws_untouched_cards_at_the_same_client_only(monkeypatch):
    monkeypatch.setattr(autofill, "TARGET", 2)
    client_id, (here, other_a, other_b) = await _client_with_jobs(3)
    _other_client, (elsewhere,) = await _client_with_jobs(1)
    person, colleague = await _people(2)
    for job_id in (here, other_a, other_b, elsewhere):
        await _pool(job_id, {person: 90, colleague: 80})
        await _fill(job_id)
    recruiter = await _user()
    # Karta ruszona przez człowieka zostaje.
    async with AsyncSessionLocal() as db:
        db.add(
            CandidateStage(
                candidate_id=person,
                job_id=other_b,
                stage=PipelineStage.screening,
                moved_by=recruiter,
            )
        )
        await db.commit()

    async with AsyncSessionLocal() as db:
        done = await autofill_withdraw.withdraw_at_client(
            db, candidate_id=person, client_id=client_id, except_job_id=here
        )
        await db.commit()

    assert done == [(person, other_a)]
    assert await _open_system_jobs(person) == {here, other_b, elsewhere}
    assert await _open_system_jobs(colleague) == {here, other_a, other_b, elsewhere}
    async with AsyncSessionLocal() as db:
        removal = await db.scalar(
            select(CandidateStageRemoval).where(
                CandidateStageRemoval.candidate_id == person,
                CandidateStageRemoval.job_id == other_a,
            )
        )
    assert removal.reason == autofill_withdraw.CLIENT_REMOVAL_REASON
    assert removal.removed_by is None


async def test_engine_skips_the_person_at_that_client_after_whole_client_reason(
    monkeypatch,
):
    monkeypatch.setattr(autofill, "TARGET", 5)
    client_id, (rejected_here, next_job) = await _client_with_jobs(2)
    _other, (elsewhere,) = await _client_with_jobs(1)
    refused, employed, single_job, ok = await _people(4)
    await _feedback(refused, rejected_here, "client_refused", whole_client=True)
    await _feedback(employed, rejected_here, "client_employed", whole_client=True)
    # Bez „cały klient” odrzucenie dotyczy tylko tamtej rekrutacji.
    await _feedback(single_job, rejected_here, "client_refused", whole_client=False)
    scores = {refused: 90, employed: 85, single_job: 80, ok: 70}
    await _pool(next_job, scores)
    await _pool(elsewhere, scores)

    assert await _fill(next_job) == [single_job, ok]
    assert await _fill(elsewhere) == [refused, employed, single_job, ok]


async def test_move_with_whole_client_withdraws_the_other_card(
    api_client,  # noqa: F811 — fixture z test_autofill_feedback
    monkeypatch,
):
    """Odrzucenie przez `/api/pipeline/move` z „cały klient” zapisuje powód
    z ``whole_client`` i zdejmuje kartę tej osoby z drugiej rekrutacji."""
    from datetime import datetime, timezone

    from app.models.pipeline_template import RejectionReason

    monkeypatch.setattr(autofill, "TARGET", 1)
    world = await _feedback_world()
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, world["job_id"])
        second = Job(
            title=f"{job.title} 2",
            client_id=job.client_id,
            status=JobStatus.published,
            work_state="searching",
        )
        db.add(second)
        await db.commit()
        second_id = second.id
    await _pool(second_id, {world["system"]: 70})
    async with AsyncSessionLocal() as db:
        now = datetime.now(timezone.utc)
        assert await autofill.fill_job(db, world["job_id"], now=now) == [
            world["system"]
        ]
        assert await autofill.fill_job(db, second_id, now=now) == [world["system"]]
        await db.commit()
    login = await api_client.post(
        "/api/auth/login",
        json={"email": world["email"], "password": world["password"]},
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    async with AsyncSessionLocal() as db:
        reason_id = await db.scalar(
            select(RejectionReason.id).where(
                RejectionReason.category == "rejected",
                RejectionReason.template_id.is_(None),
            )
        )

    moved = await api_client.post(
        "/api/pipeline/move",
        headers=headers,
        json={
            "candidate_id": world["system"],
            "job_id": world["job_id"],
            "stage": "rejected",
            "rejection_reason_id": reason_id,
            "rejection_reason": None if reason_id else "nie chce do klienta",
            "notes": "Nie chce do tego klienta.",
            "autofill_reason": "client_refused",
            "autofill_learned_from": "call",
            "autofill_whole_client": True,
        },
    )

    assert moved.status_code == 200, moved.text
    async with AsyncSessionLocal() as db:
        row = await db.scalar(
            select(AutofillFeedback).where(
                AutofillFeedback.job_id == world["job_id"],
                AutofillFeedback.candidate_id == world["system"],
            )
        )
    assert (row.reason, row.bucket, row.whole_client) == (
        "client_refused",
        "person",
        True,
    )
    assert second_id not in await _open_system_jobs(world["system"])
