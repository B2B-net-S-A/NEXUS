"""Pobieranie faktur sprzedażowych z KSeF (spółka jako sprzedawca, ``Subject1``).

Ten sam klient API, konfiguracja (``KSEF_MODE``, ``KSEF_CONTEXT_NIP``,
``KSEF_TOKEN``) i parser FA co faktury od osób (etap 4,
``services/hr/ksef``) — osobny znacznik HWM, kolejka i stan
(``app_settings['client_sales_ksef_sync']``), osobne rezerwacje przebiegu
(``sales_ksef_fetch`` co godzinę, ``sales_ksef_fetch_lock`` — jeden naraz).

* ``run_once(db)`` — pętla co godzinę (wpina koordynator): przyrostowo od
  znacznika ``permanentStorageHwmDate`` (okno ``PermanentStorage``
  z ``restrictToPermanentStorageHwmDate``), potem ponowna próba dopasowania
  faktur czekających z powodu, który mógł zniknąć (nowe zamówienie, import MD),
* ``fetch_now(db, actor_id)`` — „Pobierz teraz” (Finanse), nie częściej niż co
  5 minut.

Limity API liczy KSeF na kontekst (NIP spółki) i adres IP — wspólnie
z pobieraniem faktur od osób. Na produkcji 20 zapytań o metadane i 64 pobrania
faktury na godzinę: faktury od osób biorą do 8 i 40, ta pętla do 6 i 20.
Blokada 429 zapisana przez którąkolwiek ścieżkę wstrzymuje obie.

Zapisujemy każdą fakturę, w której spółka jest sprzedawcą (to nasze faktury
do klientów). Tryb ``simulate`` czyta katalog ``<KSEF_SIMULATE_DIR>/sales``.
Logi: identyfikatory i liczby — bez numerów KSeF, NIP-ów i kwot.
"""

from __future__ import annotations

import hashlib
import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import DEFAULT_TZ
from app.models.app_setting import AppSetting
from app.models.client_sales_invoice import ClientSalesInvoice
from app.services.client_invoicing import clients, fa_sales, matching
from app.services.client_invoicing import settings as module_settings
from app.services.hr import job_runs
from app.services.hr.ksef import fa, numbers
from app.services.hr.ksef import sync as people_sync
from app.services.hr.ksef.client import (
    SUBJECT_SELLER,
    KsefApiError,
    format_instant,
    parse_instant,
)
from app.services.hr.ksef.environment import KsefConfig, load_config
from app.services.hr.ksef.source import InvoiceSource, SimulatedSource, open_source

logger = logging.getLogger(__name__)

STATE_KEY = "client_sales_ksef_sync"
JOB_KIND = "sales_ksef_fetch"
LOCK_KIND = "sales_ksef_fetch_lock"
LOCK_KEY = "global"
SIMULATE_SUBDIR = "sales"
WINDOW = timedelta(days=99)
MAX_WINDOWS = 4
MAX_METADATA_REQUESTS = 6
MAX_DOWNLOADS = 20
MANUAL_COOLDOWN = timedelta(minutes=5)
MAX_PENDING_ATTEMPTS = 24
MAX_PROBLEMS = 20
#: Pierwszy przebieg: od 1. dnia trzeciego miesiąca wstecz (zaległe faktury).
INITIAL_MONTHS_BACK = 3
_ZONE = ZoneInfo(DEFAULT_TZ)

DISABLED_DETAIL = "Pobieranie z KSeF jest wyłączone."
BUSY_DETAIL = "Pobieranie z KSeF właśnie trwa. Odśwież za chwilę."
COOLDOWN_DETAIL = "Faktury z KSeF były pobierane przed chwilą — spróbuj za kilka minut."

PROBLEM_LABELS = {
    "seller_mismatch": "sprzedawcą nie jest spółka",
    "pending_expired": "faktura długo niedostępna do pobrania",
    "db:constraint": "baza nie przyjęła faktury",
}


class SalesSyncError(ValueError):
    def __init__(self, message: str, status_code: int = 409, code: str = "") -> None:
        self.status_code = status_code
        self.code = code
        super().__init__(message)


