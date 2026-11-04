"""Zamknięcie karty anuluje otwarty wniosek o terminy (decyzja Artura 04.11.2026).

Pomiar z 04.11.2026: 7 z 15 otwartych wniosków stało na kartach „Odrzucony”
albo „Wycofany”. Karta nadal mówiła „Wybierz termin”, panel osoby miał aktywny
przycisk, a przyszły termin dałoby się wybrać i założyć rozmowę osobie spoza
procesu.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import Candidate, CandidateStatus
from app.models.client import Client
from app.models.client_interview_slot_request import (
    SLOT_STATUS_AWAITING_DL,
    SLOT_STATUS_AWAITING_RECRUITER,
    SLOT_STATUS_CANCELLED,
    SLOT_STATUS_CONFIRMED,
    ClientInterviewSlotRequest,
)
from app.models.job import Job, JobStatus
from app.models.pipeline_template import (
    PipelineTemplate,
    RejectionReason,
    TerminalType,
)
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User, UserRole
from app.services import interview_slots
from app.services.interview_cycle import interview_badges_for_job
from app.services.interview_slot_requests import create_slot_request_for_pair
from app.services.recruitment_process_commands import transition_process
from scripts.cancel_open_slots_on_closed_cards import closed_card_open_requests

pytestmark = pytest.mark.asyncio


def _slots() -> list[dict]:
    start = datetime.now(timezone.utc) + timedelta(days=3)
    return [
        {
            "start": start.isoformat(),
            "end": (start + timedelta(hours=1)).isoformat(),
        }
    ]


async def _seed(status: str = SLOT_STATUS_AWAITING_RECRUITER) -> dict:
    """Para na „Rozmowie z klientem” z wnioskiem w danym stanie."""
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"SlotClosedClient-{tag}")
        dl = User(
            email=f"slot-closed-{tag}@example.com",
            password_hash=hash_password(f"Dl_{tag}!pw9"),
            name=f"DL {tag}",
            role=UserRole.delivery_lead,
            roles=[UserRole.delivery_lead.value],
            is_active=True,
            profile_completed=True,
        )
        db.add_all([client, dl])
        await db.flush()
        job = Job(
            title=f"SlotClosedJob-{tag}",
            status=JobStatus.published,
            client_id=client.id,
            delivery_lead_id=dl.id,
        )
        cand = Candidate(
            name="Ola",
            lastname=f"Karta-{tag}",
            email=f"slot-closed-cand-{tag}@example.com",
            status=CandidateStatus.active,
        )
        template = PipelineTemplate(name=f"SlotClosedTemplate-{tag}")
        db.add_all([job, cand, template])
        await db.flush()
        resigned = RejectionReason(
            template_id=template.id,
            name=f"Kandydat zrezygnował {tag}",
            category=TerminalType.withdrawn,
        )
        db.add(resigned)
        await db.flush()
        await transition_process(
            db,
            candidate_id=cand.id,
            job_id=job.id,
            stage=PipelineStage.client_interview,
            actor_user_id=dl.id,
        )
        req = ClientInterviewSlotRequest(
            candidate_id=cand.id,
            job_id=job.id,
            client_id=client.id,
            created_by=dl.id,
            recruiter_id=dl.id,
            slots=_slots(),
            status=status,
            chosen_index=None if status == SLOT_STATUS_AWAITING_RECRUITER else 0,
        )
        db.add(req)
        await db.commit()
        return {
            "candidate_id": cand.id,
            "job_id": job.id,
            "request_id": req.id,
            "dl_id": dl.id,
            "reason_id": resigned.id,
        }


async def _move(pair: dict, stage: PipelineStage) -> None:
    async with AsyncSessionLocal() as db:
        await transition_process(
            db,
            candidate_id=pair["candidate_id"],
            job_id=pair["job_id"],
            stage=stage,
            actor_user_id=pair["dl_id"],
            rejection_reason_id=pair["reason_id"]
            if stage == PipelineStage.withdrawn
            else None,
        )
        await db.commit()


async def _status(pair: dict) -> str:
    async with AsyncSessionLocal() as db:
        req = await db.get(ClientInterviewSlotRequest, pair["request_id"])
        return req.status


@pytest.mark.parametrize("closing", [PipelineStage.rejected, PipelineStage.withdrawn])
@pytest.mark.parametrize(
    "status", [SLOT_STATUS_AWAITING_RECRUITER, SLOT_STATUS_AWAITING_DL]
)
async def test_closing_the_card_cancels_the_open_request(closing, status):
    pair = await _seed(status)
    await _move(pair, closing)
    assert await _status(pair) == SLOT_STATUS_CANCELLED


@pytest.mark.parametrize(
    "stage",
    [PipelineStage.acceptance, PipelineStage.hired, PipelineStage.cv_sent],
)
async def test_other_moves_leave_the_open_request(stage):
    pair = await _seed()
    await _move(pair, stage)
    assert await _status(pair) == SLOT_STATUS_AWAITING_RECRUITER


async def test_closing_the_card_leaves_a_confirmed_request():
    """Potwierdzony termin ma rozmowę w kalendarzu: to osobna decyzja, nie wniosek."""
    pair = await _seed(SLOT_STATUS_CONFIRMED)
    await _move(pair, PipelineStage.rejected)
    assert await _status(pair) == SLOT_STATUS_CONFIRMED


async def test_closed_card_has_no_slot_badge_and_no_pick():
    pair = await _seed()
    await _move(pair, PipelineStage.withdrawn)
    async with AsyncSessionLocal() as db:
        badges = await interview_badges_for_job(
            db, job_id=pair["job_id"], candidate_ids=[pair["candidate_id"]]
        )
        assert pair["candidate_id"] not in badges
        req = await interview_slots.lock_request(db, pair["request_id"])
        with pytest.raises(HTTPException) as exc:
            interview_slots.choose(req, 0, user_id=pair["dl_id"])
        assert exc.value.status_code == 409


async def test_returning_card_can_get_new_slots_without_conflict():
    pair = await _seed()
    await _move(pair, PipelineStage.rejected)
    await _move(pair, PipelineStage.client_interview)
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, pair["job_id"])
        dl = await db.get(User, pair["dl_id"])
        created = await create_slot_request_for_pair(
            db,
            job=job,
            candidate_id=pair["candidate_id"],
            slots=_slots(),
            duration_minutes=60,
            actor=dl,
        )
        await db.commit()
        assert created.request.status == SLOT_STATUS_AWAITING_RECRUITER
    assert await _status(pair) == SLOT_STATUS_CANCELLED


async def test_repair_finds_only_open_requests_on_closed_cards():
    """Stare wiersze sprzed reguły: etap wpisany bez ``transition_process``."""
    stale = await _seed()
    returned = await _seed()
    active = await _seed()
    async with AsyncSessionLocal() as db:
        for pair, stage in (
            (stale, PipelineStage.rejected),
            (returned, PipelineStage.rejected),
            (returned, PipelineStage.client_interview),
        ):
            db.add(
                CandidateStage(
                    candidate_id=pair["candidate_id"],
                    job_id=pair["job_id"],
                    stage=stage,
                    moved_at=datetime.now(timezone.utc),
                )
            )
            await db.flush()
        await db.commit()
    async with AsyncSessionLocal() as db:
        found = {req.id for req in await closed_card_open_requests(db)}
    assert stale["request_id"] in found
    assert returned["request_id"] not in found
    assert active["request_id"] not in found
