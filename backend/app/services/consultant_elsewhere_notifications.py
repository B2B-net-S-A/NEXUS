"""Dzwonek „nasz konsultant w innej rekrutacji" (12.10.2026, decyzje D3 i D4).

Znacznik „Pracuje u nas" (``services/employment_marker``) mówi rekruterowi,
że dodaje do rekrutacji osobę, która u nas pracuje. Delivery Lead klienta,
u którego ta osoba pracuje, dowiaduje się o tym dopiero tutaj — w dwóch
chwilach, w których sprawa przestaje być wewnętrzna:

* karta wchodzi do kolumny **„CV wysłane"** w rekrutacji u innego klienta
  (raz na parę osoba–rekrutacja, żeby cofnięcie i ponowne wysłanie nie
  dzwoniło drugi raz),
* osoba zostaje **zatrudniona** w rekrutacji u innego klienta — z odpowiedzią
  rekrutera na pytanie „Co z obecną współpracą?" z okna zatrudnienia. Też raz
  na parę (od 14.10.2026, audyt 13.10): cofnięcie z „Zatrudniony” i ponowne
  zatrudnienie dzwoniło drugi raz. Wcześniejszy dzwonek o „CV wysłane” go
  nie zastępuje.

Samo dodanie do rekrutacji nie dzwoni. Dzwonek niczego nie zmienia w umowach
ani zamówieniach — zakończenie współpracy dalej zaczyna się w oknie
zakończenia (``/terminate``).

Odbiorcy: Delivery Leadzi klienta, a gdy żaden nie może dostać tego typu —
admini (``DeliveryAlertRecipientScope.bell_recipients``). Autor ruchu nie
dzwoni sam do siebie; odsiewamy go PO wyznaczeniu odbiorców, bo odsianie
przed dałoby zapas na adminów zawsze, gdy kartę rusza jedyny Delivery Lead.

Wołane z ``stage_notification_emitter.notify_stage_change`` — jedynego
miejsca, przez które przechodzi ruch pojedynczy, zbiorczy, automat i podpis
umowy w Generatorze. Po commicie ruchu i best-effort: błąd tutaj nie cofa
ruchu karty.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Literal, Optional

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_today
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job
from app.models.notification import Notification, NotificationType
from app.models.pipeline_template import PipelineStageDef, TerminalType
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User
from app.schemas.candidate import EmploymentMarker, EmploymentMarkerClient
from app.services.board_stage_badges import board_column_for
from app.services.client_identity import client_display_name_expression
from app.services.delivery_alert_recipients import (
    DeliveryAlertRecipientScope,
    load_delivery_alert_recipient_scope,
)
from app.services.employment_marker import job_client_family, load_employment_markers
from app.services.notification_triggers import emit
from app.services.stage_handoff_recipients import CV_SENT_COLUMN

logger = logging.getLogger(__name__)

EVENT_CV_SENT = "cv_sent"
EVENT_HIRED = "hired"
StageEvent = Literal["cv_sent", "hired"]

NOTIFICATION_TYPE = NotificationType.consultant_in_other_recruitment
RELATED_ENTITY = "candidate_stage"

#: Odpowiedzi z okna „Potwierdź zatrudnienie" (``StageMove.hired_current_engagement``).
HIRED_ENGAGEMENT_SENTENCE: dict[str, str] = {
    "switch": "Rekruter: przechodzi do nowego klienta, obecna współpraca się kończy.",
    "parallel": "Rekruter: będzie pracować równolegle u obu klientów.",
    "ask_delivery_lead": (
        "Rekruter nie wie, co z obecną współpracą — decyzja po Twojej stronie."
    ),
}
_NO_ANSWER_SENTENCE = "Nie podano, co z obecną współpracą."
_NOTHING_CHANGES_SENTENCE = (
    "Obecna umowa i zamówienie zostają bez zmian, dopóki ich nie zakończysz."
)


def _value(raw: object) -> Optional[str]:
    value = getattr(raw, "value", raw)
    return value if isinstance(value, str) else None


def stage_event(
    new_def: Optional[PipelineStageDef],
    previous_def: Optional[PipelineStageDef],
    *,
    stage_code: Optional[str],
) -> Optional[StageEvent]:
    """Czy wejście na ten etap to „CV wysłane" albo zatrudnienie — ruch w przód.

    „CV wysłane" rozpoznajemy po KOLUMNIE Tablicy, nie po kodzie etapu: etapy
    z szablonów przeniesionych z Traffita mają inne kody. Wiersz bez definicji
    etapu (stary zapis) czytamy z samego kodu.
    """
    if new_def is None:
        if stage_code in (EVENT_HIRED, EVENT_CV_SENT):
            return stage_code  # type: ignore[return-value]
        return None
    if previous_def is not None and previous_def.order >= new_def.order:
        return None
    terminal_type = _value(new_def.terminal_type)
    code = stage_code or new_def.legacy_enum_value
    if terminal_type == EVENT_HIRED or code == EVENT_HIRED:
        return EVENT_HIRED
    column = board_column_for(
        new_def.name,
        code,
        category=_value(new_def.category),
        terminal_type=terminal_type,
    )
    return EVENT_CV_SENT if column == CV_SENT_COLUMN else None


def clients_elsewhere(
    marker: Optional[EmploymentMarker], family: Optional[set[int]]
) -> list[EmploymentMarkerClient]:
    """Klienci znacznika spoza rodziny klienta rekrutacji."""
    if marker is None:
        return []
    family = family or set()
    return [
        client
        for client in marker.clients
        if client.client_id is not None and client.client_id not in family
    ]


def employment_phrase(clients: list[EmploymentMarkerClient]) -> str:
    """„Pracuje u nas u klienta A, B i zaczyna u klienta C od 01.11.2026." """
    working = [c for c in clients if c.phase != "starting"]
    starting = [c for c in clients if c.phase == "starting"]
    parts: list[str] = []
    if working:
        names = ", ".join(c.client_name or f"#{c.client_id}" for c in working)
        parts.append(f"pracuje u nas u klienta {names}")
    if starting:
        names = ", ".join(
            (c.client_name or f"#{c.client_id}")
            + (f" od {c.starts_on.strftime('%d.%m.%Y')}" if c.starts_on else "")
            for c in starting
        )
        parts.append(f"zaczyna u klienta {names}")
    sentence = " i ".join(parts)
    return sentence[:1].upper() + sentence[1:] + "."