@dataclass
class _Run:
    db: AsyncSession
    config: KsefConfig
    source: InvoiceSource
    now: datetime
    registry: clients.NipRegistry
    pending: dict[str, dict[str, Any]]
    problems: list[dict[str, Any]]
    counts: Counter = field(default_factory=Counter)
    requests_left: int = MAX_METADATA_REQUESTS
    downloads_left: int = MAX_DOWNLOADS
    progress: Optional[str] = None


class _BudgetSpent(Exception):
    pass


# ── Stan ─────────────────────────────────────────────────────────────────────


async def load_state(db: AsyncSession) -> dict[str, Any]:
    raw = await db.scalar(select(AppSetting.value).where(AppSetting.key == STATE_KEY))
    return dict(raw) if isinstance(raw, dict) else {}


async def _save_state(db: AsyncSession, state: dict[str, Any]) -> None:
    statement = insert(AppSetting).values(key=STATE_KEY, value=state)
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=[AppSetting.key], set_={"value": statement.excluded.value}
        )
    )


def initial_cursor(now: datetime) -> datetime:
    local = now.astimezone(_ZONE)
    year, month = local.year, local.month - INITIAL_MONTHS_BACK
    while month < 1:
        year, month = year - 1, month + 12
    return datetime(year, month, 1, tzinfo=_ZONE)


async def blocked_until(db: AsyncSession, now: datetime) -> Optional[datetime]:
    """Blokada 429 z którejkolwiek ścieżki KSeF (wspólny kontekst i adres IP)."""

    moments = [
        parse_instant((await load_state(db)).get("blocked_until")),
        parse_instant((await people_sync.load_state(db)).get("blocked_until")),
    ]
    future = [moment for moment in moments if moment and moment > now]
    return max(future) if future else None


def _open_source(
    config: KsefConfig,
    *,
    transport: Optional[httpx.AsyncBaseTransport],
    now: datetime,
) -> InvoiceSource:
    if config.mode == "simulate":
        return SimulatedSource(
            config.simulate_dir / SIMULATE_SUBDIR,
            context_nip=config.context_nip,
            now=lambda: now,
        )
    return open_source(config, transport=transport, now=lambda: now)


# ── Zapis faktury ────────────────────────────────────────────────────────────


async def _exists(db: AsyncSession, ksef_number: str) -> bool:
    found = await db.scalar(
        select(ClientSalesInvoice.id).where(
            ClientSalesInvoice.ksef_number == ksef_number
        )
    )
    return found is not None


async def _original_for(
    db: AsyncSession, parsed: fa.ParsedInvoice
) -> Optional[ClientSalesInvoice]:
    if parsed.corrected_ksef_number:
        found = await db.scalar(
            select(ClientSalesInvoice).where(
                ClientSalesInvoice.ksef_number == parsed.corrected_ksef_number
            )
        )
        if found is not None:
            return found
    if parsed.corrected_invoice_number:
        return await db.scalar(
            select(ClientSalesInvoice)
            .where(
                func.lower(ClientSalesInvoice.invoice_number)
                == parsed.corrected_invoice_number.lower(),
                ClientSalesInvoice.invoice_kind == "original",
            )
            .order_by(
                ClientSalesInvoice.issue_date.desc(), ClientSalesInvoice.id.desc()
            )
            .limit(1)
        )
    return None


async def _link_orphan_corrections(
    db: AsyncSession, original: ClientSalesInvoice
) -> None:
    orphans = list(
        await db.scalars(
            select(ClientSalesInvoice).where(
                ClientSalesInvoice.corrected_ksef_number == original.ksef_number,
                ClientSalesInvoice.corrects_invoice_id.is_(None),
                ClientSalesInvoice.id != original.id,
            )
        )
    )
    for orphan in orphans:
        orphan.corrects_invoice_id = original.id
        if orphan.match_reason == "original_missing":
            orphan.match_reason = "original_unmatched"
    if orphans:
        await db.flush()


