"""Karta „Zatrudniony” bez umowy w Kontraktach (17.10.2026).

Decyzja Artura: „Pracuje u nas” liczy się wyłącznie z umowy — z niej czyta
się też stawkę i termin dostępności. Podpis w Generatorze tworzy umowę od
razu, ale ręczne „Potwierdź zatrudnienie” (umowa B2B poza Generatorem, umowa
o pracę, zlecenie) zostawia osobę bez umowy, dopóki Delivery jej nie wpisze.
Do 17.10 takie zatrudnienie dawało znacznik przez 12 miesięcy; teraz:

* karta na Tablicy niesie ``missing_contract`` — plakietka „Brak umowy
  w Kontraktach” (:func:`missing_contract_ids`, tylko zatrudnienia z ostatnich
  ``MISSING_CONTRACT_HIRE_DAYS`` dni — starsze to historia z czasów Traffita);
* Delivery Leadzi klienta rekrutacji dostają dzwonek, raz na parę
  osoba–rekrutacja (:func:`notify_hire_without_contract`).

„Umowa” to każdy wpis w Kontraktach u klienta rekrutacji albo jego scalonych
rekordów poza unieważnionym — także szkic i umowa do podpisu: wtedy Delivery
już się nią zajmuje.

Wołane z ``stage_notification_emitter.notify_stage_change`` po commicie ruchu
i best-effort: błąd tutaj nie cofa ruchu karty.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Collection, Iterable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus
from app.models.job import Job
from app.models.notification import Notification, NotificationType
from app.models.recruitment_pipeline import CandidateStage
from app.models.user import User
from app.services.client_identity import client_display_name_expression
from app.services.consultant_elsewhere_notifications import (
    EVENT_HIRED,
    stage_event_for,
)
from app.services.delivery_alert_recipients import (
    DeliveryAlertRecipientScope,
    load_delivery_alert_recipient_scope,
)
from app.services.employment_marker import job_client_family
from app.services.notification_triggers import emit

logger = logging.getLogger(__name__)

MISSING_CONTRACT_HIRE_DAYS = 365
NOTIFICATION_TYPE = NotificationType.hire_missing_contract
RELATED_ENTITY = "candidate_stage"


async def candidates_with_contract(
    db: AsyncSession, *, candidate_ids: Iterable[int], client_ids: Collection[int]
) -> set[int]:
    """Kto ma u tych klientów jakąkolwiek umowę poza unieważnioną."""
    ids = sorted({int(cid) for cid in candidate_ids})
    if not ids or not client_ids:
        return set()
    rows = await db.execute(
        select(Contract.candidate_id)
        .where(
            Contract.candidate_id.in_(ids),
            Contract.client_id.in_(sorted(client_ids)),
            Contract.status != ContractStatus.void,
        )
        .distinct()
    )
    return set(rows.scalars().all())


async def missing_contract_ids(
    db: AsyncSession,
    *,
    job_client_id: Optional[int],
    hired: Iterable[tuple[int, Optional[datetime]]],
    now: datetime,
) -> set[int]:
    """Osoby z kartą na „Zatrudniony” (``(candidate_id, moved_at)``) z ostatnich
    ``MISSING_CONTRACT_HIRE_DAYS`` dni bez umowy u klienta rekrutacji."""
    if job_client_id is None:
        return set()
    cutoff = now - timedelta(days=MISSING_CONTRACT_HIRE_DAYS)
    recent = {
        candidate_id
        for candidate_id, moved_at in hired
        if moved_at is not None and moved_at >= cutoff
    }
    if not recent:
        return set()
    family = await job_client_family(db, job_client_id) or {job_client_id}
    return recent - await candidates_with_contract(
        db, candidate_ids=recent, client_ids=family
    )


def bell_content(
    *,
    candidate_name: str,
    job_title: str,
    job_client_name: Optional[str],
    mover_name: Optional[str],
) -> tuple[str, str]:
    """Tytuł i treść dzwonka — bez kwot."""
    who = mover_name or "Ktoś z zespołu"
    where = f"„{job_title}”" + (f" ({job_client_name})" if job_client_name else "")
    return (
        f"Wpisz umowę: {candidate_name}",
        f"{who} potwierdził(a) zatrudnienie osoby {candidate_name} w rekrutacji "
        f"{where}. W Kontraktach nie ma jej umowy u tego klienta — „Pracuje "
        "u nas”, stawka i termin dostępności pojawią się dopiero po wpisaniu "
        "umowy.",
    )


async def notify_hire_without_contract(
    db: AsyncSession,
    *,
    new_stage: CandidateStage,
    previous_stage: Optional[CandidateStage],
    job: Job,
    candidate: Candidate,
    mover: Optional[User],
    scope: Optional[DeliveryAlertRecipientScope] = None,
) -> int:
    """Dzwonek do Delivery Leadów klienta rekrutacji. Zwraca liczbę wysłanych;
    nie rzuca — wołający jest efektem po commicie ruchu karty."""
    try:
        # Savepoint: w tej samej sesji idą potem zwykłe dzwonki ruchu.
        async with db.begin_nested():
            return await _notify(
                db,
                new_stage=new_stage,
                previous_stage=previous_stage,
                job=job,
                candidate=candidate,
                mover=mover,
                scope=scope,
            )
    except Exception as exc:  # noqa: BLE001 — dzwonek nie może zepsuć ruchu
        logger.warning(
            "hire_contract_reminder: failed for stage=%s: %s",
            new_stage.id,
            type(exc).__name__,
        )
        return 0


async def _already_rang_for_pair(
    db: AsyncSession, *, candidate_id: int, job_id: int
) -> set[int]:
    rows = await db.execute(
        select(Notification.user_id)
        .join(CandidateStage, CandidateStage.id == Notification.related_entity_id)
        .where(
            Notification.notification_type == NOTIFICATION_TYPE,
            Notification.related_entity_type == RELATED_ENTITY,
            CandidateStage.candidate_id == candidate_id,
            CandidateStage.job_id == job_id,
        )
    )
    return set(rows.scalars().all())


async def _notify(
    db: AsyncSession,
    *,
    new_stage: CandidateStage,
    previous_stage: Optional[CandidateStage],
    job: Job,
    candidate: Candidate,
    mover: Optional[User],
    scope: Optional[DeliveryAlertRecipientScope],
) -> int:
    if job.client_id is None:
        return 0
    if await stage_event_for(db, new_stage, previous_stage) != EVENT_HIRED:
        return 0
    family = await job_client_family(db, job.client_id) or {job.client_id}
    if candidate.id in await candidates_with_contract(
        db, candidate_ids=[candidate.id], client_ids=family
    ):
        return 0

    scope = scope or await load_delivery_alert_recipient_scope(db)
    recipients = set(scope.bell_recipients(job.client_id, NOTIFICATION_TYPE))
    if mover is not None:
        recipients.discard(mover.id)
    if recipients:
        recipients -= await _already_rang_for_pair(
            db, candidate_id=candidate.id, job_id=job.id
        )
    if not recipients:
        return 0

    candidate_name = (
        f"{candidate.name or ''} {candidate.lastname or ''}".strip()
        or f"Kandydat #{candidate.id}"
    )
    job_client_name = await db.scalar(
        select(client_display_name_expression()).where(Client.id == job.client_id)
    )
    # Wszystko, co czytamy z obiektów sesji, PRZED pierwszym `emit`: odrzucony
    # duplikat cofa savepoint, a to wygasza atrybuty załadowanych wierszy.
    title, message = bell_content(
        candidate_name=candidate_name,
        job_title=getattr(job, "working_title", None) or job.title,
        job_client_name=job_client_name,
        mover_name=mover.name if mover is not None else None,
    )
    stage_id = new_stage.id
    link = f"/jobs/{job.id}?candidate={candidate.id}"
    sent = 0
    for user_id in sorted(recipients):
        notification = await emit(
            db,
            user_id=user_id,
            title=title,
            message=message,
            ntype=NOTIFICATION_TYPE,
            related_entity_type=RELATED_ENTITY,
            related_entity_id=stage_id,
            link=link,
        )
        if notification is not None:
            sent += 1
    return sent
