"""Bieg bota radaru przepisów: jednorazowy token, webhook rutyny, wygaszanie.

Ten sam wzór co kanał Sprzedaży (``services/sales/signals.py``): bieg jest
zapisany przed wywołaniem webhooka, bo bot może odpowiedzieć szybciej niż NEXUS
skończy żądanie. Zmiana stanu biegu tylko warunkowo (``status = 'started'``):
błąd webhooka ani wygaśnięcie nie nadpiszą przyjętego raportu. Timeout
webhooka zostawia bieg otwarty z tokenem (nie wiadomo, czy bot dostał
zlecenie), błąd HTTP zamyka go jako ``failed``.

Dwa boty, dwie rutyny: Zbieracz (``collect``) i Analityk (``analyze``), każdy
z własnym adresem i kluczem webhooka. Żaden nie ma stałego klucza do NEXUSA.

Webhook v2 (Analityk od 17.11, Zbieracz od 24.11.2026, ``services/grok_webhook``)
niesie samą kopertę z ``request_url``; zlecenie bot pobiera GET-em. Wersję
zapisujemy w zleceniu biegu (``_schema_version``), bo raport Analityka v2 musi
potwierdzić wszystkie pozycje. Rutyna z ``GROK_BOT_WEBHOOK_V1`` dostaje dawną
treść z całym zleceniem. Logi są publiczne: same liczby.
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
from app.services import grok_webhook
from app.services.law_radar import analyze, collect, schema
from app.services.sales.signals import hash_token, token_matches

logger = logging.getLogger(__name__)

SCHEMA_VERSION = grok_webhook.V1
FETCH_SCHEMA_VERSION = grok_webhook.V2
TOKEN_TTL = timedelta(hours=2)
INVALID_TOKEN_DETAIL = "Nieważny token biegu."
KINDS = schema.RUN_KINDS
#: Nazwa rutyny rodzaju w ``GROK_BOT_WEBHOOK_V1``.
ROUTINES: dict[str, str] = {
    collect.KIND: grok_webhook.LAW_COLLECT,
    analyze.KIND: grok_webhook.LAW_ANALYZE,
}

__all__ = [
    "INVALID_TOKEN_DETAIL",
    "callback_url",
    "configured",
    "enabled",
    "expire_runs",
    "hash_token",
    "mark_received",
    "new_run",
    "request_body",
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
    stored_request = dict(request)
    if grok_webhook.schema_for(ROUTINES[kind]) == FETCH_SCHEMA_VERSION:
        stored_request["_schema_version"] = FETCH_SCHEMA_VERSION
    run = LawRadarRun(
        kind=kind,
        status="started",
        request=stored_request,
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


def uses_request_fetch(run: LawRadarRun) -> bool:
    """Bieg v2: zlecenie dostępne GET-em na ``request_url``."""

    return (run.request or {}).get("_schema_version") == FETCH_SCHEMA_VERSION


def uses_analyze_request_fetch(run: LawRadarRun) -> bool:
    """Analityk v2: raport musi potwierdzić wszystkie pozycje zlecenia."""

    return run.kind == analyze.KIND and uses_request_fetch(run)


def _order(run: LawRadarRun) -> dict[str, Any]:
    """Polecenie, kształt raportu i zlecenie biegu (bez znacznika wersji)."""

    request = {
        key: value
        for key, value in (run.request or {}).items()
        if key != "_schema_version"
    }
    module = collect if run.kind == collect.KIND else analyze
    report_format = module.report_format()
    if uses_analyze_request_fetch(run):
        report_format = {**report_format, "reviewed_item_ids": [1]}
    return {
        "task": module.task_text(request),
        "report_format": report_format,
        "request": request,
    }


def request_body(run: LawRadarRun) -> dict[str, Any]:
    """Odpowiedź ``GET request_url``: pełne, zapisane zlecenie biegu bez tokenu."""

    return {
        "run_id": run.id,
        "kind": run.kind,
        **_order(run),
        "callback_url": callback_url(run.id),
        "expires_at": run.token_expires_at.isoformat()
        if run.token_expires_at
        else None,
    }


def webhook_body(run: LawRadarRun, token: str) -> dict[str, Any]:
    """Treść webhooka: w v2 sama koperta, w zapasie v1 całe zlecenie."""

    if uses_request_fetch(run):
        return grok_webhook.envelope(
            run.id, callback_url(run.id), token, run.token_expires_at
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run.id,
        "kind": run.kind,
        "token": token,
        "expires_at": run.token_expires_at.isoformat()
        if run.token_expires_at
        else None,
        "callback_url": callback_url(run.id),
        **_order(run),
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
    outcome = await grok_webhook.post(
        webhook_url,
        webhook_key,
        body,
        client=client,
        channel="law_radar",
        run_id=run_id,
        kind=kind,
        routine=ROUTINES[kind],
    )
    if outcome.timed_out:
        # Nie wiadomo, czy bot dostał zlecenie: bieg zostaje otwarty z tokenem,
        # a bez raportu zamknie go ``expire_runs`` po terminie tokenu.
        logger.warning("law_radar run=%s kind=%s webhook timeout", run_id, kind)
    error = outcome.error
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
