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
   7 dni na kontrakt. Opiekun z kilkoma takimi kontraktami dostaje JEDEN
   zbiorczy dzwonek z linkiem do „Opieka → Do zrobienia” z filtrem (decyzja
   Artura 19.10.2026: pierwszy przebieg dał 472 dzwonki, jednemu DL 290),
   najwyżej raz na 7 dni — wcześniej tylko, gdy któryś kontakt wypada dziś.
   Linki (makieta R2, 22.10.2026): pojedynczy kontakt → karta konsultanta
   ``/care?contract=<id>``, zbiorczy → ``/care?filter=po-terminie`` (jest
   zaległy) albo ``/care?filter=do-piatku`` (same dzisiejsze),
3. koniec projektu < 60 dni z karty albo rozmowy → wpis „Do przepięcia”,
4. klient z konsultantami bez menedżera u klienta → dzwonek
   ``care_client_structure`` „uzupełnij strukturę klienta X” do jego Delivery
   Leadów, najwyżej raz na 7 dni (``structure_proposals.remind``). Awaria tego
   kroku nie cofa przypomnień opieki — liczniki mówią ``structure_failed``.

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
from app.services.care import structure_proposals
from app.services.hr import job_runs
from app.services.hr import modules as hr_modules
from app.services.hr.modules import HrModule
from app.services.hr.notify import notify_each

logger = logging.getLogger(__name__)

JOB_KIND = "care_reminders"
REMINDER_EVERY_DAYS = 7


#: Zbiorczy dzwonek opiekuna (``related_entity_id`` = id opiekuna).
DIGEST_ENTITY = "care_owner_digest"
DIGEST_LINK_OVERDUE = "/care?filter=po-terminie"
DIGEST_LINK_THIS_WEEK = "/care?filter=do-piatku"
DIGEST_NAMES = 3


def contract_link(contract_id: int) -> str:
    """Karta konsultanta w opiece (panel ``/care?contract=<id>``)."""

    return f"/care?contract={contract_id}"


def digest_link(
    contracts: list[care_access.CareContract],
    contacts: dict[int, care_plan.NextContact],
    today: date,
) -> str:
    """Zbiorczy dzwonek: „Po terminie”, gdy coś jest zaległe, inaczej „Do piątku”."""

    if any(contacts[contract.id].due_on < today for contract in contracts):
        return DIGEST_LINK_OVERDUE
    return DIGEST_LINK_THIS_WEEK


async def _recent_digests(
    db: AsyncSession, owner_ids: list[int], now: datetime
) -> set[int]:
    if not owner_ids:
        return set()
    rows = await db.scalars(
        select(Notification.related_entity_id).where(
            Notification.notification_type == NotificationType.care_contact_due,
            Notification.related_entity_type == DIGEST_ENTITY,
            Notification.related_entity_id.in_(owner_ids),
            Notification.created_at >= now - timedelta(days=REMINDER_EVERY_DAYS),
        )
    )
    return {int(value) for value in rows.all() if value is not None}


def digest_message(
    contracts: list[care_access.CareContract],
    contacts: dict[int, care_plan.NextContact],
    today: date,
) -> str:
    """„Do zrobienia: N — A, B, C i 4 inne; najstarszy termin 01.10.”"""

    ordered = sorted(contracts, key=lambda c: (contacts[c.id].due_on, c.id))
    names = ", ".join(contract.label for contract in ordered[:DIGEST_NAMES])
    rest = len(ordered) - DIGEST_NAMES
    if rest > 0:
        names += f" i {rest} {'inny' if rest == 1 else 'inne'}"
    oldest = contacts[ordered[0].id].due_on
    when = "dziś" if oldest == today else oldest.strftime("%d.%m")
    return (
        f"Do zrobienia: {len(ordered)} — {names}. Najstarszy termin: {when}. "
        "Lista w „Opieka → Do zrobienia”."
    )


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
    skipped = no_owner = 0
    by_owner: dict[int, list[care_access.CareContract]] = {}
    for contract in candidates:
        if contract.id in recent:
            skipped += 1
            continue
        owner = owners[contract.id].user_id
        if owner is None:
            no_owner += 1
            continue
        by_owner.setdefault(owner, []).append(contract)
    digested = await _recent_digests(
        db, [owner for owner, items in by_owner.items() if len(items) > 1], now
    )
    sent = digests = 0
    for owner, items in by_owner.items():
        if len(items) == 1:
            contract = items[0]
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
        elif owner in digested and not any(
            upcoming[contract.id].due_on == today for contract in items
        ):
            created = 0
        else:
            created = await notify_each(
                db,
                [owner],
                title="Kontakt z konsultantami",
                message=digest_message(items, upcoming, today),
                ntype=NotificationType.care_contact_due,
                related_entity_type=DIGEST_ENTITY,
                related_entity_id=owner,
                link=digest_link(items, upcoming, today),
                log_tag="care",
            )
            digests += int(bool(created))
        if created:
            sent += len(items)
        else:
            skipped += len(items)
    return {
        "due": len(candidates),
        "sent": sent,
        "skipped": skipped,
        "no_owner": no_owner,
        "digests": digests,
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
    counts: dict[str, Any] = {
        "plan_items": 0,
        "project_end_active": 0,
        "auto_owners": 0,
    }
    try:
        # Najpierw opiekun dla świeżych kontraktów bez opiekuna (pula
        # opiekunów), potem plan i przypomnienia — już do nowego opiekuna.
        from app.services.care import auto_assign  # noqa: PLC0415

        counts["auto_owners"] = await auto_assign.sweep(db, today=today)
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
        try:
            counts.update(await structure_proposals.remind(db, now=local_now()))
            await db.commit()
        except Exception as exc:  # noqa: BLE001 — dodatek do przebiegu, nie bramka
            await db.rollback()
            logger.exception("[care] dzwonki struktury u klienta nie powiodły się")
            counts["structure_failed"] = type(exc).__name__
    except Exception as exc:  # noqa: BLE001 — przebieg zapisuje porażkę i daje się ponowić
        await db.rollback()
        logger.exception("[care] dzienny przebieg nie powiódł się")
        await job_runs.finish(
            db, run_id, status="failed", counts=counts, error=type(exc).__name__
        )
        return {"status": "failed", **counts}
    await job_runs.finish(db, run_id, status="done", counts=counts)
    return {"status": "done", **counts}
