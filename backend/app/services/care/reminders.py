"""Dzienny przebieg opieki (``run_once``) — plan, przypomnienia, przepięcia.

Jeden przebieg na dzień kalendarza firmy (rezerwacja w ``hr_job_runs``,
``kind = care_reminders``), więc nocny restart przy wdrożeniu niczego nie
powtarza. Dla każdego aktywnego kontraktu:

1. dopisuje brakujące punkty planu kontaktów (``plan.ensure_plan``),
2. zaległy albo dzisiejszy kontakt (punkt planu albo follow-up z ostatniej
   rozmowy) → dzwonek ``care_contact_due`` do opiekuna, najwyżej raz na
   7 dni na kontrakt,
3. koniec projektu < 60 dni z karty albo rozmowy → wpis „Do przepięcia”.

Błędy Compassa, których nie przenosimy: „dziś” w UTC (follow-up liczył
termin od północy UTC), HTTP 200 z ``ok: false`` przy awarii (tu przebieg
kończy się statusem ``failed`` w ``hr_job_runs`` i można go ponowić) oraz
stempel przed wysyłką.

Follow-up dzwoni najwyżej ``plan.LOOKBACK_DAYS`` po terminie — jak punkty
planu: rozmowy z importu niosą terminy sprzed lat i bez tej granicy każda
dzwoniłaby co 7 dni bez końca.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any, Optional

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_today, local_now
from app.models.contract_care import CareConversation, CarePlanItem
from app.models.hr_ops import HrJobRun
from app.models.notification import Notification, NotificationType
from app.services.care import access as care_access
from app.services.care import plan as care_plan
from app.services.care import records
from app.services.hr import modules as hr_modules
from app.services.notification_triggers import emit

logger = logging.getLogger(__name__)

JOB_KIND = "care_reminders"
REMINDER_EVERY_DAYS = 7
#: Rezerwacja starsza niż tyle bez zakończenia = przebieg przerwany, wolno ponowić.
STALE_CLAIM = timedelta(hours=1)


def contract_link(contract_id: int) -> str:
    return f"/contracts/{contract_id}?tab=care"


async def _claim(db: AsyncSession, period_key: str) -> Optional[int]:
    """Rezerwacja przebiegu: nowa, po awarii albo po przerwanym przebiegu."""

    row = await db.execute(
        text(
            "INSERT INTO hr_job_runs (kind, period_key, status) "
            "VALUES (:kind, :period, 'claimed') "
            "ON CONFLICT (kind, period_key) DO UPDATE "
            "SET status = 'claimed', claimed_at = now(), error = NULL, finished_at = NULL "
            "WHERE hr_job_runs.status = 'failed' "
            "OR (hr_job_runs.status = 'claimed' AND hr_job_runs.claimed_at < :stale) "
            "RETURNING id"
        ),
        {"kind": JOB_KIND, "period": period_key, "stale": local_now() - STALE_CLAIM},
    )
    claimed = row.scalar_one_or_none()
    await db.commit()
    return claimed


async def _finish(
    db: AsyncSession,
    run_id: int,
    *,
    status: str,
    counts: dict[str, Any],
    error: Optional[str] = None,
) -> None:
    await db.execute(
        update(HrJobRun)
        .where(HrJobRun.id == run_id)
        .values(status=status, counts=counts, error=error, finished_at=func.now())
    )
    await db.commit()


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


async def _due_follow_ups(
    db: AsyncSession, contract_ids: list[int], today: date
) -> dict[int, date]:
    """Follow-up z OSTATNIEJ rozmowy, którego termin minął (nowsza rozmowa go
    zamyka), nie dawniej niż ``plan.LOOKBACK_DAYS`` temu."""

    if not contract_ids:
        return {}
    latest = (
        select(
            CareConversation.contract_id,
            CareConversation.follow_up_on,
            func.row_number()
            .over(
                partition_by=CareConversation.contract_id,
                order_by=(
                    CareConversation.occurred_on.desc(),
                    CareConversation.id.desc(),
                ),
            )
            .label("rank"),
        )
        .where(CareConversation.contract_id.in_(contract_ids))
        .subquery()
    )
    rows = (
        await db.execute(
            select(latest.c.contract_id, latest.c.follow_up_on).where(
                latest.c.rank == 1,
                latest.c.follow_up_on.is_not(None),
                latest.c.follow_up_on <= today,
                latest.c.follow_up_on
                >= today - timedelta(days=care_plan.LOOKBACK_DAYS),
            )
        )
    ).all()
    return {contract_id: follow_up for contract_id, follow_up in rows}


def reminder_message(
    contract: care_access.CareContract,
    item: Optional[CarePlanItem],
    follow_up: Optional[date],
    today: date,
) -> str:
    if item is not None:
        label = care_plan.KIND_LABELS.get(item.kind, "Kontakt")
        when = (
            "dziś"
            if item.due_on == today
            else f"termin {item.due_on.strftime('%d.%m')}"
        )
        return f"{contract.label}: {label.lower()} — {when}."
    assert follow_up is not None
    when = "dziś" if follow_up == today else f"termin {follow_up.strftime('%d.%m')}"
    return f"{contract.label}: umówiony kolejny kontakt — {when}."


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
    follow_ups = await _due_follow_ups(db, ids, today)
    candidates = [c for c in contracts if c.id in due or c.id in follow_ups]
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
        async with db.begin_nested():
            created = await emit(
                db,
                user_id=owner,
                title="Kontakt z konsultantem",
                message=reminder_message(
                    contract, due.get(contract.id), follow_ups.get(contract.id), today
                ),
                ntype=NotificationType.care_contact_due,
                related_entity_type="contract",
                related_entity_id=contract.id,
                link=contract_link(contract.id),
            )
        if created is not None:
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
    if not loaded.get("care"):
        return {"status": "disabled"}
    today = business_today()
    run_id = await _claim(db, today.isoformat())
    if run_id is None:
        return {"status": "skipped", "period": today.isoformat()}
    counts: dict[str, Any] = {"plan_items": 0, "project_end_active": 0}
    try:
        contracts = await care_access.live_contracts(db)
        for contract in contracts:
            counts["plan_items"] += await care_plan.ensure_plan(
                db,
                contract.id,
                start=contract.start_date,
                end=contract.end_date,
                today=today,
            )
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
        await _finish(
            db, run_id, status="failed", counts=counts, error=type(exc).__name__
        )
        return {"status": "failed", **counts}
    await _finish(db, run_id, status="done", counts=counts)
    return {"status": "done", **counts}
