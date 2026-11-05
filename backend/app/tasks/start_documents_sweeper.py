"""Dokumenty do startu: przypomnienia (co godzinę, działa raz dziennie po 9:00).

Liczy się termin pozycji, nie sam start, bo wyciąg z KRK idzie do 2 tygodni
i dostaje termin po starcie (wiadomość Delivery Leadów z 05.11.2026).

* **Prowadzący**: jeden dzwonek zbiorczy z listą osób, w dni robocze. Od
  ``MAIL_FROM_WORKING_DAYS`` dni roboczych przed terminem (i po nim) typ
  ``start_documents_due``, który idzie też mailem.
* **Delivery Lead**: od ``DL_FROM_WORKING_DAYS`` dni roboczych przed terminem.
* **Head of Recruitment**: w dniu startu z zaległością, a po starcie w dniu terminu.

Dzień i odbiorcę pilnuje indeks ``ix_notif_dedup_daily`` (``emit``), więc restart
pętli niczego nie wysyła drugi raz. Etap 1: bez wpływu na liczniki placementów.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.core.scheduling import local_now
from app.models.notification import NotificationType
from app.models.user import User, UserRole
from app.services import loop_heartbeat
from app.services import start_documents as svc
from app.services.hr.calendar import WorkCalendar, load_calendar
from app.services.notification_triggers import emit

logger = logging.getLogger(__name__)

INTERVAL_SECONDS = 3600
FIRST_HOUR = 9
#: Tyle osób wypisuje dzwonek, reszta to „i jeszcze N”.
_MAX_LISTED = 5
_ENTITY = "start_documents_digest"


def needs_mail(state: svc.PairState) -> bool:
    days = state.working_days_to_deadline
    return days is not None and days <= svc.MAIL_FROM_WORKING_DAYS


def reaches_dl(state: svc.PairState) -> bool:
    days = state.working_days_to_deadline
    return days is not None and days <= svc.DL_FROM_WORKING_DAYS


def _first_working_day(calendar: WorkCalendar, day: date) -> date:
    current = day
    while not calendar.is_working_day(current):
        current += timedelta(days=1)
    return current


def reaches_hor(state: svc.PairState, today: date, calendar: WorkCalendar) -> bool:
    """Dzień startu z zaległością, a po starcie dzień terminu (np. KRK).

    Pętla w dzień wolny nie działa, więc start w niedzielę alarmuje w poniedziałek."""

    if state.deadline is None or state.deadline > today or state.start_date is None:
        return False
    if _first_working_day(calendar, state.start_date) == today:
        return True
    return (
        state.start_date < today
        and _first_working_day(calendar, state.deadline) == today
    )


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


@dataclass
class Digest:
    states: dict[tuple[int, int], svc.PairState] = field(default_factory=dict)
    due: bool = False

    def add(self, state: svc.PairState, *, due: bool) -> None:
        self.states[(state.candidate_id, state.job_id)] = state
        self.due = self.due or due


def plan_digests(
    states: Iterable[svc.PairState],
    *,
    today: date,
    calendar: WorkCalendar,
    head_ids: Iterable[int],
) -> dict[int, Digest]:
    """Jedna lista na odbiorcę: indeks dnia przepuści tylko jeden dzwonek tego typu."""

    heads = list(head_ids)
    plan: dict[int, Digest] = {}

    def add(user_id: int, state: svc.PairState, *, due: bool) -> None:
        plan.setdefault(user_id, Digest()).add(state, due=due)

    for state in states:
        owner = state.owner_id
        if owner is not None:
            add(owner, state, due=needs_mail(state))
        elif needs_mail(state):
            # Nikt nie odpowiada: sprawa nie może zniknąć.
            for head in heads:
                add(head, state, due=True)
        if state.delivery_lead_id is not None and reaches_dl(state):
            add(state.delivery_lead_id, state, due=True)
        if reaches_hor(state, today, calendar):
            for head in heads:
                add(head, state, due=True)
    return plan


async def _send(db: AsyncSession, *, user_id: int, digest: Digest) -> None:
    rows = list(digest.states.values())
    first = rows[0]
    await emit(
        db,
        user_id=user_id,
        title=_title(len(rows)),
        message=digest_message(rows),
        ntype=(
            NotificationType.start_documents_due
            if digest.due
            else NotificationType.start_documents
        ),
        related_entity_type=_ENTITY,
        related_entity_id=user_id,
        link=(
            f"/jobs/{first.job_id}?candidate={first.candidate_id}"
            if len(rows) == 1
            else "/dashboard"
        ),
    )


async def run_once(now: datetime) -> dict[str, int]:
    """Jeden przebieg: w dzień wolny i przed 9:00 nic nie robi."""

    counts = {"recipients": 0}
    today = now.date()
    if now.hour < FIRST_HOUR:
        return counts
    async with AsyncSessionLocal() as db:
        calendar = await load_calendar(db, today - timedelta(days=45), today)
        if not calendar.is_working_day(today):
            return counts
        states = await svc.open_states(db)
        if not states:
            return counts
        heads = [
            user.id
            for user in (
                await db.scalars(select(User).where(User.is_active.is_(True)))
            ).all()
            if user.has_role(UserRole.head_of_recruitment)
        ]
        plan = plan_digests(states, today=today, calendar=calendar, head_ids=heads)
        for user_id, digest in plan.items():
            await _send(db, user_id=user_id, digest=digest)
            counts["recipients"] += 1
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
