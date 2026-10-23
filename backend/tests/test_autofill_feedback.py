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
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.job_autofill_pool import JobAutofillPool
from app.models.pipeline_template import RejectionReason
from app.models.user import User, UserRole
from app.services import autofill_feedback as feedback
from app.services import new_column_autofill as autofill
from app.services.autofill_feedback_schema import REASONS

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
