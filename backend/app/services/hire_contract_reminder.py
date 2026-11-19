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
from typing import Awaitable, Callable, Collection, Iterable, Mapping, Optional

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
from app.services.employment_marker import job_client_families, job_client_family
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


async def contract_client_ids(
    db: AsyncSession, *, candidate_ids: Iterable[int], client_ids: Collection[int]
) -> dict[int, set[int]]:
    """``{kandydat: {klient}}`` umów poza unieważnioną — jedno zapytanie dla
    wszystkich Tablic; przypisanie do rodziny rekrutacji robi wołający."""
    ids = sorted({int(cid) for cid in candidate_ids})
    if not ids or not client_ids:
        return {}
    out: dict[int, set[int]] = {}
    for candidate_id, client_id in (
        await db.execute(
            select(Contract.candidate_id, Contract.client_id)
            .where(
                Contract.candidate_id.in_(ids),
                Contract.client_id.in_(sorted(client_ids)),
                Contract.status != ContractStatus.void,
            )
            .distinct()
        )
    ).all():
        out.setdefault(candidate_id, set()).add(client_id)
    return out


#: Rodziny klientów rekrutacji: ``{client_id: rodzina | None}``.
FamiliesLoader = Callable[[list[int]], Awaitable[Mapping[int, Optional[set[int]]]]]


async def missing_contract_ids(
    db: AsyncSession,
    *,
    job_client_id: Optional[int],
    hired: Iterable[tuple[int, Optional[datetime]]],
    now: datetime,
    family_loader: Optional[Callable[[], Awaitable[Optional[set[int]]]]] = None,
) -> set[int]:
    """Osoby z kartą na „Zatrudniony” (``(candidate_id, moved_at)``) z ostatnich
    ``MISSING_CONTRACT_HIRE_DAYS`` dni bez umowy u klienta rekrutacji.

    ``family_loader`` — rodzina klienta liczona raz na Tablicę (znacznik
    „Pracuje u nas” potrzebuje tej samej)."""

    async def load_families(client_ids: list[int]) -> Mapping[int, Optional[set[int]]]:
        if family_loader is None:
            return await job_client_families(db, client_ids)
        return {client_id: await family_loader() for client_id in client_ids}

    # Jedna Tablica pod umownym kluczem — wołający nie podaje id rekrutacji.
    board = 0
    return (
        await _missing_for_boards(
            db,
            boards={board: (job_client_id, list(hired))},
            now=now,
            load_families=load_families,
        )
    )[board]


async def missing_contract_ids_for_jobs(
    db: AsyncSession,
    *,
    boards: Mapping[int, tuple[Optional[int], list[tuple[int, Optional[datetime]]]]],
    now: datetime,
    families: Optional[Mapping[int, Optional[set[int]]]] = None,
) -> dict[int, set[int]]:
    """:func:`missing_contract_ids` dla wielu Tablic: ``{job_id: (client_id
    rekrutacji, zatrudnieni z kartą)}`` → ``{job_id: osoby bez umowy}``.

    Zapytań tyle, co dla jednej Tablicy: rodziny klientów hurtem
    (:func:`job_client_families`) i jedno o umowy. ``families`` — rodziny
    policzone już przez wołającego (Tablica: też znacznik „Pracuje u nas”);
    brakujących klientów dociągamy."""

    async def load_families(client_ids: list[int]) -> Mapping[int, Optional[set[int]]]:
        known = {
            cid: families[cid] for cid in client_ids if families and cid in families
        }
        rest = [cid for cid in client_ids if cid not in known]
        if rest:
            known.update(await job_client_families(db, rest))
        return known

    return await _missing_for_boards(
        db, boards=boards, now=now, load_families=load_families
    )


async def _missing_for_boards(
    db: AsyncSession,
    *,
    boards: Mapping[int, tuple[Optional[int], list[tuple[int, Optional[datetime]]]]],
    now: datetime,
    load_families: FamiliesLoader,
) -> dict[int, set[int]]:
    out: dict[int, set[int]] = {job_id: set() for job_id in boards}
    cutoff = now - timedelta(days=MISSING_CONTRACT_HIRE_DAYS)
    recent_by_job: dict[int, tuple[int, set[int]]] = {}
    for job_id, (job_client_id, hired) in boards.items():
        if job_client_id is None:
            continue
        recent = {
            candidate_id
            for candidate_id, moved_at in hired
            if moved_at is not None and moved_at >= cutoff
        }
        if recent:
            recent_by_job[job_id] = (job_client_id, recent)
    if not recent_by_job:
        return out
    loaded = await load_families(
        sorted({client_id for client_id, _ in recent_by_job.values()})
    )
    family_by_job = {
        job_id: loaded.get(client_id) or {client_id}
        for job_id, (client_id, _) in recent_by_job.items()
    }
    contracted = await contract_client_ids(
        db,
        candidate_ids={cid for _, ids in recent_by_job.values() for cid in ids},
        client_ids={cid for family in family_by_job.values() for cid in family},
    )
    for job_id, (_, recent) in recent_by_job.items():
        family = family_by_job[job_id]
        out[job_id] = {
            cid for cid in recent if not (contracted.get(cid, set()) & family)
        }
    return out


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
        select(Notification.addressee_id)
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
