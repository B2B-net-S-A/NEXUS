"""Pas „Czeka na odpowiedź klienta” (S-C2, 08.11.2026).

Bramka jak przy zamknięciu rekrutacji: ``RecruitmentManageUser`` i zakres Delivery
Leada. ``Przypomnij klientowi`` niczego nie wysyła, zwraca treść dla DL-a.

Uwaga: moduł bez ``from __future__ import annotations`` — FastAPI czyta adnotacje
w czasie rejestracji trasy.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import HeadOfRecruitmentPlus, get_db
from app.api.permission_access import RecruitmentManageUser
from app.api.recruitment_access import ensure_delivery_lead_job_visible
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.models.contact import Contact
from app.models.job import Job
from app.services import client_panel as panel_service
from app.services import client_wait
from app.services.job_working_title import display_title

router = APIRouter(dependencies=PIPELINE_SECTION_DEPENDENCIES)


class ReminderIn(BaseModel):
    candidate_ids: Optional[list[int]] = Field(None, max_length=200)


class SettingsIn(BaseModel):
    auto_close: bool


async def _visible_job(db: AsyncSession, job_id: int, user) -> Job:
    job = await db.scalar(select(Job).where(Job.id == job_id))
    if job is None:
        raise HTTPException(status_code=404, detail="Nie znaleziono rekrutacji.")
    await ensure_delivery_lead_job_visible(job, user, db)
    return job


@router.get("/jobs/{job_id}")
async def get_client_wait(
    job_id: int,
    current_user: RecruitmentManageUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    job = await _visible_job(db, job_id, current_user)
    return client_wait.wait_payload(await client_wait.load_wait(db, job))


@router.post("/jobs/{job_id}/reminder")
async def prepare_client_reminder(
    job_id: int,
    body: ReminderIn,
    current_user: RecruitmentManageUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Gotowa wiadomość dla DL-a. Z NEXUSA nic nie idzie do klienta."""
    job = await _visible_job(db, job_id, current_user)
    wait = await client_wait.load_wait(db, job)
    wanted = set(body.candidate_ids) if body.candidate_ids else None
    people = [
        p
        for p in wait.people
        if (p.candidate_id in wanted if wanted is not None else p.needs_action)
    ]
    if not people:
        raise HTTPException(
            status_code=422, detail="Nikt nie czeka na odpowiedź klienta."
        )
    panel_url: Optional[str] = None
    if wait.panel_enabled:
        panel = await panel_service.panel_for_job(db, job_id)
        token = panel_service.current_token(panel) if panel else None
        if token:
            panel_url = panel_service.panel_urls(token)[0]
    subject, text = client_wait.reminder_text(
        job_title=display_title(job),
        people=people,
        panel_url=panel_url,
        sender_name=current_user.name,
    )
    to_email = None
    if job.hiring_manager_contact_id is not None:
        contact = await db.get(Contact, job.hiring_manager_contact_id)
        to_email = contact.email if contact is not None else None
    client_wait.mark(
        db,
        job_id,
        client_wait.ACTION_REMINDED,
        [p.candidate_id for p in people],
        current_user.id,
    )
    await db.commit()
    return {
        "subject": subject,
        "body": text,
        "to_email": to_email,
        "panel_url": panel_url,
        "people": len(people),
    }


@router.post("/jobs/{job_id}/candidates/{candidate_id}/responded")
async def mark_client_responded(
    job_id: int,
    candidate_id: int,
    current_user: RecruitmentManageUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """„Klient odpowiedział, ale decyzji jeszcze nie ma”: zegar liczy się od nowa."""
    job = await _visible_job(db, job_id, current_user)
    wait = await client_wait.load_wait(db, job)
    if candidate_id not in {p.candidate_id for p in wait.people}:
        raise HTTPException(status_code=404, detail="Ta osoba nie czeka na klienta.")
    client_wait.mark(
        db, job_id, client_wait.ACTION_RESPONDED, [candidate_id], current_user.id
    )
    await db.commit()
    return {"candidate_id": candidate_id, "ok": True}


@router.get("/settings")
async def get_client_wait_settings(
    current_user: RecruitmentManageUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    return (await client_wait.read_settings(db)).as_dict()


@router.put("/settings")
async def put_client_wait_settings(
    body: SettingsIn,
    current_user: HeadOfRecruitmentPlus,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Automatyczne zamykanie po 30 dniach: włącza Head of Recruitment albo admin."""
    value = await client_wait.write_settings(
        db, body.auto_close, user_id=current_user.id
    )
    await db.commit()
    return value.as_dict()