async def store_invoice(
    db: AsyncSession,
    *,
    ksef_number: str,
    sales: fa_sales.SalesInvoice,
    xml_sha256: str,
    acquired_at: Optional[datetime],
    now: datetime,
    registry: Optional[clients.NipRegistry] = None,
) -> Optional[ClientSalesInvoice]:
    """Zapis faktury i dopasowanie; ``None`` = już była (wyścig o numer KSeF)."""

    parsed = sales.base
    original = await _original_for(db, parsed) if parsed.kind == "correction" else None
    period, period_source = sales.period, sales.period_source
    if (
        original is not None
        and period_source != "invoice"
        and original.period_year is not None
    ):
        period = (int(original.period_year), int(original.period_month))
        period_source = original.period_source
    net = parsed.net_amount
    if net is None:
        net = parsed.gross_amount - parsed.vat_amount
    buyer_nip = (
        parsed.buyer_nip if parsed.buyer_nip and parsed.buyer_nip.isdigit() else None
    )
    invoice = ClientSalesInvoice(
        ksef_number=ksef_number,
        ksef_acquired_at=acquired_at,
        xml_sha256=xml_sha256,
        buyer_nip=buyer_nip if buyer_nip and len(buyer_nip) == 10 else None,
        buyer_name=sales.buyer_name,
        client_id=original.client_id if original is not None else None,
        invoice_number=parsed.invoice_number,
        invoice_type=parsed.invoice_type[:16],
        invoice_kind=parsed.kind,
        corrects_invoice_id=original.id if original is not None else None,
        corrected_ksef_number=parsed.corrected_ksef_number,
        corrected_invoice_number=parsed.corrected_invoice_number,
        issue_date=parsed.issue_date,
        sale_date=parsed.sale_date,
        period_year=period[0] if period else None,
        period_month=period[1] if period else None,
        period_source=period_source if period else None,
        due_date=sales.due_date,
        paid_in_invoice_on=sales.paid_on,
        currency=parsed.currency,
        net_amount=net,
        vat_amount=parsed.vat_amount,
        gross_amount=parsed.gross_amount,
        items=parsed.items,
        order_refs=sales.order_refs,
        match_status="unmatched",
        fetched_at=now,
    )
    try:
        async with db.begin_nested():
            db.add(invoice)
            await db.flush()
    except IntegrityError as exc:
        if await _exists(db, ksef_number):
            return None
        constraint = (
            getattr(exc.orig, "constraint_name", None) or type(exc.orig).__name__
        )
        logger.warning("[client-invoicing] baza odrzuciła fakturę (%s)", constraint)
        raise
    await _link_orphan_corrections(db, invoice)
    await match(db, invoice, registry=registry)
    return invoice


async def match(
    db: AsyncSession,
    invoice: ClientSalesInvoice,
    *,
    registry: Optional[clients.NipRegistry] = None,
) -> bool:
    """``matching.auto_match`` w SAVEPOINT; awaria = faktura do przypisania."""

    try:
        async with db.begin_nested():
            decision = await matching.auto_match(db, invoice, registry=registry)
    except Exception:  # noqa: BLE001 — pobieranie idzie dalej, faktura czeka na Finanse
        logger.exception(
            "[client-invoicing] dopasowanie faktury %s nieudane", invoice.id
        )
        await db.refresh(invoice)
        return False
    return decision.matched


# ── Przebieg ─────────────────────────────────────────────────────────────────


def _defer(run: _Run, ksef_number: str, acquired: Optional[str], reason: str) -> None:
    entry = run.pending.setdefault(
        ksef_number,
        {"ksef_number": ksef_number, "acquired_at": acquired, "attempts": 0},
    )
    entry["attempts"] = int(entry.get("attempts") or 0) + 1
    entry["reason"] = reason
    run.counts["deferred"] += 1


def _problem(run: _Run, ksef_number: str, reason: str) -> None:
    run.problems = [p for p in run.problems if p.get("ksef_number") != ksef_number]
    run.problems.append(
        {"ksef_number": ksef_number, "reason": reason, "at": format_instant(run.now)}
    )
    run.problems = run.problems[-MAX_PROBLEMS:]
    run.pending.pop(ksef_number, None)
    run.counts["failed"] += 1


