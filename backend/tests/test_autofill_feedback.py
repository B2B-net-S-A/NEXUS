"""Odrzucenie osoby od systemu z powodem (silnik „Nowi na 20”, 23.10.2026).

Kontrakty:

- kosz raportu liczy się z migawki tego, co system wiedział: „za droga”
  przy nieznanej stawce = brak danych, przy znanej ponad budżetem = błąd
  wyszukiwania;
- osoba od systemu z „Nowych”/„Screeningu” bez powodu → 422
  ``AUTOFILL_REASON_REQUIRED``; powód przy innej osobie → 422; „Inne” bez
  opisu → 422;
- ruch z powodem zapisuje wiersz ``autofill_feedback`` z migawką, a stawka
  z rozmowy idzie do „Stawki od”.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

import app.models  # noqa: F401
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.autofill_feedback import AutofillFeedback
from app.models.candidate import Candidate
from app.models.candidate_stage_removal import CandidateStageRemoval
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.job_autofill_pool import JobAutofillPool
from app.models.pipeline_template import RejectionReason
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.recruitment_process import ProcessStatus, RecruitmentProcess
from app.models.user import User, UserRole
from app.services import autofill_feedback as feedback
from app.services import autofill_withdraw
from app.services import new_column_autofill as autofill
from app.services.autofill_feedback_schema import REASONS
from tests.test_new_column_autofill import _fill, _pool, _user

# ── reguła bez bazy ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("reason", "snapshot", "budget", "bucket"),
    [
        ("missing_skill", {}, None, "search"),
        ("language", {}, None, "search"),
        ("outdated_cv", {}, None, "data"),
        ("not_looking", {}, None, "person"),
        ("other", {}, None, "other"),
        # System nie znał stawki — to brak danych, nie błąd wyszukiwania.
        ("too_expensive", {"rate_from_hourly": None}, 130.0, "data"),
        # Znał stawkę ponad budżetem i mimo to dodał — błąd doboru.
        ("too_expensive", {"rate_from_hourly": 160.0}, 130.0, "search"),
        # Znał stawkę w budżecie — osoba chce dziś więcej: brak danych.
        ("too_expensive", {"rate_from_hourly": 120.0}, 130.0, "data"),
        # Rekrutacja bez budżetu — nie ma z czym porównać.
        ("too_expensive", {"rate_from_hourly": 160.0}, None, "data"),
    ],
)
def test_bucket_follows_what_the_system_knew(reason, snapshot, budget, bucket):
    assert (
        feedback.bucket_for(reason, snapshot=snapshot, budget_hourly=budget) == bucket
    )


def test_every_reason_has_a_polish_label():
    assert set(feedback.REASON_LABELS) == set(REASONS)


def test_validation_requires_reason_only_for_system_people():
    process = SimpleNamespace(entry_source="system")
    with pytest.raises(HTTPException) as missing:
        feedback.validate(process=process, reason=None, learned_from=None, note=None)
    assert missing.value.status_code == 422
    assert missing.value.detail["code"] == feedback.REQUIRED_CODE
    with pytest.raises(HTTPException):
        feedback.validate(
            process=process, reason="missing_skill", learned_from=None, note=None
        )
    with pytest.raises(HTTPException):
        feedback.validate(
            process=process, reason="other", learned_from="call", note=" "
        )
    feedback.validate(process=process, reason="other", learned_from="call", note="opis")
    with pytest.raises(HTTPException):
        feedback.validate(
            process=None, reason="missing_skill", learned_from="call", note=None
        )
    feedback.validate(process=None, reason=None, learned_from=None, note=None)


# ── przez API ───────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def api_client():
    from app.core.rate_limit import limiter as _limiter
    from app.main import app

    _limiter.enabled = False
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as c:
        yield c


async def _world() -> dict:
    tag = uuid.uuid4().hex[:8]
    password = f"T3st_{tag}!Fb"
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"afb-{tag}@example.com",
            password_hash=hash_password(password),
            name=f"AFB {tag}",
            role=UserRole.recruiter,
            is_active=True,
            profile_completed=True,
        )
        client = Client(name=f"AFB client {tag}")
        db.add_all([user, client])
        await db.flush()
        job = Job(
            title=f"AFB job {tag}",
            client_id=client.id,
            status=JobStatus.published,
            work_state="searching",
            recruiter_id=user.id,
            rate_budget_hourly=Decimal("130"),
        )
        system_person = Candidate(name="Od", lastname=f"Systemu-{tag}")
        human_person = Candidate(name="Od", lastname=f"Człowieka-{tag}")
        db.add_all([job, system_person, human_person])
        await db.flush()
        db.add(
            JobAutofillPool(
                job_id=job.id,
                candidate_id=system_person.id,
                score=Decimal("77"),
                run_id="run-afb",
                evidence={"matched_must": ["Java"], "missing_must": []},
            )
        )
        await db.commit()
        return {
            "email": user.email,
            "password": password,
            "user_id": user.id,
            "job_id": job.id,
            "system": system_person.id,
            "human": human_person.id,
        }


async def test_rejecting_a_system_person_needs_a_reason_and_stores_it(
    api_client, monkeypatch
):
    monkeypatch.setattr(autofill, "TARGET", 1)
    world = await _world()
    async with AsyncSessionLocal() as db:
        assert await autofill.fill_job(
            db, world["job_id"], now=datetime.now(timezone.utc)
        ) == [world["system"]]
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
    base = {
        "candidate_id": world["system"],
        "job_id": world["job_id"],
        "stage": "rejected",
        "rejection_reason_id": reason_id,
        "rejection_reason": None if reason_id else "nie pasuje",
        "notes": "Na B2B od stycznia.",
    }

    missing = await api_client.post("/api/pipeline/move", headers=headers, json=base)
    assert missing.status_code == 422, missing.text
    assert missing.json()["detail"]["code"] == "AUTOFILL_REASON_REQUIRED"

    ok = await api_client.post(
        "/api/pipeline/move",
        headers=headers,
        json={
            **base,
            "autofill_reason": "too_expensive",
            "autofill_learned_from": "call",
            "autofill_rate_hourly": "175",
        },
    )
    assert ok.status_code == 200, ok.text
    async with AsyncSessionLocal() as db:
        [row] = (
            await db.scalars(
                select(AutofillFeedback).where(
                    AutofillFeedback.job_id == world["job_id"]
                )
            )
        ).all()
    assert row.candidate_id == world["system"]
    assert (row.reason, row.learned_from, row.bucket) == (
        "too_expensive",
        "call",
        "data",
    )
    assert row.rate_hourly == Decimal("175.00")
    assert row.created_by == world["user_id"]
    assert row.snapshot["kind"] == "autofill" and row.snapshot["score"] == 77.0

    # Powód dla systemu przy osobie dodanej przez człowieka — 422.
    async with AsyncSessionLocal() as db:
        from app.api.proposals_bulk import add_candidates_to_job

        job = await db.get(Job, world["job_id"])
        await add_candidates_to_job(
            db,
            job=job,
            candidate_ids=[world["human"]],
            actor_user_id=world["user_id"],
        )
        await db.commit()
    wrong = await api_client.post(
        "/api/pipeline/move",
        headers=headers,
        json={
            **base,
            "candidate_id": world["human"],
            "autofill_reason": "missing_skill",
            "autofill_learned_from": "profile",
        },
    )
    assert wrong.status_code == 422, wrong.text


# ── Odrzucenie na cały klient (27.10.2026, 0530) ────────────────────────────
# Odrzucenie osoby od systemu na cały klient (decyzja Artura 27.10.2026) — Postgres.
#
# Analiza 133 odrzuceń: 13 z 20 „Inne” to klient, nie osoba („pracuje
# w Nordei przez inną kontraktownię”, „nie chce do Nordei”), a ci sami ludzie
# czekali jeszcze na 45 kartach w innych rekrutacjach tego klienta. Kontrakty:
#
# - „Pracuje u tego klienta” i „Nie chce do tego klienta” z zaznaczonym
#   „cały klient” zdejmują nietknięte karty tej osoby od systemu z innych
#   rekrutacji klienta (droga „Usuń z rekrutacji”, archiwum bez autora);
# - karty ruszone przez człowieka, inne osoby i inni klienci zostają;
# - silnik więcej tej osoby temu klientowi nie podsuwa — ale innemu tak,
#   a bez „cały klient” tylko w tej jednej rekrutacji.
#
# Baza testowa jest wspólna i nieczyszczona: asercje dotyczą własnych wierszy.


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
                bucket=feedback.bucket_for(reason, snapshot=None, budget_hourly=None),
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
    bucket = feedback.bucket_for
    assert bucket("client_employed", snapshot=None, budget_hourly=None) == "data"
    assert bucket("client_refused", snapshot=None, budget_hourly=None) == "person"
    assert feedback.CLIENT_WIDE_REASONS == frozenset(
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


async def test_move_with_whole_client_withdraws_the_other_card(api_client, monkeypatch):
    """Odrzucenie przez `/api/pipeline/move` z „cały klient” zapisuje powód
    z ``whole_client`` i zdejmuje kartę tej osoby z drugiej rekrutacji."""
    monkeypatch.setattr(autofill, "TARGET", 1)
    world = await _world()
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