def bell_content(
    *,
    event: StageEvent,
    candidate_name: str,
    clients: list[EmploymentMarkerClient],
    job_title: str,
    job_client_name: Optional[str],
    mover_name: Optional[str],
    hired_engagement: Optional[str],
) -> tuple[str, str]:
    """Tytuł i treść dzwonka — bez kwot, bez niczego poza tym, co mówi znacznik."""
    who = mover_name or "Ktoś z zespołu"
    where = f"„{job_title}”" + (f" ({job_client_name})" if job_client_name else "")
    employment = employment_phrase(clients)
    if event == EVENT_HIRED:
        answer = HIRED_ENGAGEMENT_SENTENCE.get(
            hired_engagement or "", _NO_ANSWER_SENTENCE
        )
        return (
            f"Zatrudnienie w innej rekrutacji: {candidate_name}",
            f"{who} oznaczył(a) zatrudnienie osoby {candidate_name} w rekrutacji "
            f"{where}. {employment} {answer} {_NOTHING_CHANGES_SENTENCE}",
        )
    return (
        f"CV wysłane do innego klienta: {candidate_name}",
        f"{who} wysłał(a) CV osoby {candidate_name} w rekrutacji {where}. {employment}",
    )


async def _stage_event_for(
    db: AsyncSession,
    new_stage: CandidateStage,
    previous_stage: Optional[CandidateStage],
) -> Optional[StageEvent]:
    code = _value(new_stage.stage)
    def_ids = {
        stage.stage_def_id
        for stage in (new_stage, previous_stage)
        if stage is not None and stage.stage_def_id is not None
    }
    defs: dict[int, PipelineStageDef] = {}
    if def_ids:
        rows = await db.execute(
            select(PipelineStageDef).where(PipelineStageDef.id.in_(def_ids))
        )
        defs = {row.id: row for row in rows.scalars().all()}
    new_def = defs.get(new_stage.stage_def_id) if new_stage.stage_def_id else None
    previous_def = (
        defs.get(previous_stage.stage_def_id)
        if previous_stage is not None and previous_stage.stage_def_id
        else None
    )
    return stage_event(new_def, previous_def, stage_code=code)


