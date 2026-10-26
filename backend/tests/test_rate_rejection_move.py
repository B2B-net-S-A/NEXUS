"""Odrzucenie „Za wysokie oczekiwania finansowe” zapisuje nową stawkę (26.10.2026).

Prośba Marka: osoba z „Stawką od” 129 zł/h mówi przy telefonie, że jej minimum
to teraz 150. Rekruter odrzucał ją z powodem finansowym i wpisywał „150 minimum”
w opis, którego „Stawka od” nie czyta (51 ze 118 takich odrzuceń na kopii
z 22.10.2026). Teraz ruch niesie ``rejection_rate_hourly``: kwota trafia do
profilu i historii stawek, a przy ``rejection_rate_is_minimum`` (domyślnie)
jako jawne minimum, które unieważnia starsze, niższe stawki.

Uses in-process fixtures (real postgres in CI).
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.services.rejection_reason_labels import RATE_TOO_HIGH_REJECTED, SALARY_MISMATCH

MOVE = "/api/pipeline/move"


async def _seed(
    *, reason_name: str = RATE_TOO_HIGH_REJECTED, category: str = "rejected"
):
    """Kandydat z profilem 129 zł/h w „Screeningu” rekrutacji z powodem finansowym.

    Zwraca (candidate_id, job_id, rate_reason_id, other_reason_id).
    """
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.services import candidate_audit
    from app.models.job import Job, JobStatus
    from app.models.pipeline_template import (
        PipelineTemplate,
        RejectionReason,
        TerminalType,
    )
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage

    async with AsyncSessionLocal() as db:
        tpl = PipelineTemplate(name=f"RR-Tpl-{uuid.uuid4().hex[:6]}")
        db.add(tpl)
        await db.flush()
        rate = RejectionReason(
            template_id=tpl.id, name=reason_name, category=TerminalType(category)
        )
        other = RejectionReason(
            template_id=tpl.id,
            name=f"RR-Other-{uuid.uuid4().hex[:4]}",
            category=TerminalType(category),
        )
        client = Client(name=f"RR-Client-{uuid.uuid4().hex[:6]}")
        db.add_all([rate, other, client])
        await db.flush()
        job = Job(
            title=f"RR-Job-{uuid.uuid4().hex[:6]}",
            status=JobStatus.published,
            client_id=client.id,
            pipeline_template_id=tpl.id,
        )
        candidate = Candidate(
            name="Stawka",
            lastname=f"Odrzucenie-{uuid.uuid4().hex[:6]}",
            email=f"rr-{uuid.uuid4().hex[:8]}@example.com",
            expected_rate_hourly=Decimal("129.00"),
            expected_rate_currency="PLN",
        )
        db.add_all([job, candidate])
        await db.flush()
        # 129 zł/h podane kiedyś w profilu — wpis w dzienniku, jak u prawdziwej
        # osoby (sama kolumna profilu bez śladu nie jest osobną obserwacją).
        candidate_audit.record_candidate_audit(
            db,
            action=candidate_audit.PROFILE_RATE_CHANGED,
            user_id=None,
            entity_id=candidate.id,
            details={"new_amount": "129.00", "source": "manual"},
        )
        db.add(
            CandidateStage(
                candidate_id=candidate.id,
                job_id=job.id,
                stage=PipelineStage.screening,
            )
        )
        await db.commit()
        return candidate.id, job.id, rate.id, other.id


async def _candidate(candidate_id: int):
    from app.models.candidate import Candidate

    async with AsyncSessionLocal() as db:
        return await db.get(Candidate, candidate_id)


async def _rate_audits(candidate_id: int):
    from app.models.activity import Activity

    async with AsyncSessionLocal() as db:
        return (
            await db.scalars(
                select(Activity)
                .where(
                    Activity.entity_type == "candidate",
                    Activity.entity_id == candidate_id,
                    Activity.action == "profile_rate_changed",
                )
                .order_by(Activity.id)
            )
        ).all()


def _move(candidate_id, job_id, reason_id, *, stage="rejected", **extra):
    return {
        "candidate_id": candidate_id,
        "job_id": job_id,
        "stage": stage,
        "rejection_reason_id": reason_id,
        "send_rejection_email": False,
        **extra,
    }


async def test_new_minimum_lands_on_profile_and_rate_from(
    app_client: AsyncClient, app_auth_headers
):
    cand, job, reason, _ = await _seed()
    r = await app_client.post(
        MOVE,
        json=_move(cand, job, reason, rejection_rate_hourly=150),
        headers=app_auth_headers,
    )
    assert r.status_code == 200, r.text

    c = await _candidate(cand)
    assert c.expected_rate_hourly == Decimal("150.00")
    # Jawne minimum unieważnia starsze, niższe 129 — „Stawka od” = 150.
    assert c.rate_from_hourly == Decimal("150.00")

    audits = await _rate_audits(cand)
    assert len(audits) == 2  # 129 z przeszłości + 150 z odrzucenia
    details = audits[-1].details
    assert details["source"] == "rejection_minimum"
    assert details["rate_meaning"] == "minimum"
    assert details["job_id"] == job
    assert details["stage_id"] == r.json()["id"]

    # Historia procesu: kwota w opisie powodu, także bez opisu od rekrutera.
    assert r.json()["notes"] == "Chce min. 150 zł/h"


async def test_description_keeps_recruiter_text_after_amount(
    app_client: AsyncClient, app_auth_headers
):
    cand, job, reason, _ = await _seed()
    r = await app_client.post(
        MOVE,
        json=_move(
            cand, job, reason, rejection_rate_hourly="152.5", notes="projekt za 130"
        ),
        headers=app_auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["notes"] == "Chce min. 152,5 zł/h — projekt za 130"


async def test_unticked_minimum_is_a_plain_rate(
    app_client: AsyncClient, app_auth_headers
):
    cand, job, reason, _ = await _seed(
        reason_name=SALARY_MISMATCH, category="withdrawn"
    )
    r = await app_client.post(
        MOVE,
        json=_move(
            cand,
            job,
            reason,
            stage="withdrawn",
            rejection_rate_hourly=150,
            rejection_rate_is_minimum=False,
        ),
        headers=app_auth_headers,
    )
    assert r.status_code == 200, r.text

    c = await _candidate(cand)
    assert c.expected_rate_hourly == Decimal("150.00")
    # Zwykła stawka: najniższa z 18 miesięcy dalej wygrywa.
    assert c.rate_from_hourly == Decimal("129.00")
    details = (await _rate_audits(cand))[-1].details
    assert details["source"] == "rejection"
    assert "rate_meaning" not in details
    assert r.json()["notes"] == "Chce 150 zł/h"


async def test_without_amount_profile_stays(app_client: AsyncClient, app_auth_headers):
    cand, job, reason, _ = await _seed()
    r = await app_client.post(
        MOVE, json=_move(cand, job, reason), headers=app_auth_headers
    )
    assert r.status_code == 200, r.text
    c = await _candidate(cand)
    assert c.expected_rate_hourly == Decimal("129.00")
    assert len(await _rate_audits(cand)) == 1  # tylko 129 z przeszłości


async def test_amount_with_another_reason_is_refused(
    app_client: AsyncClient, app_auth_headers
):
    cand, job, _, other = await _seed()
    r = await app_client.post(
        MOVE,
        json=_move(cand, job, other, rejection_rate_hourly=150),
        headers=app_auth_headers,
    )
    assert r.status_code == 422, r.text
    assert "oczekiwania finansowe" in r.json()["detail"]
    c = await _candidate(cand)
    assert c.expected_rate_hourly == Decimal("129.00")


def test_rejection_rate_in_history_names_its_recruitment():
    """Wpis z odrzucenia niesie rekrutację — historia stawek pokazuje jej nazwę."""
    from datetime import datetime, timezone

    from app.services.candidate_rate_observations import _profile_observation

    row = {
        "id": 7,
        "candidate_id": 1,
        "user_id": 2,
        "created_at": datetime(2026, 10, 26, tzinfo=timezone.utc),
        "details": {
            "new_amount": "150.00",
            "source": "rejection_minimum",
            "rate_meaning": "minimum",
            "job_id": 306,
        },
    }
    obs = _profile_observation(row)
    assert obs.job_id == 306 and obs.explicit_minimum
    # Inne zapisy profilu zostają bez rekrutacji, nawet z `job_id` w audycie.
    other = _profile_observation(
        {**row, "details": {**row["details"], "source": "manual"}}
    )
    assert other.job_id is None