async def _download_and_store(
    run: _Run, ksef_number: str, acquired: Optional[str]
) -> None:
    if run.downloads_left <= 0:
        _defer(run, ksef_number, acquired, "budget")
        return
    run.downloads_left -= 1
    try:
        xml = await run.source.download_invoice(ksef_number)
    except KsefApiError as exc:
        if exc.category in {"not_ready", "unavailable", "rate_limited"}:
            _defer(run, ksef_number, acquired, exc.category)
            if exc.category == "rate_limited":
                raise
            return
        _problem(run, ksef_number, f"ksef:{exc.category}")
        return
    try:
        sales = fa_sales.parse_sales_invoice(xml)
    except fa.InvoiceParseError as exc:
        _problem(run, ksef_number, f"parse:{exc.code}")
        return
    context = run.config.context_nip
    if sales.base.seller_nip != numbers.seller_nip(ksef_number) or (
        context and sales.base.seller_nip != context
    ):
        _problem(run, ksef_number, "seller_mismatch")
        return
    try:
        invoice = await store_invoice(
            run.db,
            ksef_number=ksef_number,
            sales=sales,
            xml_sha256=hashlib.sha256(xml).hexdigest(),
            acquired_at=parse_instant(acquired),
            now=run.now,
            registry=run.registry,
        )
    except IntegrityError:
        await run.db.rollback()
        _problem(run, ksef_number, "db:constraint")
        return
    await run.db.commit()
    run.pending.pop(ksef_number, None)
    if invoice is None:
        run.counts["duplicates"] += 1
        return
    run.counts["saved"] += 1
    if invoice.match_status == "matched":
        run.counts["matched"] += 1


async def _consider(run: _Run, item: dict[str, Any]) -> None:
    ksef_number = item.get("ksefNumber")
    if not numbers.is_valid(ksef_number):
        run.counts["invalid"] += 1
        return
    run.counts["listed"] += 1
    if await _exists(run.db, ksef_number):
        run.counts["duplicates"] += 1
        run.pending.pop(ksef_number, None)
        return
    acquired = item.get("acquisitionDate")
    await _download_and_store(
        run, ksef_number, acquired if isinstance(acquired, str) else None
    )


async def _retry_pending(run: _Run) -> None:
    for ksef_number, entry in list(run.pending.items()):
        if await _exists(run.db, ksef_number):
            run.pending.pop(ksef_number, None)
            continue
        if int(entry.get("attempts") or 0) >= MAX_PENDING_ATTEMPTS:
            _problem(run, ksef_number, "pending_expired")
            continue
        await _download_and_store(run, ksef_number, entry.get("acquired_at"))


async def _window(
    run: _Run, *, date_from: str, date_to: Optional[str]
) -> Optional[str]:
    current_from = date_from
    page_offset = 0
    hwm: Optional[str] = None
    while True:
        if run.requests_left <= 0:
            raise _BudgetSpent()
        run.requests_left -= 1
        page = await run.source.query_metadata(
            subject_type=SUBJECT_SELLER,
            date_from=current_from,
            date_to=date_to,
            page_offset=page_offset,
        )
        hwm = page.hwm or hwm
        for item in page.invoices:
            await _consider(run, item)
            stamp = item.get("permanentStorageDate")
            if isinstance(stamp, str) and parse_instant(stamp):
                run.progress = stamp
        if not page.has_more:
            return hwm
        if page.is_truncated:
            last = (
                page.invoices[-1].get("permanentStorageDate") if page.invoices else None
            )
            if not isinstance(last, str) or last == current_from:
                raise KsefApiError("invalid_response")
            current_from = last
            page_offset = 0
        else:
            page_offset += 1


async def _incremental(run: _Run, state: dict[str, Any]) -> None:
    """Okna po 99 dni od znacznika; znacznik najwyżej do końca okna (jak etap 4)."""

    cursors: dict[str, str] = dict(state.get("cursors") or {})
    key = run.config.state_key
    cursor = cursors.get(key) or format_instant(initial_cursor(run.now))
    start = parse_instant(cursor) or initial_cursor(run.now)
    try:
        for _ in range(MAX_WINDOWS):
            start = parse_instant(cursor) or initial_cursor(run.now)
            end = start + WINDOW if run.now - start > WINDOW else None
            run.progress = None
            hwm = await _window(
                run, date_from=cursor, date_to=format_instant(end) if end else None
            )
            reached = hwm
            if end is not None:
                hwm_at = parse_instant(hwm)
                if hwm_at is None or hwm_at > end:
                    reached = format_instant(end)
            if reached is None or (parse_instant(reached) or start) <= start:
                break
            cursor = reached
            cursors[key] = cursor
            if end is None:
                break
    except (_BudgetSpent, KsefApiError):
        reached_at = parse_instant(run.progress)
        if run.progress and reached_at is not None and reached_at > start:
            cursors[key] = run.progress
        raise
    finally:
        state["cursors"] = cursors


