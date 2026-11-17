"""Bieg bota Cpro: jednorazowy token, webhook rutyny, wygaszanie, stan kart.

Ten sam wzór co radar przepisów i Sprzedaż (``services/law_radar/runs.py``):
bieg jest zapisany przed wywołaniem webhooka, zmiana stanu biegu tylko
warunkowo (``status = 'started'``), timeout webhooka zostawia bieg otwarty
z tokenem, błąd HTTP zamyka go jako ``failed``.

Stan karty w kolejce liczy się z najnowszego biegu, który ją obejmował:
``working`` (bieg trwa), wynik z raportu (``submitted``, ``draft``,
``failed``, ``skipped``) albo ``retry`` (bieg padł albo wygasł bez raportu —
pętla spróbuje jeszcze raz, najwyżej ``MAX_ATTEMPTS`` razy). ``failed``
i ``skipped`` z raportu pętla nie ponawia sama: bot powiedział, czemu się nie
da, więc kartę wrzuca człowiek albo klika „Ponów botem”.
Logi są publiczne: same liczby.
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.cpro_bot import CproBotRun
from app.services.cpro_bot import task_text
from app.services.sales.signals import hash_token, token_matches

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
TOKEN_TTL = timedelta(hours=2)
WEBHOOK_TIMEOUT_SECONDS = 20.0
INVALID_TOKEN_DETAIL = "Nieważny token biegu."
#: Tyle kart naraz: bot wypełnia formularze po kolei, ok. 5 min na osobę.
MAX_ITEMS_PER_RUN = 5
MAX_ATTEMPTS = 3
RETRY_AFTER = timedelta(minutes=30)
#: Z tylu dni wstecz liczy się stan kart (kolejka Cpro żyje dniami, nie tygodniami).
STATE_WINDOW = timedelta(days=30)

__all__ = [
    "INVALID_TOKEN_DETAIL",
    "ItemState",
    "callback_url",
    "configured",
    "cv_url",
    "enabled",
    "expire_runs",
    "hash_token",
    "item_states",
    "start_run",
    "token_matches",
    "webhook_body",
]


def enabled() -> bool:
    return bool(settings.CPRO_BOT_ENABLED)


def webhook() -> tuple[str, str]:
    return settings.GROK_BOT_CPRO_WEBHOOK_URL, settings.GROK_BOT_CPRO_WEBHOOK_KEY


def configured() -> bool:
    return all(webhook())


def callback_url(run_id: int) -> str:
    base = settings.PUBLIC_API_BASE_URL.rstrip("/")
    return f"{base}/api/integrations/cpro-bot/runs/{run_id}"


def cv_url(run_id: int, stage_id: int) -> str:
    return f"{callback_url(run_id)}/cv/{stage_id}"


def new_run(
    items: list[dict[str, Any]],
    *,
    now: datetime,
    submit: bool,
    cards: Optional[dict[str, Any]] = None,
    requested_by_user_id: Optional[int] = None,
) -> tuple[CproBotRun, str]:
    token = secrets.token_urlsafe(32)
    run = CproBotRun(
        status="started",
        submit=submit,
        stage_ids=[int(item["ref"]) for item in items],
        # ``cards`` (etap docelowy, wersja procesu) zostaje w NEXUSIE — botowi
        # idą tylko ``items`` (``webhook_body``).
        request={"items": [dict(item) for item in items], "cards": dict(cards or {})},
        report={},
        requested_by_user_id=requested_by_user_id,
        token_hash=hash_token(token),
        token_expires_at=now + TOKEN_TTL,
        started_at=now,
    )
    return run, token


def webhook_body(run: CproBotRun, token: str) -> dict[str, Any]:
    """Treść dla bota: polecenie, kształt raportu i pozycje z adresem CV."""

    items = []
    for item in (run.request or {}).get("items", []):
        offer = {**item.get("offer", {}), "cv_url": cv_url(run.id, int(item["ref"]))}
        items.append({**item, "offer": offer})
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run.id,
        "kind": "cpro_offers",
        "token": token,
        "expires_at": run.token_expires_at.isoformat()
        if run.token_expires_at
        else None,
        "callback_url": callback_url(run.id),
        "submit": bool(run.submit),
        "task": task_text.TASK,
        "report_format": task_text.report_format(),
        "items": items,
    }


async def start_run(
    db: AsyncSession,
    items: list[dict[str, Any]],
    *,
    submit: bool = True,
    cards: Optional[dict[str, Any]] = None,
    now: Optional[datetime] = None,
    client: Optional[httpx.AsyncClient] = None,
    requested_by_user_id: Optional[int] = None,
) -> Optional[CproBotRun]:
    """Załóż bieg i wywołaj webhook rutyny. Bez adresu, klucza albo pozycji: nic."""

    webhook_url, webhook_key = webhook()
    if not (webhook_url and webhook_key) or not items:
        return None
    moment = now or datetime.now(timezone.utc)
    run, token = new_run(
        items,
        now=moment,
        submit=submit,
        cards=cards,
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
        logger.warning("cpro_bot run=%s webhook timeout", run_id)
    except httpx.HTTPStatusError as exc:
        error = f"webhook HTTP {exc.response.status_code}"
    except httpx.HTTPError as exc:
        error = f"webhook {type(exc).__name__}"[:255]
    if error is not None:
        await _close_open_run(db, run_id, status="failed", error=error)
        logger.warning("cpro_bot run=%s failed: %s", run_id, error)
    await db.refresh(run)
    logger.info(
        "cpro_bot run=%s items=%d submit=%s status=%s",
        run_id,
        len(items),
        submit,
        run.status,
    )
    return run


async def _close_open_run(
    db: AsyncSession, run_id: int, *, status: str, error: str
) -> bool:
    result = await db.execute(
        update(CproBotRun)
        .where(CproBotRun.id == run_id, CproBotRun.status == "started")
        .values(status=status, token_hash=None, error=error)
    )
    await db.commit()
    return bool(result.rowcount)


async def expire_runs(db: AsyncSession, *, now: datetime) -> int:
    rows = (
        await db.execute(
            update(CproBotRun)
            .where(
                CproBotRun.status == "started",
                CproBotRun.token_expires_at < now,
            )
            .values(status="expired", token_hash=None, error="brak raportu")
            .returning(CproBotRun.id)
        )
    ).all()
    await db.commit()
    for (run_id,) in rows:
        logger.warning("cpro_bot run=%s expired without report", run_id)
    return len(rows)


async def has_open_run(db: AsyncSession) -> bool:
    found = await db.scalar(
        select(CproBotRun.id).where(CproBotRun.status == "started").limit(1)
    )
    return found is not None


@dataclass(frozen=True)
class ItemState:
    state: str
    at: datetime
    run_id: int
    attempts: int = 1
    message: Optional[str] = None
    offer_url: Optional[str] = None
    cpro_status: Optional[str] = None
    submit: bool = True
    #: Wysłana karta: czy NEXUS przesunął ją na „Wysłane do Cpro”.
    moved: Optional[bool] = None


def state_for(run: CproBotRun, stage_id: int, attempts: int) -> ItemState:
    """Stan jednej karty w biegu (czysta reguła)."""

    at = run.received_at or run.started_at
    if run.status == "started":
        return ItemState("working", at, run.id, attempts, submit=run.submit)
    if run.status in ("failed", "expired"):
        return ItemState("retry", at, run.id, attempts, submit=run.submit)
    outcome = ((run.report or {}).get("items") or {}).get(str(stage_id))
    if not isinstance(outcome, dict):
        return ItemState(
            "failed",
            at,
            run.id,
            attempts,
            message="Bot nie odesłał wyniku tej osoby.",
            submit=run.submit,
        )
    moved = outcome.get("moved")
    return ItemState(
        str(outcome.get("outcome") or "failed"),
        at,
        run.id,
        attempts,
        message=outcome.get("move_problem") or outcome.get("message"),
        offer_url=outcome.get("offer_url"),
        cpro_status=outcome.get("cpro_status"),
        submit=run.submit,
        moved=moved if isinstance(moved, bool) else None,
    )


async def item_states(
    db: AsyncSession, stage_ids: Iterable[int], *, now: datetime
) -> dict[int, ItemState]:
    """Stan każdej karty z najnowszego biegu, który ją obejmował."""

    wanted = {int(s) for s in stage_ids}
    if not wanted:
        return {}
    runs = (
        await db.scalars(
            select(CproBotRun)
            .where(CproBotRun.started_at >= now - STATE_WINDOW)
            .order_by(CproBotRun.started_at.asc(), CproBotRun.id.asc())
        )
    ).all()
    attempts: dict[int, int] = {}
    out: dict[int, ItemState] = {}
    for run in runs:
        for raw in run.stage_ids or []:
            stage_id = int(raw)
            if stage_id not in wanted:
                continue
            attempts[stage_id] = attempts.get(stage_id, 0) + 1
            out[stage_id] = state_for(run, stage_id, attempts[stage_id])
    return out


def due_for_bot(state: Optional[ItemState], *, now: datetime) -> bool:
    """Czy pętla może dać kartę botowi (karta bez braków).

    Szkic z próby (bieg bez wysyłki) bot wyśle w następnym biegu. Szkic
    z prawdziwego biegu (np. „Submit Offer” się nie udał) liczy się jak bieg,
    który padł: najwyżej ``MAX_ATTEMPTS`` prób, co ``RETRY_AFTER`` — każda
    próba to dane osoby jeszcze raz u bota.
    """

    if state is None:
        return True
    if state.state == "draft" and not state.submit:
        return True
    if state.state in ("retry", "draft"):
        return state.attempts < MAX_ATTEMPTS and state.at <= now - RETRY_AFTER
    return False
