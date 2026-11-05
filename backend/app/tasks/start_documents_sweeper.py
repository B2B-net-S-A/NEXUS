"""Dokumenty do startu: przypomnienia (co godzinę, działa raz dziennie po 9:00).

* **Prowadzący**: jeden dzwonek zbiorczy z listą osób, w dni robocze. Od
  ``MAIL_FROM_WORKING_DAYS`` dni roboczych przed startem (i po terminie) typ
  ``start_documents_due``, który idzie też mailem.
* **Delivery Lead**: od ``DL_FROM_WORKING_DAYS`` dni roboczych przed startem.
* **Head of Recruitment**: w dniu startu bez kompletu.

Dzień i odbiorcę pilnuje indeks ``ix_notif_dedup_daily`` (``emit``), więc restart
pętli niczego nie wysyła drugi raz. Etap 1: bez wpływu na liczniki placementów.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.core.scheduling import local_now
from app.models.notification import NotificationType
from app.models.user import User, UserRole
from app.services import loop_heartbeat
from app.services import start_documents as svc
from app.services.hr.calendar import load_calendar
from app.services.notification_triggers import emit

logger = logging.getLogger(__name__)

INTERVAL_SECONDS = 3600
FIRST_HOUR = 9
#: Tyle osób wypisuje dzwonek, reszta to „i jeszcze N”.
_MAX_LISTED = 5
_ENTITY = "start_documents_digest"


def needs_mail(state: svc.PairState) -> bool:
    if state.tone == "late":
        return True
    days = state.working_days_to_start
    return days is not None and days <= svc.MAIL_FROM_WORKING_DAYS


def reaches_dl(state: svc.PairState) -> bool:
    days = state.working_days_to_start
    return state.working or (days is not None and days <= svc.DL_FROM_WORKING_DAYS)


def reaches_hor(state: svc.PairState, today: date) -> bool:
    return state.start_date == today


def digest_line(state: svc.PairState) -> str:
    missing = ", ".join(i.document.name for i in state.missing)
    start = f", start {state.start_date:%d.%m}" if state.start_date else ""
    return f"{state.candidate_name}: {missing}{start}"


def digest_message(states: Iterable[svc.PairState]) -> str:
    rows = list(states)
    lines = [digest_line(s) for s in rows[:_MAX_LISTED]]
    if len(rows) > _MAX_LISTED:
        lines.append(f"i jeszcze {len(rows) - _MAX_LISTED}")
    return "; ".join(lines)


def _title(count: int) -> str:
    return f"Dokumenty do startu: {count} bez kompletu"


async def _send(
    db: AsyncSession,
    *,
    user_id: int,
    states: list[svc.PairState],
    ntype: NotificationType,
) -> None:
    first = states[0]
    await emit(
        db,
        user_id=user_id,
        title=_title(len(states)),
        message=digest_message(states),
        ntype=ntype,
        related_entity_type=_ENTITY,
        related_entity_id=user_id,
        link=(
            f"/jobs/{first.job_id}?candidate={first.candidate_id}"
            if len(states) == 1
            else "/dashboard"
        ),
    )


async def run_once(now: datetime) -> dict[str, int]:
    """Jeden przebieg: w dzień wolny i przed 9:00 nic nie robi."""

    counts = {"owners": 0, "delivery_leads": 0, "heads": 0}
    today = now.date()
    if now.hour < FIRST_HOUR:
        return counts
    async with AsyncSessionLocal() as db:
        calendar = await load_calendar(db, today, today)
        if not calendar.is_working_day(today):
            return counts
        states = await svc.open_states(db)
        if not states:
            return counts

        by_owner: dict[int, list[svc.PairState]] = {}
        by_dl: dict[int, list[svc.PairState]] = {}
        for state in states:
            if state.owner_id is not None:
                by_owner.setdefault(state.owner_id, []).append(state)
            if (
                state.delivery_lead_id is not None
                and state.delivery_lead_id != state.owner_id
                and reaches_dl(state)
            ):
                by_dl.setdefault(state.delivery_lead_id, []).append(state)

        for user_id, rows in by_owner.items():
            due = any(needs_mail(s) for s in rows)
            await _send(
                db,
                user_id=user_id,
                states=rows,
                ntype=(
                    NotificationType.start_documents_due
                    if due
                    else NotificationType.start_documents
                ),
            )
            counts["owners"] += 1
        for user_id, rows in by_dl.items():
            await _send(
                db,
                user_id=user_id,
                states=rows,
                ntype=NotificationType.start_documents_due,
            )
            counts["delivery_leads"] += 1

        starting = [s for s in states if reaches_hor(s, today)]
        if starting:
            heads = await db.scalars(select(User).where(User.is_active.is_(True)))
            for head in heads.all():
                if head.has_role(UserRole.head_of_recruitment):
                    await _send(
                        db,
                        user_id=head.id,
                        states=starting,
                        ntype=NotificationType.start_documents_due,
                    )
                    counts["heads"] += 1
        await db.commit()
    return counts


async def start_documents_sweeper_loop() -> None:
    beat = loop_heartbeat.register(
        "start_documents_sweeper", max_silence_seconds=INTERVAL_SECONDS + 1800
    )
    while True:
        beat.tick()
        try:
            counts = await run_once(local_now())
            if any(counts.values()):
                logger.info("[start_documents] przypomnienia: %s", counts)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("[start_documents] przegląd nie powiódł się")
        await asyncio.sleep(INTERVAL_SECONDS)