async def _execute(
    db: AsyncSession,
    config: KsefConfig,
    *,
    now: datetime,
    kind: str,
    source: Optional[InvoiceSource],
    transport: Optional[httpx.AsyncBaseTransport],
) -> dict[str, Any]:
    lock_id = await job_runs.claim(db, LOCK_KIND, LOCK_KEY, now, retake_done=True)
    if lock_id is None:
        return {"status": "busy"}
    state = await load_state(db)
    pending_all: dict[str, list[dict[str, Any]]] = dict(state.get("pending") or {})
    key = config.state_key
    run = _Run(
        db=db,
        config=config,
        source=source or _open_source(config, transport=transport, now=now),
        now=now,
        registry=await clients.nip_registry(db),
        pending={
            str(entry.get("ksef_number")): dict(entry)
            for entry in pending_all.get(key) or []
            if isinstance(entry, dict) and numbers.is_valid(entry.get("ksef_number"))
        },
        problems=list(state.get("problems") or []),
    )
    error: Optional[KsefApiError] = None
    partial = False
    try:
        async with run.source:
            await _retry_pending(run)
            await _incremental(run, state)
    except _BudgetSpent:
        partial = True
    except KsefApiError as exc:
        error = exc
        await db.rollback()
    except Exception:  # noqa: BLE001 — błąd trafia do stanu, przebieg ponowi pętla
        await db.rollback()
        logger.exception("[client-invoicing] przebieg KSeF przerwany")
        error = KsefApiError("internal")

    if error is None:
        try:
            rematched = await matching.rematch_pending(db)
            await db.commit()
            run.counts["rematched"] = rematched["matched"]
        except Exception:  # noqa: BLE001 — ponowne dopasowanie nie zatrzymuje stanu
            await db.rollback()
            logger.exception("[client-invoicing] ponowne dopasowanie nieudane")

    counts = dict(run.counts)
    counts["requests"] = run.source.requests
    counts["pending"] = len(run.pending)
    pending_all[key] = list(run.pending.values())
    started = dict(state.get("last_started") or {})
    started[kind] = format_instant(now)
    state.update(
        pending=pending_all,
        problems=run.problems,
        last_run_at=format_instant(now),
        last_run_kind=kind,
        last_started=started,
        last_counts=counts,
        mode=config.mode,
    )
    if error is None:
        state.update(
            last_success_at=format_instant(now), last_error=None, last_error_text=None
        )
        if not partial:
            state["blocked_until"] = None
    else:
        state.update(
            last_error=error.label,
            last_error_text=error.message,
            last_error_at=format_instant(now),
        )
        if error.category == "rate_limited" and error.retry_after:
            state["blocked_until"] = format_instant(
                now + timedelta(seconds=error.retry_after)
            )
    await _save_state(db, state)
    await job_runs.finish(
        db,
        lock_id,
        status="failed" if error else "done",
        counts=counts,
        error=error.label if error else None,
        commit=False,
    )
    await db.commit()
    logger.info(
        "[client-invoicing] przebieg KSeF %s %s %s",
        kind,
        "błąd " + error.label if error else ("częściowy" if partial else "ok"),
        counts,
    )
    result: dict[str, Any] = {"status": "error" if error else "ok", **counts}
    if partial:
        result["partial"] = True
    if error is not None:
        result["error"] = error.label
        result["error_text"] = error.message
    return result


def _clock(now: Optional[datetime]) -> datetime:
    return now or datetime.now(timezone.utc)


