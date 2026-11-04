"""Pętla zdarzeń API integracyjnego v1 (``integration_webhooks`` w ``main.py``).

Co ``LOOP_SLEEP_SECONDS`` (albo od razu po zamówieniu próby / nowym webhooku):

1. ``publish_pending`` — zdarzenia z poczekalni dostają kursor i trafiają do
   kanału ``GET /events`` (bez tego kroku kanał stoi);
2. raz na godzinę retencja kanału — zdarzenia starsze niż 30 dni znikają
   (webhook z kursorem sprzed retencji po prostu ich już nie dostanie);
3. dostarczenie webhooków, które są „na teraz” (aktywne po odstępie albo
   z zamówioną próbą) — po kolei, każdy we własnej sesji.

Bez przełącznika w konfiguracji: pusta poczekalnia i brak webhooków to dwa
krótkie zapytania na bieg.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

from app.core.database import AsyncSessionLocal
from app.services import integration_events, integration_webhooks, loop_heartbeat

logger = logging.getLogger(__name__)

LOOP_SLEEP_SECONDS = 10
PURGE_EVERY_SECONDS = 3600

_wake = asyncio.Event()
_last_purge = 0.0


def request_wakeup() -> None:
    """Obudź pętlę przed czasem (trasa zamówiła próbę albo dodała webhook)."""
    try:
        _wake.set()
    except RuntimeError:  # pragma: no cover - zdarzenie z innej pętli (testy)
        pass


async def run_once() -> dict:
    """Jeden bieg: publikacja, retencja (co godzinę), dostarczenie."""
    global _last_purge
    summary = {"published": 0, "purged": 0, "webhooks": {}}
    async with AsyncSessionLocal() as db:
        summary["published"] = await integration_events.publish_pending(db)
    if time.monotonic() - _last_purge >= PURGE_EVERY_SECONDS:
        async with AsyncSessionLocal() as db:
            summary["purged"] = await integration_events.purge_expired(db)
        _last_purge = time.monotonic()
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        due = await integration_webhooks.due_webhook_ids(db, now)
    if not due:
        return summary
    async with integration_webhooks.new_http_client() as client:
        for webhook_id in due:
            try:
                async with AsyncSessionLocal() as db:
                    outcome = await integration_webhooks.deliver_webhook(
                        db, client, webhook_id, now=now
                    )
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — jeden webhook nie zatrzymuje reszty
                logger.exception(
                    "integration_webhooks: webhook %d — bieg nieudany", webhook_id
                )
                outcome = "error"
            summary["webhooks"][webhook_id] = outcome
    return summary


async def integration_webhooks_loop() -> None:
    beat = loop_heartbeat.register(
        "integration_webhooks", max_silence_seconds=LOOP_SLEEP_SECONDS + 900
    )
    while True:
        beat.tick()
        # Czyszczone PRZED biegiem: pobudka zamówiona w trakcie biegu skraca
        # najbliższe czekanie zamiast przepaść.
        _wake.clear()
        try:
            summary = await run_once()
            busy = {
                webhook_id: outcome
                for webhook_id, outcome in summary["webhooks"].items()
                if outcome not in ("idle", "skipped", "busy")
            }
            if summary["published"] or summary["purged"] or busy:
                logger.info(
                    "integration_webhooks: published=%d purged=%d webhooks=%s",
                    summary["published"],
                    summary["purged"],
                    busy,
                )
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("integration_webhooks iteration failed")
        try:
            await asyncio.wait_for(_wake.wait(), timeout=LOOP_SLEEP_SECONDS)
        except asyncio.TimeoutError:
            pass
