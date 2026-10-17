"""Dzienny przebieg opieki (``run_once``) — plan, przypomnienia, przepięcia.

Jeden przebieg na dzień kalendarza firmy (rezerwacja w ``hr_job_runs``,
``kind = care_reminders``), więc nocny restart przy wdrożeniu niczego nie
powtarza. Dla każdego aktywnego kontraktu:

1. dopisuje brakujące punkty planu kontaktów (``plan.ensure_plans`` —
   zbiorczo dla wszystkich kontraktów; listy opieki przy odczycie już tego
   nie robią) i zamyka punkty pokryte późniejszą rozmową, także z importu
   Compassa (``plan.close_covered``),
2. zaległy albo dzisiejszy kontakt (punkt planu albo follow-up z ostatniej
   rozmowy) → dzwonek ``care_contact_due`` do opiekuna, najwyżej raz na
   7 dni na kontrakt,
3. koniec projektu < 60 dni z karty albo rozmowy → wpis „Do przepięcia”.

Błędy Compassa, których nie przenosimy: „dziś” w UTC (follow-up liczył
termin od północy UTC), HTTP 200 z ``ok: false`` przy awarii (tu przebieg
kończy się statusem ``failed`` w ``hr_job_runs`` i można go ponowić) oraz
stempel przed wysyłką.

Termin to „następny kontakt” z ``plan.next_contact`` — ta sama reguła co na
karcie kontraktu: follow-up dzwoni najwyżej ``plan.LOOKBACK_DAYS`` po terminie,
bo rozmowy z importu niosą terminy sprzed lat i bez tej granicy każda
dzwoniłaby co 7 dni bez końca.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_today, local_now
from app.models.contract_care import CarePlanItem
from app.models.notification import Notification, NotificationType
from app.services.care import access as care_access
from app.services.care import plan as care_plan
from app.services.care import records
from app.services.hr import job_runs
from app.services.hr import modules as hr_modules
from app.services.hr.modules import HrModule
from app.services.hr.notify import notify_each

logger = logging.getLogger(__name__)

JOB_KIND = "care_reminders"
REMINDER_EVERY_DAYS = 7


def contract_link(contract_id: int) -> str:
    return f"/contracts/{contract_id}?tab=care"


async def _recently_reminded(
    db: AsyncSession, contract_ids: list[int], now: datetime
) -> set[int]:
    if not contract_ids:
        return set()
    rows = await db.scalars(
        select(Notification.related_entity_id).where(
            Notification.notification_type == NotificationType.care_contact_due,
            Notification.related_entity_type == "contract",
            Notification.related_entity_id.in_(contract_ids),
            Notification.created_at >= now - timedelta(days=REMINDER_EVERY_DAYS),
        )
    )
    return {int(value) for value in rows.all() if value is not None}


async def _due_items(
    db: AsyncSession, contract_ids: list[int], today: date
) -> dict[int, CarePlanItem]:
    """Najwcześniejszy zaległy (albo dzisiejszy) otwarty punkt planu per kontrakt."""

    if not contract_ids:
        return {}
    items = (
        await db.scalars(
            select(CarePlanItem)
            .where(
                CarePlanItem.contract_id.in_(contract_ids),
                CarePlanItem.status == "open",
                CarePlanItem.due_on <= today,
            )
            .order_by(CarePlanItem.contract_id, CarePlanItem.due_on, CarePlanItem.id)
        )
    ).all()
    out: dict[int, CarePlanItem] = {}
    for item in items:
        out.setdefault(item.contract_id, item)
    return out


def reminder_message(
    contract: care_access.CareContract, contact: care_plan.NextContact, today: date
) -> str:
    when = (
        "dziś"
        if contact.due_on == today
        else f"termin {contact.due_on.strftime('%d.%m')}"
    )
    if contact.kind == care_plan.FOLLOW_UP:
        return f"{contract.label}: umówiony kolejny kontakt — {when}."
    return f"{contract.label}: {contact.label.lower()} — {when}."


async def remind(
    db: AsyncSession,
    contracts: list[care_access.CareContract],
    *,
    today: date,
    now: datetime,
) -> dict[str, int]:
    """Dzwonki do opiekunów (bez commita). Zwraca liczniki."""

    ids = [contract.id for contract in contracts]
    due = await _due_items(db, ids, today)
    latest = await care_plan.latest_conversations(db, ids)
    upcoming: dict[int, care_plan.NextContact] = {}
    for contract in contracts:
        # Najwcześniejszy zaległy punkt wystarcza: późniejsze nie zmienią wyniku.
        item = due.get(contract.id)
        contact = care_plan.next_contact(
            [item] if item else [], latest.get(contract.id), today
        )
        if contact is not None and contact.due_on <= today:
            upcoming[contract.id] = contact
    candidates = [c for c in contracts if c.id in upcoming]
    recent = await _recently_reminded(db, [c.id for c in candidates], now)
    owners = await care_access.effective_owners(db, candidates)
    sent = skipped = no_owner = 0
    for contract in candidates:
        if contract.id in recent:
            skipped += 1
            continue
        owner = owners[contract.id].user_id
        if owner is None:
            no_owner += 1
            continue
        created = await notify_each(
            db,
            [owner],
            title="Kontakt z konsultantem",
            message=reminder_message(contract, upcoming[contract.id], today),
            ntype=NotificationType.care_contact_due,
            related_entity_type="contract",
            related_entity_id=contract.id,
            link=contract_link(contract.id),
            log_tag="care",
        )
        if created:
            sent += 1
        else:
            skipped += 1
    return {
        "due": len(candidates),
        "sent": sent,
        "skipped": skipped,
        "no_owner": no_owner,
    }


async def run_once(db: AsyncSession) -> dict[str, Any]:
    """Jeden przebieg dzienny (idempotentny). Wpięcie: pętla w ``app/main.py``."""

    loaded = await hr_modules.load_modules(db)
    if not loaded.get(HrModule.care):
        return {"status": "disabled"}
    today = business_today()
    run_id = await job_runs.claim(db, JOB_KIND, today.isoformat(), local_now())
    if run_id is None:
        return {"status": "skipped", "period": today.isoformat()}
    counts: dict[str, Any] = {"plan_items": 0, "project_end_active": 0}
    try:
        contracts = await care_access.live_contracts(db)
        counts["plan_items"] = await care_plan.ensure_plans(db, contracts, today=today)
        for contract in contracts:
            if await records.sync_project_end(
                db, contract.id, today=today, actor_id=None
            ):
                counts["project_end_active"] += 1
        await db.commit()
        counts.update(await remind(db, contracts, today=today, now=local_now()))
        await db.commit()
    except Exception as exc:  # noqa: BLE001 — przebieg zapisuje porażkę i daje się ponowić
        await db.rollback()
        logger.exception("[care] dzienny przebieg nie powiódł się")
        await job_runs.finish(
            db, run_id, status="failed", counts=counts, error=type(exc).__name__
        )
        return {"status": "failed", **counts}
    await job_runs.finish(db, run_id, status="done", counts=counts)
    return {"status": "done", **counts}
