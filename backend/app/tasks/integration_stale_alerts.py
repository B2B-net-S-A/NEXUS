"""Alert o zastoju integracji (scrapery pracuj.pl / JJIT).

Scraper, który przestał chodzić, nie wysyła niczego — więc nikt nie zauważa.
Ta pętla co ``INTEGRATION_STALE_CHECK_MINUTES`` sprawdza, czy każde znane
źródło miało udany run w ciągu ``INTEGRATION_STALE_AFTER_HOURS`` (ta sama
reguła co badge „stale" w Insights — ``services.integration_runs.is_stale``),
a jeśli nie, wysyła jeden alert na Slacka na ``INTEGRATION_ALERT_COOLDOWN_HOURS``
per źródło. Cooldown trzymamy w ``integration_alert_state``, nie w pamięci —
Coolify restartuje backend przy każdym pushu na main i alert poszedłby po
każdym deployu od nowa.

Slack przez ``SLACK_WEBHOOK_URL`` z env (ten sam kanał co SLA/spend alerts).
Brak webhooka = pętla loguje i nic nie wysyła (nie kończy się — badge w UI
i tak działa, a webhook może dojść później).
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.integration_run import (
    INTEGRATION_SOURCE_LABELS,
    INTEGRATION_SOURCES,
    IntegrationAlertState,
)
from app.services import loop_heartbeat
from app.services.integration_runs import is_stale, last_success_per_source

logger = logging.getLogger(__name__)


def _format_age(last: datetime | None, now: datetime) -> str:
    if last is None:
        return "nigdy"
    hours = int((now - last).total_seconds() // 3600)
    return f"{hours} h temu" if hours < 48 else f"{hours // 24} dni temu"


async def _post_to_slack(webhook: str, text: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(webhook, json={"text": text})
        if resp.status_code >= 400:
            logger.warning(
                "integration stale alert: slack %s %s",
                resp.status_code,
                resp.text[:120],
            )
            return False
        return True
    except Exception:  # noqa: BLE001 - alert nie może wywrócić pętli
        logger.exception("integration stale alert: slack post failed")
        return False


async def run_once(*, now: datetime | None = None) -> dict:
    """Jedna iteracja; zwraca słownik do logów/testów: {source: 'ok'|'stale'|'alerted'|'cooldown'}."""
    now = now or datetime.now(timezone.utc)
    stale_after = float(settings.INTEGRATION_STALE_AFTER_HOURS)
    cooldown = timedelta(hours=float(settings.INTEGRATION_ALERT_COOLDOWN_HOURS))
    webhook = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
    outcome: dict[str, str] = {}

    async with AsyncSessionLocal() as db:
        last_success = await last_success_per_source(db)
        for source in INTEGRATION_SOURCES:
            last = last_success.get(source)
            if not is_stale(last, stale_after_hours=stale_after, now=now):
                outcome[source] = "ok"
                continue

            state = await db.scalar(
                select(IntegrationAlertState).where(
                    IntegrationAlertState.source == source
                )
            )
            if state and state.last_alert_at and (now - state.last_alert_at) < cooldown:
                outcome[source] = "cooldown"
                continue

            label = INTEGRATION_SOURCE_LABELS.get(source, source)
            reason = (
                f"🔕 *Integracja {label} nie raportuje*\n"
                f"• Ostatni udany run: {_format_age(last, now)}\n"
                f"• Próg: {stale_after:.0f} h\n"
                f"• Sprawdź scraper na Macu (launchd) i NEXUS → Insights → Integracje"
            )
            sent = bool(webhook) and await _post_to_slack(webhook, reason)
            if not webhook:
                logger.warning(
                    "integration stale (%s) — SLACK_WEBHOOK_URL not set", source
                )
            if state is None:
                state = IntegrationAlertState(source=source)
                db.add(state)
            # Stempel także bez webhooka — inaczej log spamowałby co 30 min.
            state.last_alert_at = now
            state.last_alert_reason = reason
            outcome[source] = "alerted" if sent else "stale"
        await db.commit()
    return outcome


async def integration_stale_alerts_loop() -> None:
    """Kill-switch sprawdzany PRZED pętlą (konwencja repo)."""
    if not settings.INTEGRATION_STALE_ALERTS_ENABLED:
        logger.info(
            "integration_stale_alerts_loop disabled (INTEGRATION_STALE_ALERTS_ENABLED=false)"
        )
        return
    interval = max(5.0, float(settings.INTEGRATION_STALE_CHECK_MINUTES)) * 60
    beat = loop_heartbeat.register(
        "integration_stale_alerts", max_silence_seconds=int(interval * 3)
    )
    # Krótki rozbieg: po deployu baza i tak jest, ale nie ma powodu ścigać się
    # z resztą pętli o połączenia w pierwszej sekundzie.
    await asyncio.sleep(60)
    while True:
        try:
            beat.tick()
            outcome = await run_once()
            if any(v in ("alerted", "stale") for v in outcome.values()):
                logger.info("integration stale check: %s", outcome)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("integration_stale_alerts iteration failed")
        await asyncio.sleep(interval)
