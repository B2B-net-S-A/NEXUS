"""Odrzucenie „Zatrudniony gdzie indziej” zapisuje „Nie szuka” na 3 miesiące (04.11.2026).

Kopia z 04.11.2026: 41 ze 159 tak odrzuconych osób dostało potem 61 kart od
systemu i żadna nie doszła do „Zweryfikowany”. Ruch zapisuje teraz w profilu
„Nie szuka” z datą, a silnik „Nowi na 20” pomija osobę do tej daty.

Uses in-process fixtures (real postgres in CI).
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.candidate import AvailabilityStatus
from app.services.rejection_reason_labels import EMPLOYED_ELSEWHERE

MOVE = "/api/pipeline/move"


async def _seed(
    *,
    reason_name: str = EMPLOYED_ELSEWHERE,
    availability_status: AvailabilityStatus | None = None,
    availability_date: date | None = None,
):
    """Kandydat w „Screeningu” rekrutacji z szablonem; zwraca (kandydat, rekrutacja, powód)."""
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.job import Job, JobStatus
    from app.models.pipeline_template import (
        PipelineTemplate,
        RejectionReason,
        TerminalType,
    )
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage

    async with AsyncSessionLocal() as db:
        tpl = PipelineTemplate(name=f"EE-Tpl-{uuid.uuid4().hex[:6]}")
        db.add(tpl)
        await db.flush()
        reason = RejectionReason(
            template_id=tpl.id, name=reason_name, category=TerminalType("rejected")
        )
        client = Client(name=f"EE-Client-{uuid.uuid4().hex[:6]}")
        db.add_all([reason, client])
        await db.flush()
        job = Job(
            title=f"EE-Job-{uuid.uuid4().hex[:6]}",
            status=JobStatus.published,
            client_id=client.id,
            pipeline_template_id=tpl.id,
        )
        candidate = Candidate(
            name="Zatrudniony",
            lastname=f"Gdzieindziej-{uuid.uuid4().hex[:6]}",
            email=f"ee-{uuid.uuid4().hex[:8]}@example.com",
            availability_status=availability_status,
            availability_date=availability_date,
        )
        db.add_all([job, candidate])
        await db.flush()
        db.add(
            CandidateStage(
                candidate_id=candidate.id,
                job_id=job.id,
                stage=PipelineStage.screening,
            )
        )
        await db.commit()
        return candidate.id, job.id, reason.id


async def _candidate(candidate_id: int):
    from app.models.candidate import Candidate

    async with AsyncSessionLocal() as db:
        return await db.get(Candidate, candidate_id)


async def _availability_audits(candidate_id: int):
    from app.models.activity import Activity
    from app.services import candidate_audit

    async with AsyncSessionLocal() as db:
        return (
            await db.scalars(
                select(Activity).where(
                    Activity.entity_type == "candidate",
                    Activity.entity_id == candidate_id,
                    Activity.action == candidate_audit.AVAILABILITY_CHANGED,
                )
            )
        ).all()


async def _reject(client: AsyncClient, headers, candidate_id, job_id, reason_id):
    response = await client.post(
        MOVE,
        json={
            "candidate_id": candidate_id,
            "job_id": job_id,
            "stage": "rejected",
            "rejection_reason_id": reason_id,
            "send_rejection_email": False,
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response


async def test_rejection_marks_not_looking_for_three_months(
    app_client: AsyncClient, app_auth_headers
):
    cand, job, reason = await _seed()
    await _reject(app_client, app_auth_headers, cand, job, reason)

    candidate = await _candidate(cand)
    assert candidate.availability_status == AvailabilityStatus.not_looking
    assert candidate.availability_date == business_today() + timedelta(days=92)

    audits = await _availability_audits(cand)
    assert len(audits) == 1
    assert audits[0].details["source"] == "employed_elsewhere_rejection"
    assert audits[0].details["job_id"] == job


async def test_other_reason_leaves_profile_alone(
    app_client: AsyncClient, app_auth_headers
):
    cand, job, reason = await _seed(reason_name="Brak doświadczenia")
    await _reject(app_client, app_auth_headers, cand, job, reason)

    candidate = await _candidate(cand)
    assert candidate.availability_status != AvailabilityStatus.not_looking
    assert candidate.availability_date is None
    assert await _availability_audits(cand) == []


async def test_longer_not_looking_date_is_kept(
    app_client: AsyncClient, app_auth_headers
):
    later = business_today() + timedelta(days=300)
    cand, job, reason = await _seed(
        availability_status=AvailabilityStatus.not_looking,
        availability_date=later,
    )
    await _reject(app_client, app_auth_headers, cand, job, reason)

    candidate = await _candidate(cand)
    assert candidate.availability_date == later
    assert await _availability_audits(cand) == []


async def test_not_looking_without_date_is_kept(
    app_client: AsyncClient, app_auth_headers
):
    cand, job, reason = await _seed(availability_status=AvailabilityStatus.not_looking)
    await _reject(app_client, app_auth_headers, cand, job, reason)

    candidate = await _candidate(cand)
    assert candidate.availability_status == AvailabilityStatus.not_looking
    assert candidate.availability_date is None
    assert await _availability_audits(cand) == []


async def test_shorter_not_looking_date_is_extended(
    app_client: AsyncClient, app_auth_headers
):
    cand, job, reason = await _seed(
        availability_status=AvailabilityStatus.not_looking,
        availability_date=business_today() + timedelta(days=10),
    )
    await _reject(app_client, app_auth_headers, cand, job, reason)

    candidate = await _candidate(cand)
    assert candidate.availability_date == business_today() + timedelta(days=92)


async def test_untouched_system_cards_elsewhere_are_withdrawn(
    app_client: AsyncClient, app_auth_headers, monkeypatch
):
    from app.services import autofill_withdraw

    calls: list[dict] = []

    async def spy(db, *, candidate_id, except_job_id):
        calls.append({"candidate_id": candidate_id, "except_job_id": except_job_id})
        return []

    monkeypatch.setattr(autofill_withdraw, "withdraw_elsewhere", spy)
    cand, job, reason = await _seed()
    await _reject(app_client, app_auth_headers, cand, job, reason)

    assert calls == [{"candidate_id": cand, "except_job_id": job}]
