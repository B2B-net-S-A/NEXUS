"""Założenie wniosku o terminy od klienta: wspólne dla DL-a i panelu klienta.

Ta sama droga z ``POST /interview-cycle/slots`` i z panelu klienta pod linkiem:
wiersz wniosku, karta jedzie na „Rozmowę u klienta”, dzwonek rekrutera i powrót
„Klient milczy”. Bramki ról i członkostwa zostają u wołającego, bo klient
z linku nie ma konta; aktorem jego wniosku jest Delivery Lead rekrutacji.

Wołający commituje sam (panel dokłada w tej samej transakcji swój wiersz)
i po commicie woła ``after_slot_request_commit``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client_interview_slot_request import (
    OPEN_SLOT_STATUSES,
    ClientInterviewSlotRequest,
)
from app.models.job import Job
from app.models.notification import NotificationType
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User
from app.services import interview_slots
from app.services.pipeline_auto_move import auto_advance, run_after_commit
from app.services.pipeline_realtime import broadcast_pipeline_changed

logger = logging.getLogger(__name__)


class SlotsAlreadyOpen(Exception):
    """Para ma już otwarty wniosek (częściowy UNIQUE). Transakcja jest cofnięta."""

    def __init__(self, open_request_id: Optional[int]) -> None:
        super().__init__("slots already open")
        self.open_request_id = open_request_id


@dataclass
class CreatedSlotRequest:
    request: ClientInterviewSlotRequest
    job_id: int
    actor: Optional[User]
    moved: Optional[CandidateStage] = None
    skip_reasons: list[str] = field(default_factory=list)


async def create_slot_request_for_pair(
    db: AsyncSession,
    *,
    job: Job,
    candidate_id: int,
    slots: list[dict],
    duration_minutes: int,
    respond_by: Optional[datetime] = None,
    note: Optional[str] = None,
    recruiter_id: Optional[int] = None,
    replaced: Optional[ClientInterviewSlotRequest] = None,
    actor: Optional[User],
) -> CreatedSlotRequest:
    """Zapisuje wniosek i jego skutki, bez commitu.

    ``actor`` = osoba, w której imieniu idzie wniosek. Bez niej (rekrutacja bez
    Delivery Leada, wniosek z panelu klienta) karta zostaje na miejscu: ruch bez
    autora nie miałby kogo zapisać w historii, a rekruter dostaje dzwonek.
    """
    job_id = job.id
    recruiter_id = (
        recruiter_id
        or (replaced.recruiter_id if replaced is not None else None)
        or await interview_slots.default_recruiter_id(
            db, candidate_id=candidate_id, job_id=job_id
        )
    )
    actor_id = actor.id if actor is not None else None
    req = ClientInterviewSlotRequest(
        candidate_id=candidate_id,
        job_id=job_id,
        client_id=job.client_id,
        created_by=actor_id,
        recruiter_id=recruiter_id,
        slots=slots,
        duration_minutes=duration_minutes,
        respond_by=respond_by,
        note=(note or "").strip() or None,
    )
    db.add(req)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        open_id = await db.scalar(
            select(ClientInterviewSlotRequest.id).where(
                ClientInterviewSlotRequest.candidate_id == candidate_id,
                ClientInterviewSlotRequest.job_id == job_id,
                ClientInterviewSlotRequest.status.in_(OPEN_SLOT_STATUSES),
            )
        )
        raise SlotsAlreadyOpen(open_id) from exc
    # Pipeline v4 (23.09.2026): terminy od klienta = kandydat JEST w rozmowie
    # u klienta. Karta jedzie tam sama — wyłącznie do przodu; proces zamknięty
    # albo karta już dalej zostają bez zmian.
    # Ruch jest dodatkiem do wniosku: jego awaria (savepoint) zostawia kartę
    # na miejscu i nie cofa terminów, które DL właśnie wpisał.
    # Runda 10 (F09): automat nie przeskakuje „CV wysłane” — para bez
    # wysłanego CV zostaje na miejscu (bramki QC CV i stawki DL sprawdza tylko
    # `/pipeline/move`), a terminy i tak się zapisują.
    moved = None
    skip_reasons: list[str] = []
    if actor_id is not None:
        try:
            async with db.begin_nested():
                moved = await auto_advance(
                    db,
                    candidate_id=candidate_id,
                    job_id=job_id,
                    target=PipelineStage.client_interview,
                    actor_user_id=actor_id,
                    source="interview_slots",
                    note="Auto: terminy od klienta",
                    skip_reasons=skip_reasons,
                )
        except Exception:  # noqa: BLE001 — ruch karty nie może wywrócić wniosku
            moved = None
            skip_reasons = []
            logger.exception(
                "interview slots: auto move to client_interview failed "
                "(candidate %s, job %s)",
                candidate_id,
                job_id,
            )
    await interview_slots.notify(
        db,
        user_id=recruiter_id,
        ntype=NotificationType.interview_slots_requested,
        req=req,
        title=(
            "Zmienione terminy rozmowy od klienta"
            if replaced is not None
            else "Terminy rozmowy od klienta"
        ),
        message=(
            f"{len(slots)} terminy rozmowy u klienta do ustalenia z kandydatem "
            f"({job.title})."
        ),
        actor_id=actor_id or 0,
        # Zmiana może przyjść tego samego dnia co pierwszy dzwonek.
        daily_dedup=replaced is None,
    )
    # 0371: terminy od klienta = klient się odezwał → „Klient milczy” wraca
    # do „Szukamy kandydatów”. Nigdy nie rzuca.
    from app.services.request_work_state import (  # noqa: PLC0415
        wake_on_client_response,
    )

    await wake_on_client_response(db, job_id=job_id, stage=None, reason="client_slots")
    return CreatedSlotRequest(
        request=req,
        job_id=job_id,
        actor=actor,
        moved=moved,
        skip_reasons=skip_reasons,
    )


async def after_slot_request_commit(
    db: AsyncSession, created: CreatedSlotRequest
) -> None:
    """Skutki po zatwierdzonym wniosku; bez ruchu karty nie ma czego ogłaszać."""
    if created.moved is None or created.actor is None:
        return
    # Live kanban: reszta zespołu odświeża tablicę (best-effort).
    await broadcast_pipeline_changed(db, created.job_id, created.actor.id)
    # Runda 7 (N7-4): powiadomienia o etapie i profil ryzyka — jak po
    # `/move`. Po commicie, nigdy nie rzuca.
    await run_after_commit(db, stage_id=created.moved.id, mover=created.actor)
