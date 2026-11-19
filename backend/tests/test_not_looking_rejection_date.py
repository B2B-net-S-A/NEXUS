"""„Nie szuka pracy” z datą przy karcie dodanej przez człowieka (19.11.2026).

Wybór „3 miesiące / 6 miesięcy / Rok” stał tylko przy osobie od systemu
(`autofill_not_looking_until`). Na kopii z 19.11.2026 w 30 dni 179 odrzuceń
„Nie szuka pracy” na kartach dodanych ręcznie nie miało daty, a rekruterzy
pisali „odezwę się za pół roku” w notatce. Ruch przyjmuje teraz
`not_looking_until` przy powodzie `not_looking_for_work` z szablonu.

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
from app.services.rejection_reason_labels import NOT_LOOKING_FOR_WORK

MOVE = "/api/pipeline/move"


async def _seed(*, reason_name: str = NOT_LOOKING_FOR_WORK):
    """Kandydat dodany ręcznie w „Screeningu”; zwraca (kandydat, rekrutacja, powód)."""
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
        tpl = PipelineTemplate(name=f"NL-Tpl-{uuid.uuid4().hex[:6]}")
        db.add(tpl)
        await db.flush()
        reason = RejectionReason(
            template_id=tpl.id, name=reason_name, category=TerminalType("rejected")
        )
        client = Client(name=f"NL-Client-{uuid.uuid4().hex[:6]}")
        db.add_all([reason, client])
        await db.flush()
        job = Job(
            title=f"NL-Job-{uuid.uuid4().hex[:6]}",
            status=JobStatus.published,
            client_id=client.id,
            pipeline_template_id=tpl.id,
        )
        candidate = Candidate(
            name="Nie",
            lastname=f"Szuka-{uuid.uuid4().hex[:6]}",
            email=f"nl-{uuid.uuid4().hex[:8]}@example.com",
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


async def _reject(
    client: AsyncClient,
    headers,
    candidate_id: int,
    job_id: int,
    reason_id: int,
    until: date | None,
):
    body = {
        "candidate_id": candidate_id,
        "job_id": job_id,
        "stage": "rejected",
        "rejection_reason_id": reason_id,
        "send_rejection_email": False,
    }
    if until is not None:
        body["not_looking_until"] = until.isoformat()
    return await client.post(MOVE, json=body, headers=headers)


async def test_manual_card_saves_not_looking_until_date(
    app_client: AsyncClient, app_auth_headers
):
    until = business_today() + timedelta(days=183)
    cand, job, reason = await _seed()
    response = await _reject(app_client, app_auth_headers, cand, job, reason, until)
    assert response.status_code == 200, response.text

    candidate = await _candidate(cand)
    assert candidate.availability_status == AvailabilityStatus.not_looking
    assert candidate.availability_date == until

    audits = await _availability_audits(cand)
    assert len(audits) == 1
    assert audits[0].details["source"] == "not_looking_rejection"
    assert audits[0].details["job_id"] == job


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
    until = business_today() + timedelta(days=92)
    response = await _reject(app_client, app_auth_headers, cand, job, reason, until)
    assert response.status_code == 200, response.text

    assert calls == [{"candidate_id": cand, "except_job_id": job}]


async def test_without_date_profile_stays_untouched(
    app_client: AsyncClient, app_auth_headers
):
    """API integracyjne i stare okna wysyłają powód bez daty — bez zmian w profilu."""
    cand, job, reason = await _seed()
    response = await _reject(app_client, app_auth_headers, cand, job, reason, None)
    assert response.status_code == 200, response.text

    candidate = await _candidate(cand)
    assert candidate.availability_status != AvailabilityStatus.not_looking
    assert candidate.availability_date is None
    assert await _availability_audits(cand) == []


async def test_date_with_other_reason_is_refused(
    app_client: AsyncClient, app_auth_headers
):
    cand, job, reason = await _seed(reason_name="Brak doświadczenia")
    until = business_today() + timedelta(days=92)
    response = await _reject(app_client, app_auth_headers, cand, job, reason, until)
    assert response.status_code == 422
    assert "Nie szuka" in response.text

    candidate = await _candidate(cand)
    assert candidate.availability_date is None


async def test_past_date_is_refused(app_client: AsyncClient, app_auth_headers):
    cand, job, reason = await _seed()
    response = await _reject(
        app_client, app_auth_headers, cand, job, reason, business_today()
    )
    assert response.status_code == 422


async def test_date_beyond_two_years_is_refused(
    app_client: AsyncClient, app_auth_headers
):
    cand, job, reason = await _seed()
    until = business_today() + timedelta(days=800)
    response = await _reject(app_client, app_auth_headers, cand, job, reason, until)
    assert response.status_code == 422