async def _already_rang_for_pair(
    db: AsyncSession, *, candidate_id: int, job_id: int, event: StageEvent
) -> set[int]:
    """Odbiorcy, którzy dostali już ten dzwonek dla tej pary osoba–rekrutacja.

    Przy zatrudnieniu liczy się tylko dzwonek o zatrudnieniu (wiersz etapu
    „Zatrudniony”, ta sama definicja co w :func:`stage_event`) — dzwonek
    o „CV wysłane” nie niesie odpowiedzi „Co z obecną współpracą?”.
    """
    stmt = (
        select(Notification.user_id)
        .join(CandidateStage, CandidateStage.id == Notification.related_entity_id)
        .where(
            Notification.notification_type == NOTIFICATION_TYPE,
            Notification.related_entity_type == RELATED_ENTITY,
            CandidateStage.candidate_id == candidate_id,
            CandidateStage.job_id == job_id,
        )
    )
    if event == EVENT_HIRED:
        stmt = stmt.outerjoin(
            PipelineStageDef, PipelineStageDef.id == CandidateStage.stage_def_id
        ).where(
            or_(
                CandidateStage.stage == PipelineStage.hired,
                PipelineStageDef.terminal_type == TerminalType.hired,
            )
        )
    rows = await db.execute(stmt)
    return set(rows.scalars().all())


async def employed_elsewhere_client_ids(
    db: AsyncSession, *, candidate_id: int, job: Job
) -> list[int]:
    """Klienci spoza rodziny klienta rekrutacji, u których osoba ma sygnał
    zatrudnienia — żeby odpowiedź z okna zatrudnienia zapisać tylko wtedy,
    gdy pytanie miało sens."""
    if job.client_id is None:
        return []
    markers = await load_employment_markers(
        db, [candidate_id], today=business_today(), job_client_id=job.client_id
    )
    family = await job_client_family(db, job.client_id)
    return sorted(
        {
            client.client_id
            for client in clients_elsewhere(markers.get(candidate_id), family)
            if client.client_id is not None
        }
    )


async def notify_current_client_leads(
    db: AsyncSession,
    *,
    new_stage: CandidateStage,
    previous_stage: Optional[CandidateStage],
    job: Job,
    candidate: Candidate,
    mover: Optional[User],
    hired_engagement: Optional[str] = None,
    scope: Optional[DeliveryAlertRecipientScope] = None,
) -> int:
    """Dzwonek do Delivery Leadów klienta, u którego osoba pracuje.

    Zwraca liczbę wysłanych dzwonków. Nie rzuca — wołający jest efektem po
    commicie ruchu karty.
    """
    try:
        # Savepoint: w tej samej sesji idą potem zwykłe dzwonki ruchu, a po
        # nieudanym zapytaniu bez niego transakcja zostaje przerwana.
        async with db.begin_nested():
            return await _notify(
                db,
                new_stage=new_stage,
                previous_stage=previous_stage,
                job=job,
                candidate=candidate,
                mover=mover,
                hired_engagement=hired_engagement,
                scope=scope,
            )
    except Exception as exc:  # noqa: BLE001 — dzwonek nie może zepsuć ruchu
        logger.warning(
            "consultant_elsewhere: failed for stage=%s: %s",
            new_stage.id,
            type(exc).__name__,
        )
        return 0


async def _notify(
    db: AsyncSession,
    *,
    new_stage: CandidateStage,
    previous_stage: Optional[CandidateStage],
    job: Job,
    candidate: Candidate,
    mover: Optional[User],
    hired_engagement: Optional[str],
    scope: Optional[DeliveryAlertRecipientScope],
) -> int:
    if job.client_id is None:
        return 0
    event = await _stage_event_for(db, new_stage, previous_stage)
    if event is None:
        return 0
    markers = await load_employment_markers(
        db, [candidate.id], today=business_today(), job_client_id=job.client_id
    )
    family = await job_client_family(db, job.client_id)
    elsewhere = clients_elsewhere(markers.get(candidate.id), family)
    if not elsewhere:
        return 0

    scope = scope or await load_delivery_alert_recipient_scope(db)
    by_recipient: dict[int, list[EmploymentMarkerClient]] = defaultdict(list)
    for client in elsewhere:
        for user_id in scope.bell_recipients(client.client_id, NOTIFICATION_TYPE):
            by_recipient[user_id].append(client)
    if mover is not None:
        by_recipient.pop(mover.id, None)
    if by_recipient:
        for user_id in await _already_rang_for_pair(
            db, candidate_id=candidate.id, job_id=job.id, event=event
        ):
            by_recipient.pop(user_id, None)
    if not by_recipient:
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
    job_title = getattr(job, "working_title", None) or job.title
    mover_name = mover.name if mover is not None else None
    stage_id = new_stage.id
    link = f"/jobs/{job.id}?candidate={candidate.id}"
    sent = 0
    for user_id, clients in by_recipient.items():
        title, message = bell_content(
            event=event,
            candidate_name=candidate_name,
            clients=clients,
            job_title=job_title,
            job_client_name=job_client_name,
            mover_name=mover_name,
            hired_engagement=hired_engagement,
        )
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