async def run_once(
    db: AsyncSession,
    *,
    now: Optional[datetime] = None,
    source: Optional[InvoiceSource] = None,
    transport: Optional[httpx.AsyncBaseTransport] = None,
) -> dict[str, Any]:
    """Przebieg pętli (co godzinę). Wyłączony KSeF albo moduł = ``disabled``."""

    config = load_config()
    if not config.enabled:
        return {"status": "disabled", "reason": config.disabled_reason}
    if not await module_settings.is_enabled(db):
        return {"status": "disabled", "reason": "module_off"}
    moment = _clock(now)
    if await blocked_until(db, moment):
        return {"status": "skipped", "reason": "blocked"}
    hour = moment.astimezone(_ZONE).strftime("%Y-%m-%dT%H")
    run_id = await job_runs.claim(db, JOB_KIND, hour, moment)
    if run_id is None:
        return {"status": "skipped", "reason": "already_ran"}
    result = await _execute(
        db, config, now=moment, kind="auto", source=source, transport=transport
    )
    await job_runs.finish(
        db,
        run_id,
        status={"ok": "done", "busy": "skipped"}.get(result["status"], "failed"),
        counts={k: v for k, v in result.items() if isinstance(v, int)},
        error=result.get("error"),
    )
    return result


async def fetch_now(
    db: AsyncSession,
    *,
    actor_id: int,
    now: Optional[datetime] = None,
    source: Optional[InvoiceSource] = None,
    transport: Optional[httpx.AsyncBaseTransport] = None,
) -> dict[str, Any]:
    """„Pobierz teraz” — przebieg przyrostowy od razu (Finanse)."""

    moment = _clock(now)
    config = load_config()
    if not config.enabled:
        raise SalesSyncError(DISABLED_DETAIL, 409, "disabled")
    blocked = await blocked_until(db, moment)
    if blocked is not None:
        until = blocked.astimezone(_ZONE).strftime("%H:%M")
        raise SalesSyncError(
            f"KSeF ogranicza liczbę zapytań — spróbuj po {until}.", 409, "blocked"
        )
    started = (await load_state(db)).get("last_started") or {}
    for previous in ("manual", "auto"):
        last = parse_instant(started.get(previous))
        if last is not None and moment - last < MANUAL_COOLDOWN:
            raise SalesSyncError(COOLDOWN_DETAIL, 409, "cooldown")
    result = await _execute(
        db, config, now=moment, kind="manual", source=source, transport=transport
    )
    logger.info("[client-invoicing] „Pobierz teraz” uruchomił użytkownik %s", actor_id)
    if result["status"] == "busy":
        raise SalesSyncError(BUSY_DETAIL, 409, "busy")
    if result["status"] == "error":
        raise SalesSyncError(result["error_text"], 502, "ksef_error")
    return result


async def status(db: AsyncSession) -> dict[str, Any]:
    """Karta stanu dla Finansów: tryb, ostatni przebieg, błąd, blokada, problemy."""

    config = load_config()
    state = await load_state(db)
    now = datetime.now(timezone.utc)
    blocked = await blocked_until(db, now)
    problems = [
        {
            "ksef_number": p.get("ksef_number"),
            "reason": p.get("reason"),
            "text": PROBLEM_LABELS.get(
                str(p.get("reason")), "nie udało się odczytać faktury"
            ),
            "at": p.get("at"),
        }
        for p in state.get("problems") or []
        if isinstance(p, dict)
    ]
    pending = (state.get("pending") or {}).get(config.state_key) or []
    return {
        "mode": config.mode,
        "enabled": config.enabled,
        "disabled_reason": config.disabled_reason,
        "module_enabled": await module_settings.is_enabled(db),
        "last_run_at": state.get("last_run_at"),
        "last_run_kind": state.get("last_run_kind"),
        "last_success_at": state.get("last_success_at"),
        "last_error_text": state.get("last_error_text"),
        "last_error_at": state.get("last_error_at"),
        "blocked_until": format_instant(blocked) if blocked else None,
        "last_counts": state.get("last_counts") or {},
        "pending": len(pending),
        "problems": problems,
    }


__all__ = [
    "JOB_KIND",
    "STATE_KEY",
    "SalesSyncError",
    "fetch_now",
    "initial_cursor",
    "load_state",
    "match",
    "run_once",
    "status",
    "store_invoice",
]
