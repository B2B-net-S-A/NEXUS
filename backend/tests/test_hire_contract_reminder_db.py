"""Dzwonek „Wpisz umowę” na żywej bazie (17.10.2026).

Ręczne „Potwierdź zatrudnienie” bez umowy w Kontraktach dzwoni do Delivery
Leada klienta rekrutacji raz na parę osoba–rekrutacja; z umową — wcale.
Osoby i firmy są zmyślone. Część czysta: ``test_hire_contract_reminder.py``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

import app.models  # noqa: F401  (rejestracja wszystkich mapperów)
from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus
from app.models.job import Job, JobStatus
from app.models.notification import Notification, NotificationType
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.team_structure import DeliveryLeadClientAssignment
from app.models.user import User, UserRole
from app.services.hire_contract_reminder import notify_hire_without_contract


async def _seed(*, with_contract: bool) -> dict:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Umowa-Klient-{tag}")
        person = Candidate(
            name="Ewa", lastname=f"Zatrudniona-{tag}", email=f"hire-{tag}@example.com"
        )
        lead = User(
            email=f"hire-lead-{tag}@example.com",
            password_hash="test-only",
            name=f"Lead {tag}",
            role=UserRole.delivery_lead,
            roles=[UserRole.delivery_lead.value],
            is_active=True,
        )
        db.add_all([client, person, lead])
        await db.flush()
        job = Job(title=f"Umowa-{tag}", status=JobStatus.published, client_id=client.id)
        db.add_all(
            [
                job,
                DeliveryLeadClientAssignment(
                    delivery_lead_user_id=lead.id, client_id=client.id, is_head=True
                ),
            ]
        )
        if with_contract:
            db.add(
                Contract(
                    candidate_id=person.id,
                    client_id=client.id,
                    start_date=business_today() + timedelta(days=14),
                    status=ContractStatus.draft,
                )
            )
        await db.commit()
        return {"person": person.id, "job": job.id, "lead": lead.id}


async def _move(ids: dict, stage: PipelineStage, minute: int) -> int:
    async with AsyncSessionLocal() as db:
        row = CandidateStage(
            candidate_id=ids["person"],
            job_id=ids["job"],
            stage=stage,
            moved_at=datetime.now(timezone.utc) + timedelta(minutes=minute),
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        sent = await notify_hire_without_contract(
            db,
            new_stage=row,
            previous_stage=None,
            job=await db.get(Job, ids["job"]),
            candidate=await db.get(Candidate, ids["person"]),
            mover=None,
        )
        await db.commit()
        return sent


async def _bells(user_id: int) -> int:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(func.count(Notification.id)).where(
                Notification.user_id == user_id,
                Notification.notification_type
                == NotificationType.hire_missing_contract,
            )
        )


async def test_hire_without_a_contract_rings_the_lead_once_per_pair():
    ids = await _seed(with_contract=False)

    assert await _move(ids, PipelineStage.cv_sent, 0) == 0
    assert await _move(ids, PipelineStage.hired, 1) == 1
    # Cofnięte z „Zatrudniony” i zatrudnione jeszcze raz — ten sam temat.
    assert await _move(ids, PipelineStage.client_interview, 2) == 0
    assert await _move(ids, PipelineStage.hired, 3) == 0
    assert await _bells(ids["lead"]) == 1


async def test_a_contract_in_kontrakty_means_no_bell():
    """Szkic umowy też: Delivery już się nią zajmuje."""
    ids = await _seed(with_contract=True)

    assert await _move(ids, PipelineStage.hired, 0) == 0
    assert await _bells(ids["lead"]) == 0
