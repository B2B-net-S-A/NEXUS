"""Kroki po wysłaniu oferty: trzy zadania ustawiane przy wejściu na etap „Oferta wysłana”.

Dzień 3 potwierdzenie odbioru, dzień 14 pytanie o decyzję, dzień 30 rozstrzygnięcie
(decyzja Artura 10.11.2026). To zwykłe zadania opiekuna: da się je przełożyć, odhaczyć
albo usunąć, a moduł niczego sam nie wysyła. Autorem jest ta sama osoba co wykonawca,
bo zadanie usuwa tylko autor, a krok ma dać się usunąć opiekunowi także wtedy, gdy
szansę przesunął ktoś inny (kto przesunął, mówi historia szansy).

Kroków nie dostaje przetarg (``tender-submitted`` ma własne terminy) ani oferta, która
była na etapie przed wdrożeniem: zapis idzie tylko z wejścia na etap. Powrót na etap
nie dubluje kroków, dopóki któryś z poprzednich jest otwarty.

To nie są sekwencje do zimnego kontaktu (odłożone 09.11.2026 do opinii prawnej): kroki
dotyczą oferty już wysłanej osobie, z którą trwa rozmowa. Nie rozszerzaj ich na leady.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import DEFAULT_TZ, business_date, is_business_day
from app.models.sales import SalesActivity, SalesOpportunity
from app.models.user import User
from app.services.sales.kpi import OFFER_STAGE_KEY

#: Znacznik w ``external_source``: po nim widać, że krok ustawił NEXUS, a nie człowiek.
OFFER_STEP_SOURCE = "offer-step"
#: Rano w kalendarzu firmy, jak termin z okna „Co dalej i kiedy”.
STEP_HOUR = 9


@dataclass(frozen=True)
class StepTemplate:
    day: int
    subject: str


STEPS: tuple[StepTemplate, ...] = (
    StepTemplate(3, "Potwierdzić odbiór oferty"),
    StepTemplate(14, "Zapytać o decyzję w sprawie oferty"),
    StepTemplate(30, "Rozstrzygnąć ofertę: decyzja albo zamknięcie"),
)


def step_due_at(sent_on: date, day: int) -> datetime:
    """Termin kroku: ``day`` dni po wysłaniu, a z weekendu i święta na najbliższy dzień roboczy."""

    zone = ZoneInfo(DEFAULT_TZ)
    due = datetime.combine(sent_on + timedelta(days=day), time(STEP_HOUR), tzinfo=zone)
    while not is_business_day(due):
        due += timedelta(days=1)
    return due.astimezone(timezone.utc)


async def _assignee(
    db: AsyncSession, opportunity: SalesOpportunity, user_id: int
) -> int:
    """Opiekun szansy, a bez aktywnego opiekuna osoba, która przesunęła szansę."""

    if opportunity.owner_user_id is not None:
        owner_id = await db.scalar(
            select(User.id).where(
                User.id == opportunity.owner_user_id, User.is_active.is_(True)
            )
        )
        if owner_id is not None:
            return owner_id
    return user_id


async def schedule_on_entry(
    db: AsyncSession,
    opportunity: SalesOpportunity,
    stage_key: str,
    *,
    user_id: int,
    now: datetime,
) -> int:
    """Ustaw kroki po wejściu szansy na ``stage_key``; zwraca liczbę dodanych zadań."""

    if stage_key != OFFER_STAGE_KEY:
        return 0
    open_steps = await db.scalar(
        select(func.count())
        .select_from(SalesActivity)
        .where(
            SalesActivity.opportunity_id == opportunity.id,
            SalesActivity.external_source == OFFER_STEP_SOURCE,
            SalesActivity.done_at.is_(None),
        )
    )
    if open_steps:
        return 0
    assignee_id = await _assignee(db, opportunity, user_id)
    sent_on = business_date(now)
    db.add_all(
        SalesActivity(
            kind="task",
            company_id=opportunity.company_id,
            opportunity_id=opportunity.id,
            subject=step.subject,
            due_at=step_due_at(sent_on, step.day),
            assignee_user_id=assignee_id,
            created_by_user_id=assignee_id,
            external_source=OFFER_STEP_SOURCE,
        )
        for step in STEPS
    )
    return len(STEPS)
