"""Umowa przedwstępna — wygasanie i przypomnienia (co godzinę).

* Podpisana umowa po dacie ważności: prośba zamknięta jako ``expired``,
  dzwonek do obserwujących i wystawiającego.
* Do końca ważności zostały ≤ 3 dni, a osoba wciąż w toku: dzwonek „wkrótce
  wygaśnie” (raz).
* Umowa wysłana, kandydat milczy ``REMIND_EVERY``: dzwonek do wystawiającego.
* Termin umowy B2B z przedwstępnej (po akceptacji klienta) za ≤ 1 dzień
  roboczy: dzwonek do obserwujących.

Najwyżej jedno przypomnienie na prośbę dziennie (``last_reminder_at``).
Każda prośba w osobnej transakcji z blokadą (``SKIP LOCKED``), więc równoległy
podpis albo zamknięcie wygrywa.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.pre_contract import PreContractRequest
from app.services import loop_heartbeat
from app.services import pre_contracts as svc

logger = logging.getLogger(__name__)

INTERVAL_SECONDS = 3600
REMIND_EVERY = timedelta(days=3)


def due_action(req: PreContractRequest, *, today: date, now: datetime) -> Optional[str]:
    """Co sweeper ma zrobić z prośbą (czysta funkcja — testy bez bazy)."""
    if req.closed_at is not None:
        return None
    if svc.is_signed(req) and req.valid_until is not None and req.valid_until < today:
        return "expire"
    reminded_today = (
        req.last_reminder_at is not None
        and req.last_reminder_at.astimezone(svc._TZ).date() >= today
    )
    if reminded_today:
        return None
    # Termin B2B: tylko przed jego upływem (po terminie dzwonek co dzień
    # nikomu nie pomaga i zjadałby ostrzeżenie o ważności).
    if (
        req.b2b_deadline is not None
        and req.b2b_deadline >= today
        and svc.business_days_until(today, req.b2b_deadline) <= 1
    ):
        return "b2b_deadline"
    if (
        svc.is_signed(req)
        and req.valid_until is not None
        and (req.valid_until - today).days <= svc.REMIND_EXPIRING_DAYS
        and (
            req.last_reminder_at is None
            or req.last_reminder_at.astimezone(svc._TZ).date()
            < req.valid_until - timedelta(days=svc.REMIND_EXPIRING_DAYS)
        )
    ):
        return "expiring"
    if (
        req.sent_at is not None
        and req.candidate_signed_at is None
        and now - max(req.sent_at, req.last_reminder_at or req.sent_at) >= REMIND_EVERY
    ):
        return "reminder_waiting"
    return None


async def _open_ids() -> list[int]:
    async with AsyncSessionLocal() as db:
        rows = await db.scalars(
            select(PreContractRequest.id).where(PreContractRequest.closed_at.is_(None))
        )
        return list(rows.all())


async def _handle(request_id: int, now: datetime) -> Optional[str]:
    today = svc.today()
    async with AsyncSessionLocal() as db:
        req = await db.scalar(
            select(PreContractRequest)
            .where(PreContractRequest.id == request_id)
            .with_for_update(skip_locked=True)
        )
        if req is None:
            return None
        action = due_action(req, today=today, now=now)
        if action is None:
            return None
        if action == "expire":
            req.closed_at = now
            req.close_reason = "expired"
            event = await svc.add_event(db, req, "expired", actor_id=None)
            message = f"Umowa przedwstępna wygasła {req.valid_until:%d.%m.%Y}."
            await svc.notify(db, req, event, message=message, actor_id=None)
        elif action == "expiring":
            req.last_reminder_at = now
            event = await svc.add_event(db, req, "expiring", actor_id=None)
            message = (
                f"Umowa przedwstępna jest ważna do {req.valid_until:%d.%m.%Y}. "
                "Osoba jest wciąż w procesie — przedłuż umowę albo zamknij prośbę."
            )
            await svc.notify(db, req, event, message=message, actor_id=None)
        elif action == "b2b_deadline":
            req.last_reminder_at = now
            event = await svc.add_event(db, req, "b2b_deadline", actor_id=None)
            message = (
                f"Termin zawarcia umowy B2B z przedwstępnej mija {req.b2b_deadline:%d.%m.%Y}. "
                "Po nim kara dla firmy."
            )
            await svc.notify(db, req, event, message=message, actor_id=None)
        else:
            req.last_reminder_at = now
            event = await svc.add_event(db, req, "reminder_waiting", actor_id=None)
            days = (now - req.sent_at).days if req.sent_at else 0
            message = (
                f"Kandydat od {days} dni nie odesłał podpisanej umowy przedwstępnej."
            )
            await svc.notify(
                db,
                req,
                event,
                message=message,
                actor_id=None,
                only_user_ids=[req.assignee_id],
            )
        await db.commit()
        return action


async def sweep(now: Optional[datetime] = None) -> dict[str, int]:
    moment = now or datetime.now(timezone.utc)
    counts: dict[str, int] = {}
    for request_id in await _open_ids():
        try:
            outcome = await _handle(request_id, moment)
        except Exception:  # noqa: BLE001 — jedna prośba nie zatrzymuje reszty
            logger.exception(
                "[pre_contract] przegląd prośby %d nie powiódł się", request_id
            )
            continue
        if outcome:
            counts[outcome] = counts.get(outcome, 0) + 1
    return counts


async def pre_contract_sweeper_loop() -> None:
    beat = loop_heartbeat.register(
        "pre_contract_sweeper", max_silence_seconds=INTERVAL_SECONDS + 1800
    )
    while True:
        beat.tick()
        try:
            counts = await sweep()
            if counts:
                logger.info("[pre_contract] przegląd: %s", counts)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("[pre_contract] przegląd nie powiódł się")
        await asyncio.sleep(INTERVAL_SECONDS)
