"""Bieg bota radaru przepisów: jednorazowy token, webhook rutyny, wygaszanie.

Ten sam wzór co kanał Sprzedaży (``services/sales/signals.py``): bieg jest
zapisany przed wywołaniem webhooka, bo bot może odpowiedzieć szybciej niż NEXUS
skończy żądanie. Zmiana stanu biegu tylko warunkowo (``status = 'started'``):
błąd webhooka ani wygaśnięcie nie nadpiszą przyjętego raportu. Timeout
webhooka zostawia bieg otwarty z tokenem (nie wiadomo, czy bot dostał
zlecenie), błąd HTTP zamyka go jako ``failed``.

Dwa boty, dwie rutyny: Zbieracz (``collect``) i Analityk (``analyze``), każdy
z własnym adresem i kluczem webhooka. Żaden nie ma stałego klucza do NEXUSA.
Logi są publiczne: same liczby.
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.law_radar import LawRadarRun
from app.services.law_radar import analyze, collect, schema
from app.services.sales.signals import hash_token, token_matches

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
TOKEN_TTL = timedelta(hours=2)
WEBHOOK_TIMEOUT_SECONDS = 20.0
INVALID_TOKEN_DETAIL = "Nieważny token biegu."
KINDS = schema.RUN_KINDS

__all__ = [
    "INVALID_TOKEN_DETAIL",
    "callback_url",
    "configured",
    "enabled",
    "expire_runs",
    "hash_token",
    "mark_received",
    "new_run",
    "start_run",
    "token_matches",
    "webhook",
    "webhook_body",
]


def enabled() -> bool:
    return bool(settings.LAW_RADAR_ENABLED)


def webhook(kind: str) -> tuple[str, str]:
    """Adres i klucz rutyny bota danego rodzaju."""

    if kind == collect.KIND:
        return (
            settings.GROK_BOT_LAW_COLLECT_WEBHOOK_URL,
            settings.GROK_BOT_LAW_COLLECT_WEBHOOK_KEY,
        )
    if kind == analyze.KIND:
        return (
            settings.GROK_BOT_LAW_ANALYZE_WEBHOOK_URL,
            settings.GROK_BOT_LAW_ANALYZE_WEBHOOK_KEY,
        )
    raise ValueError("Nieznany rodzaj biegu radaru.")


def configured(kind: str) -> bool:
    return all(webhook(kind))


def new_run(
    kind: str,
    request: dict[str, Any],
    *,
    now: datetime,
    parent_run_id: Optional[int] = None,
    requested_by_user_id: Optional[int] = None,
) -> tuple[LawRadarRun, str]:
    if kind not in KINDS:
        raise ValueError("Nieznany rodzaj biegu radaru.")
    token = secrets.token_urlsafe(32)
    run = LawRadarRun(
        kind=kind,
        status="started",
        request=dict(request),
        report={},
        parent_run_id=parent_run_id,
        requested_by_user_id=requested_by_user_id,
        token_hash=hash_token(token),
        token_expires_at=now + TOKEN_TTL,
        started_at=now,
    )
    return run, token


def callback_url(run_id: int) -> str:
    base = settings.PUBLIC_API_BASE_URL.rstrip("/")
    return f"{base}/api/integrations/law-radar/runs/{run_id}"


def webhook_body(run: LawRadarRun, token: str) -> dict[str, Any]:
    """Treść dla bota: polecenie, kształt raportu i zlecenie biegu.

    Rutyna robi to, co mówi ``task``, i odsyła jeden ``POST`` w kształcie
    ``report_format`` na ``callback_url`` z nagłówkiem ``X-Run-Token``.
    """

    request = dict(run.request or {})
    module = collect if run.kind == collect.KIND else analyze
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run.id,
        "kind": run.kind,
        "token": token,
        "expires_at": run.token_expires_at.isoformat()
        if run.token_expires_at
        else None,
        "callback_url": callback_url(run.id),
        "task": module.task_text(request),
        "report_format": module.report_format(),
        "request": request,
    }


def mark_received(run: LawRadarRun, summary: dict[str, Any], now: datetime) -> None:
    run.status = "received"
    run.received_at = now
    run.token_hash = None
    run.report = summary


async def start_run(
    db: AsyncSession,
    kind: str,
    request: dict[str, Any],
    *,
    now: Optional[datetime] = None,
    client: Optional[httpx.AsyncClient] = None,
    parent_run_id: Optional[int] = None,
    requested_by_user_id: Optional[int] = None,
) -> Optional[LawRadarRun]:
    """Załóż bieg i wywołaj webhook rutyny. Bez adresu albo klucza: nic."""

    webhook_url, webhook_key = webhook(kind)
    if not (webhook_url and webhook_key):
        return None
    moment = now or datetime.now(timezone.utc)
    run, token = new_run(
        kind,
        request,
        now=moment,
        parent_run_id=parent_run_id,
        requested_by_user_id=requested_by_user_id,
    )
    db.add(run)
    await db.flush()
    body = webhook_body(run, token)
    await db.commit()
    run_id = run.id
    headers = {"Authorization": f"Bearer {webhook_key}"}
    error: Optional[str] = None
    try:
        if client is None:
            async with httpx.AsyncClient(timeout=WEBHOOK_TIMEOUT_SECONDS) as own:
                response = await own.post(webhook_url, json=body, headers=headers)
        else:
            response = await client.post(webhook_url, json=body, headers=headers)
        response.raise_for_status()
    except httpx.TimeoutException:
        # Nie wiadomo, czy bot dostał zlecenie: bieg zostaje otwarty z tokenem,
        # a bez raportu zamknie go ``expire_runs`` po terminie tokenu.
        logger.warning("law_radar run=%s kind=%s webhook timeout", run_id, kind)
    except httpx.HTTPStatusError as exc:
        error = f"webhook HTTP {exc.response.status_code}"
    except httpx.HTTPError as exc:
        error = f"webhook {type(exc).__name__}"[:255]
    if error is not None:
        await _close_open_run(db, run_id, status="failed", error=error)
        logger.warning("law_radar run=%s kind=%s failed: %s", run_id, kind, error)
    await db.refresh(run)
    logger.info("law_radar run=%s kind=%s status=%s", run_id, kind, run.status)
    return run


async def _close_open_run(
    db: AsyncSession, run_id: int, *, status: str, error: str
) -> bool:
    """Zamknij bieg tylko, gdy wciąż czeka: raport przyjęty w międzyczasie wygrywa."""

    result = await db.execute(
        update(LawRadarRun)
        .where(LawRadarRun.id == run_id, LawRadarRun.status == "started")
        .values(status=status, token_hash=None, error=error)
    )
    await db.commit()
    return bool(result.rowcount)


async def expire_runs(db: AsyncSession, *, now: datetime) -> int:
    """Bieg bez raportu po terminie tokenu: ``expired`` i ostrzeżenie w logu."""

    rows = (
        await db.execute(
            update(LawRadarRun)
            .where(
                LawRadarRun.status == "started",
                LawRadarRun.token_expires_at < now,
            )
            .values(status="expired", token_hash=None, error="brak raportu")
            .returning(LawRadarRun.id, LawRadarRun.kind)
        )
    ).all()
    await db.commit()
    for run_id, kind in rows:
        logger.warning("law_radar run=%s kind=%s expired without report", run_id, kind)
    return len(rows)
