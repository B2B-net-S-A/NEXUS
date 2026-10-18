"""Pobieranie faktur z KSeF do ``payroll_invoices`` (R1, R7).

Trzy wejścia, jeden przebieg (``_Run``):

* ``run_once(db)`` — pętla co godzinę (wpina koordynator): przyrostowo od
  znacznika ``permanentStorageHwmDate`` z poprzedniego przebiegu,
  ``subjectType=Subject2`` (spółka jako nabywca), okno ``PermanentStorage``
  z ``restrictToPermanentStorageHwmDate`` — dane do znacznika są kompletne,
  więc kolejne okno zaczyna się dokładnie tam, gdzie skończyło poprzednie,
* ``fetch_now(db, actor)`` — „Pobierz teraz” (Płace), ten sam przebieg
  od razu, nie częściej niż co 5 minut,
* ``refetch_period(db, year, month, actor)`` — „Pobierz ponownie okres”:
  okno od początku miesiąca do dziś (np. po dopisaniu NIP-u osobie), bez
  przesuwania znacznika.

Zapisujemy wyłącznie faktury od NIP-ów z ``employee_billing_details``;
pozostałe (dostawcy firmy) to tylko licznik ``skipped`` — bez numeru, NIP-u
i kwot w bazie i w logach. Faktura od znanego NIP-u: XML z KSeF → ``fa``
→ wiersz ``payroll_invoices`` (unikalny numer KSeF, skrót SHA-256 XML-a;
samego XML-a nie trzymamy). Ta sama faktura dopięta wcześniej przez Płace
jako PDF (ten sam NIP sprzedawcy, numer i waluta) nie dostaje drugiego
wiersza: wiersz PDF-u przechodzi na źródło ``ksef`` z numerem KSeF, skrótem
XML-a, datą przyjęcia i kwotami z XML-a (PDF zostaje) — inaczej netto
liczyłoby się dwa razy. Potem ``settlements.match_invoice`` w SAVEPOINT
(awaria dopasowania zostawia fakturę „do przypisania”, nie zatrzymuje
pobierania). Korekta wskazuje fakturę pierwotną (numer KSeF albo numer
faktury tego samego sprzedawcy); korekta, która przyszła przed pierwotną,
dopina się, gdy pierwotna się pojawi.

Limity API (na produkcji 20 zapytań o metadane i 64 pobrania faktury na
godzinę): przebieg robi najwyżej ``MAX_METADATA_REQUESTS`` zapytań
i ``MAX_DOWNLOADS`` pobrań. Faktura jeszcze niegotowa (21165), chwilowa
awaria albo wyczerpany budżet = wpis „w kolejce” (``pending``) ponawiany
w kolejnych przebiegach. Długa blokada 429 zapisuje ``blocked_until``
— do tej chwili nic nie wychodzi do KSeF.

Stan (znacznik per środowisko i NIP spółki, kolejka, ostatni przebieg,
błąd, problemy z odczytem) leży w ``app_settings['hr_ksef_sync']``.
Jeden przebieg naraz pilnuje rezerwacja ``hr_job_runs`` (``ksef_fetch_lock``),
pętlę na godzinę — ``ksef_fetch`` z kluczem godziny.
"""

from __future__ import annotations

import hashlib
import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import DEFAULT_TZ
from app.models.app_setting import AppSetting
from app.models.hr_settlement import EmployeeBillingDetails, PayrollInvoice
from app.services.hr import audit, job_runs, settlements
from app.services.hr.ksef import fa, numbers
from app.services.hr.ksef.client import (
    SUBJECT_BUYER,
    KsefApiError,
    format_instant,
    parse_instant,
)
from app.services.hr.ksef.environment import KsefConfig, load_config
from app.services.hr.ksef.source import InvoiceSource, open_source
from app.services.hr.modules import HrModule, load_modules
from app.services.hr.payroll_errors import PayrollError
from app.services.hr.payroll_periods import add_months

logger = logging.getLogger(__name__)

STATE_KEY = "hr_ksef_sync"
JOB_KIND = "ksef_fetch"
LOCK_KIND = "ksef_fetch_lock"
LOCK_KEY = "global"
#: API: zakres dat zapytania najwyżej 100 dni.
WINDOW = timedelta(days=99)
MAX_WINDOWS = 4
#: Produkcja: 20 zapytań o metadane na godzinę — pętla bierze najwyżej 8.
MAX_METADATA_REQUESTS = 8
#: Produkcja: 64 pobrania faktury na godzinę.
MAX_DOWNLOADS = 40
MANUAL_COOLDOWN = timedelta(minutes=5)
MAX_PENDING_ATTEMPTS = 24
MAX_PROBLEMS = 20
REFETCH_MONTHS_BACK = 12
_ZONE = ZoneInfo(DEFAULT_TZ)

DISABLED_DETAIL = "Pobieranie z KSeF jest wyłączone."
BUSY_DETAIL = "Pobieranie z KSeF właśnie trwa. Odśwież za chwilę."
COOLDOWN_DETAIL = "Faktury z KSeF były pobierane przed chwilą — spróbuj za kilka minut."
REFETCH_RANGE_DETAIL = "Ponownie pobrać można miesiąc z ostatnich 12 miesięcy."

PROBLEM_LABELS = {
    "seller_mismatch": "NIP sprzedawcy w pliku inny niż w KSeF",
    "buyer_mismatch": "nabywcą nie jest spółka",
    "pending_expired": "faktura długo niedostępna do pobrania",
}


class KsefSyncError(PayrollError):
    """Przebieg nie ruszył (wyłączony, trwa, za wcześnie) albo KSeF odmówił."""


@dataclass
class _Run:
    db: AsyncSession
    config: KsefConfig
    source: InvoiceSource
    now: datetime
    known: dict[str, list[int]]
    pending: dict[str, dict[str, Any]]
    problems: list[dict[str, Any]]
    counts: Counter = field(default_factory=Counter)
    requests_left: int = MAX_METADATA_REQUESTS
    downloads_left: int = MAX_DOWNLOADS
    #: ``permanentStorageDate`` ostatniego przetworzonego rekordu bieżącego okna.
    progress: Optional[str] = None


class _BudgetSpent(Exception):
    """Wyczerpany budżet zapytań przebiegu — reszta w następnym."""


class InvoiceRejected(Exception):
    """Baza nie przyjęła faktury (ograniczenie inne niż unikalny numer KSeF)."""


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


def _iso(moment: Optional[datetime]) -> Optional[str]:
    return format_instant(moment) if moment else None


def initial_cursor(now: datetime) -> datetime:
    """Pierwszy przebieg: od 1. dnia poprzedniego miesiąca (Warszawa)."""

    local = now.astimezone(_ZONE)
    year, month = add_months(local.year, local.month, -1)
    return datetime.combine(date(year, month, 1), time.min, tzinfo=_ZONE)


def _local_month_start(year: int, month: int) -> datetime:
    return datetime.combine(date(year, month, 1), time.min, tzinfo=_ZONE)


# ── Zapis faktury ────────────────────────────────────────────────────────────


async def known_nips(db: AsyncSession) -> dict[str, list[int]]:
    """NIP → osoby z tym NIP-em w danych do rozliczeń (zwykle jedna)."""

    rows = await db.execute(
        select(EmployeeBillingDetails.nip, EmployeeBillingDetails.user_id)
        .where(EmployeeBillingDetails.nip.is_not(None))
        .order_by(EmployeeBillingDetails.user_id)
    )
    known: dict[str, list[int]] = {}
    for nip, user_id in rows:
        known.setdefault(nip, []).append(int(user_id))
    return known


async def _exists(db: AsyncSession, ksef_number: str) -> bool:
    found = await db.scalar(
        select(PayrollInvoice.id).where(PayrollInvoice.ksef_number == ksef_number)
    )
    return found is not None


async def _original_for(
    db: AsyncSession, parsed: fa.ParsedInvoice
) -> Optional[PayrollInvoice]:
    if parsed.corrected_ksef_number:
        # Numer KSeF zaczyna się NIP-em sprzedawcy: korekta cudzej faktury to nie
        # korekta — bez wskazania (inaczej zmieniłaby rozliczenie innej osoby).
        if numbers.seller_nip(parsed.corrected_ksef_number) != parsed.seller_nip:
            return None
        found = await db.scalar(
            select(PayrollInvoice).where(
                PayrollInvoice.ksef_number == parsed.corrected_ksef_number,
                PayrollInvoice.seller_nip == parsed.seller_nip,
            )
        )
        if found is not None:
            return found
    if parsed.corrected_invoice_number:
        return await db.scalar(
            select(PayrollInvoice)
            .where(
                PayrollInvoice.seller_nip == parsed.seller_nip,
                PayrollInvoice.invoice_number == parsed.corrected_invoice_number,
                PayrollInvoice.invoice_kind == "original",
            )
            .order_by(PayrollInvoice.issue_date.desc(), PayrollInvoice.id.desc())
            .limit(1)
        )
    return None


async def match(db: AsyncSession, invoice: PayrollInvoice) -> bool:
    """``settlements.match_invoice`` w SAVEPOINT; awaria = faktura do przypisania."""

    try:
        async with db.begin_nested():
            settlement = await settlements.match_invoice(db, invoice)
    except Exception:  # noqa: BLE001 — pobieranie idzie dalej, faktura czeka na Płace
        logger.exception("ksef: dopasowanie faktury %s nieudane", invoice.id)
        await db.refresh(invoice)
        return False
    return settlement is not None


async def _link_orphan_corrections(
    db: AsyncSession, original: PayrollInvoice
) -> list[PayrollInvoice]:
    """Korekty, które przyszły przed fakturą pierwotną, dostają do niej wskazanie."""

    if not original.ksef_number or original.invoice_kind != "original":
        return []
    orphans = list(
        await db.scalars(
            select(PayrollInvoice).where(
                PayrollInvoice.corrected_ksef_number == original.ksef_number,
                PayrollInvoice.seller_nip == original.seller_nip,
                PayrollInvoice.corrects_invoice_id.is_(None),
                PayrollInvoice.id != original.id,
            )
        )
    )
    for orphan in orphans:
        orphan.corrects_invoice_id = original.id
        if orphan.period_year is None and original.period_year is not None:
            orphan.period_year = original.period_year
            orphan.period_month = original.period_month
    if orphans:
        await db.flush()
    return orphans


async def _manual_twin(
    db: AsyncSession, parsed: fa.ParsedInvoice
) -> Optional[PayrollInvoice]:
    """PDF dopięty ręcznie, który jest tą samą fakturą co ta z KSeF."""

    if parsed.kind != "original":
        return None
    return await db.scalar(
        select(PayrollInvoice)
        .where(
            PayrollInvoice.source == "manual_pdf",
            PayrollInvoice.ksef_number.is_(None),
            PayrollInvoice.invoice_kind == "original",
            PayrollInvoice.seller_nip == parsed.seller_nip,
            PayrollInvoice.currency == parsed.currency,
            func.lower(PayrollInvoice.invoice_number) == parsed.invoice_number.lower(),
        )
        .order_by(PayrollInvoice.id)
        .limit(1)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


async def _bind_twin(
    db: AsyncSession,
    twin: PayrollInvoice,
    *,
    ksef_number: str,
    parsed: fa.ParsedInvoice,
    net: Decimal,
    period: Optional[tuple[int, int]],
    xml_sha256: str,
    user_id: Optional[int],
    acquired_at: Optional[datetime],
    now: datetime,
) -> Optional[PayrollInvoice]:
    """Wiersz PDF-u dostaje numer KSeF i kwoty z XML-a (dokument z KSeF wiąże)."""

    changed = (twin.net_amount, twin.vat_amount, twin.gross_amount) != (
        net,
        parsed.vat_amount,
        parsed.gross_amount,
    )
    try:
        async with db.begin_nested():
            twin.source = "ksef"
            twin.ksef_number = ksef_number
            twin.ksef_acquired_at = acquired_at
            twin.xml_sha256 = xml_sha256
            twin.issue_date = parsed.issue_date
            twin.sale_date = parsed.sale_date or twin.sale_date
            if twin.period_year is None and period is not None:
                twin.period_year, twin.period_month = period
            twin.net_amount = net
            twin.vat_amount = parsed.vat_amount
            twin.gross_amount = parsed.gross_amount
            twin.items = parsed.items
            twin.fetched_at = now
            if twin.user_id is None:
                twin.user_id = user_id
            await db.flush()
    except IntegrityError:
        if await _exists(db, ksef_number):
            return None
        raise InvoiceRejected("payroll_invoices") from None
    if changed and twin.match_status == "matched" and twin.settlement_id:
        settlement = await settlements.lock_settlement(db, twin.settlement_id)
        if settlement is not None and settlement.status != "paid":
            # Inne kwoty niż wpisane z PDF-u = nowy dokument; uznanie od nowa.
            settlements.clear_override(settlement)
    audit.record(
        db,
        actor_user_id=None,
        subject_user_id=twin.user_id,
        entity_type="payroll_invoice",
        entity_id=twin.id,
        action="payroll_invoice_ksef_linked",
        sensitivity="payroll",
        details={"amounts_changed": changed, "match_status": twin.match_status},
    )
    corrections = await _link_orphan_corrections(db, twin)
    await match(db, twin)
    for correction in corrections:
        await match(db, correction)
    return twin


async def store_ksef_invoice(
    db: AsyncSession,
    *,
    ksef_number: str,
    parsed: fa.ParsedInvoice,
    xml_sha256: str,
    user_id: Optional[int],
    acquired_at: Optional[datetime],
    now: datetime,
) -> Optional[PayrollInvoice]:
    """Zapis faktury z KSeF i dopasowanie; ``None`` = już była (wyścig o numer)."""

    original = await _original_for(db, parsed) if parsed.kind == "correction" else None
    period = parsed.period
    if period is None and original is not None and original.period_year is not None:
        period = (int(original.period_year), int(original.period_month))
    net = parsed.net_amount
    if net is None:
        net = parsed.gross_amount - parsed.vat_amount
    twin = await _manual_twin(db, parsed)
    if twin is not None:
        return await _bind_twin(
            db,
            twin,
            ksef_number=ksef_number,
            parsed=parsed,
            net=net,
            period=period,
            xml_sha256=xml_sha256,
            user_id=user_id,
            acquired_at=acquired_at,
            now=now,
        )
    invoice = PayrollInvoice(
        source="ksef",
        ksef_number=ksef_number,
        ksef_acquired_at=acquired_at,
        seller_nip=parsed.seller_nip,
        user_id=user_id,
        invoice_number=parsed.invoice_number,
        invoice_kind=parsed.kind,
        corrects_invoice_id=original.id if original else None,
        corrected_ksef_number=parsed.corrected_ksef_number,
        issue_date=parsed.issue_date,
        sale_date=parsed.sale_date,
        period_year=period[0] if period else None,
        period_month=period[1] if period else None,
        currency=parsed.currency,
        net_amount=net,
        vat_amount=parsed.vat_amount,
        gross_amount=parsed.gross_amount,
        items=parsed.items,
        xml_sha256=xml_sha256,
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
        # Treść błędu bazy cytuje wiersz (NIP, kwoty) — do logu tylko ograniczenie.
        constraint = (
            getattr(exc.orig, "constraint_name", None) or type(exc.orig).__name__
        )
        logger.warning("ksef: baza odrzuciła fakturę (%s)", constraint)
        raise InvoiceRejected(str(constraint)) from None
    corrections = await _link_orphan_corrections(db, invoice)
    await match(db, invoice)
    for correction in corrections:
        await match(db, correction)
    return invoice


# ── Przebieg ─────────────────────────────────────────────────────────────────


def _owner(run: _Run, seller_nip: str) -> Optional[int]:
    owners = run.known.get(seller_nip) or []
    # Ten sam NIP u dwóch osób — osobę wskazują Płace przy przypisaniu.
    return owners[0] if len(owners) == 1 else None


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
    seller = numbers.seller_nip(ksef_number)
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
        parsed = fa.parse_invoice(xml)
    except fa.InvoiceParseError as exc:
        _problem(run, ksef_number, f"parse:{exc.code}")
        return
    if parsed.seller_nip != seller:
        _problem(run, ksef_number, "seller_mismatch")
        return
    context = run.config.context_nip
    if context and parsed.buyer_nip and parsed.buyer_nip != context:
        _problem(run, ksef_number, "buyer_mismatch")
        return
    try:
        invoice = await store_ksef_invoice(
            run.db,
            ksef_number=ksef_number,
            parsed=parsed,
            xml_sha256=hashlib.sha256(xml).hexdigest(),
            user_id=_owner(run, seller),
            acquired_at=parse_instant(acquired),
            now=run.now,
        )
    except InvoiceRejected:
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
    seller = (item.get("seller") or {}).get("nip") or numbers.seller_nip(ksef_number)
    if seller not in run.known:
        # Dostawca firmy — tylko licznik, bez śladu w bazie i logach.
        run.counts["skipped"] += 1
        return
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
        if numbers.seller_nip(ksef_number) not in run.known:
            # NIP zniknął z danych do rozliczeń — faktury już nie zapisujemy.
            run.pending.pop(ksef_number, None)
            continue
        if int(entry.get("attempts") or 0) >= MAX_PENDING_ATTEMPTS:
            _problem(run, ksef_number, "pending_expired")
            continue
        await _download_and_store(run, ksef_number, entry.get("acquired_at"))


async def _window(
    run: _Run,
    *,
    date_from: str,
    date_to: Optional[str],
    seller_nip: Optional[str] = None,
) -> Optional[str]:
    """Jedno okno dat (wszystkie strony); zwraca ``permanentStorageHwmDate``."""

    current_from = date_from
    page_offset = 0
    hwm: Optional[str] = None
    while True:
        if run.requests_left <= 0:
            raise _BudgetSpent()
        run.requests_left -= 1
        page = await run.source.query_metadata(
            subject_type=SUBJECT_BUYER,
            date_from=current_from,
            date_to=date_to,
            seller_nip=seller_nip,
            page_offset=page_offset,
        )
        hwm = page.hwm or hwm
        for item in page.invoices:
            await _consider(run, item)
            stamp = item.get("permanentStorageDate")
            if isinstance(stamp, str) and parse_instant(stamp):
                # Rekordy idą rosnąco: wszystko do tej chwili jest przetworzone.
                run.progress = stamp
        if not page.has_more:
            return hwm
        if page.is_truncated:
            # Limit 10 000 wyników: zawężamy okno od ostatniego rekordu.
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
    cursors: dict[str, str] = dict(state.get("cursors") or {})
    key = run.config.state_key
    cursor = cursors.get(key) or format_instant(initial_cursor(run.now))
    start = parse_instant(cursor) or initial_cursor(run.now)
    try:
        for _ in range(MAX_WINDOWS):
            start = parse_instant(cursor) or initial_cursor(run.now)
            end = start + WINDOW if run.now - start > WINDOW else None
            run.progress = None
            hwm = await _window(run, date_from=cursor, date_to=_iso(end))
            reached = hwm
            if end is not None:
                # Okno przycięte do 99 dni: KSeF podaje HWM całego magazynu,
                # często dalej niż koniec okna — znacznik idzie najwyżej do
                # końca okna (min(HWM, koniec)), inaczej przeskoczyłby faktury
                # między końcem okna a HWM, o które nikt nie zapytał.
                hwm_at = parse_instant(hwm)
                if hwm_at is None or hwm_at > end:
                    reached = _iso(end)
            if reached is None or (parse_instant(reached) or start) <= start:
                break
            cursor = reached
            cursors[key] = cursor
            if end is None:
                break
    except (_BudgetSpent, KsefApiError):
        # Przerwane okno: znacznik idzie do ostatniego przetworzonego rekordu
        # (rekordy rosnąco, okno do HWM jest kompletne). Inaczej każdy przebieg
        # czytałby od nowa te same pierwsze strony i nie doszedł do najnowszych.
        # Ten sam rekord w następnym oknie odsiewa unikalny numer KSeF.
        reached_at = parse_instant(run.progress)
        if run.progress and reached_at is not None and reached_at > start:
            cursors[key] = run.progress
        raise
    finally:
        state["cursors"] = cursors


async def _refetch(run: _Run, *, start: datetime, seller_nip: Optional[str]) -> None:
    window_start = start
    for _ in range(MAX_WINDOWS):
        end = window_start + WINDOW
        open_ended = end >= run.now
        await _window(
            run,
            date_from=format_instant(window_start),
            date_to=None if open_ended else format_instant(end),
            seller_nip=seller_nip,
        )
        if open_ended:
            return
        window_start = end


async def _execute(
    db: AsyncSession,
    config: KsefConfig,
    *,
    now: datetime,
    kind: str,
    source: Optional[InvoiceSource],
    transport: Optional[httpx.AsyncBaseTransport],
    refetch_from: Optional[datetime] = None,
    seller_nip: Optional[str] = None,
) -> dict[str, Any]:
    """Przebieg pod rezerwacją ``ksef_fetch_lock``; stan zapisany zawsze."""

    lock_id = await job_runs.claim(db, LOCK_KIND, LOCK_KEY, now, retake_done=True)
    if lock_id is None:
        return {"status": "busy"}
    state = await load_state(db)
    pending_all: dict[str, list[dict[str, Any]]] = dict(state.get("pending") or {})
    key = config.state_key
    run = _Run(
        db=db,
        config=config,
        source=source or open_source(config, transport=transport, now=lambda: now),
        now=now,
        known=await known_nips(db),
        pending={
            str(entry.get("ksef_number")): dict(entry)
            for entry in pending_all.get(key) or []
            if isinstance(entry, dict) and numbers.is_valid(entry.get("ksef_number"))
        },
        problems=list(state.get("problems") or []),
        requests_left=MAX_METADATA_REQUESTS,
        downloads_left=MAX_DOWNLOADS,
    )
    error: Optional[KsefApiError] = None
    partial = False
    try:
        async with run.source:
            if kind != "refetch":
                await _retry_pending(run)
            if kind == "refetch" and refetch_from is not None:
                await _refetch(run, start=refetch_from, seller_nip=seller_nip)
            else:
                await _incremental(run, state)
    except _BudgetSpent:
        partial = True
    except KsefApiError as exc:
        error = exc
        await db.rollback()
    except Exception:  # noqa: BLE001 — błąd trafia do stanu i karty, przebieg ponowi pętla
        await db.rollback()
        logger.exception("ksef: przebieg przerwany")
        error = KsefApiError("internal")

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
            last_success_at=format_instant(now),
            last_error=None,
            last_error_text=None,
            last_error_at=None,
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
        "ksef: przebieg %s %s %s",
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


def _blocked(state: dict[str, Any], now: datetime) -> Optional[datetime]:
    until = parse_instant(state.get("blocked_until"))
    return until if until and until > now else None


async def _blocked_any(
    db: AsyncSession, now: datetime, state: Optional[dict[str, Any]] = None
) -> Optional[datetime]:
    """Blokada 429 z tej ścieżki albo z faktur sprzedażowych (E8) — limit KSeF
    jest wspólny dla tokenu spółki, więc obie ścieżki czekają na siebie."""
    from app.services.client_invoicing import sync as sales_sync  # noqa: PLC0415

    own = _blocked(state if state is not None else await load_state(db), now)
    sales = _blocked(await sales_sync.load_state(db), now)
    candidates = [moment for moment in (own, sales) if moment is not None]
    return max(candidates) if candidates else None


def _clock(now: Optional[datetime]) -> datetime:
    return now or datetime.now(timezone.utc)


async def run_once(
    db: AsyncSession,
    *,
    now: Optional[datetime] = None,
    source: Optional[InvoiceSource] = None,
    transport: Optional[httpx.AsyncBaseTransport] = None,
) -> dict[str, Any]:
    """Przebieg pętli (co godzinę). Wyłączony tryb albo moduł = ``disabled``."""

    config = load_config()
    if not config.enabled:
        return {"status": "disabled", "reason": config.disabled_reason}
    if not (await load_modules(db)).get(HrModule.settlements):
        return {"status": "disabled", "reason": "module_off"}
    moment = _clock(now)
    if await _blocked_any(db, moment):
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


async def _manual_guard(db: AsyncSession, now: datetime, kind: str) -> KsefConfig:
    """Wyłączony tryb, blokada 429 i odstęp 5 minut = 409 z powodem."""

    config = load_config()
    if not config.enabled:
        raise KsefSyncError(DISABLED_DETAIL, 409, code="disabled")
    state = await load_state(db)
    blocked = await _blocked_any(db, now, state)
    if blocked is not None:
        until = blocked.astimezone(_ZONE).strftime("%H:%M")
        raise KsefSyncError(
            f"KSeF ogranicza liczbę zapytań — spróbuj po {until}.", 409, code="blocked"
        )
    started = state.get("last_started") or {}
    # „Pobierz teraz” liczy odstęp także od przebiegu pętli; okres — od okresu.
    kinds = ("manual", "auto") if kind == "manual" else (kind,)
    for previous in kinds:
        last = parse_instant(started.get(previous))
        if last is not None and now - last < MANUAL_COOLDOWN:
            raise KsefSyncError(COOLDOWN_DETAIL, 409, code="cooldown")
    return config


def _manual_result(result: dict[str, Any]) -> dict[str, Any]:
    if result["status"] == "busy":
        raise KsefSyncError(BUSY_DETAIL, 409, code="busy")
    if result["status"] == "error":
        raise KsefSyncError(result["error_text"], 502, code="ksef_error", data=result)
    return result


async def fetch_now(
    db: AsyncSession,
    *,
    actor_id: int,
    now: Optional[datetime] = None,
    source: Optional[InvoiceSource] = None,
    transport: Optional[httpx.AsyncBaseTransport] = None,
) -> dict[str, Any]:
    """„Pobierz teraz” — przebieg przyrostowy od razu (Płace)."""

    moment = _clock(now)
    config = await _manual_guard(db, moment, "manual")
    result = await _execute(
        db, config, now=moment, kind="manual", source=source, transport=transport
    )
    logger.info("ksef: „Pobierz teraz” uruchomił użytkownik %s", actor_id)
    return _manual_result(result)


async def refetch_period(
    db: AsyncSession,
    *,
    year: int,
    month: int,
    actor_id: int,
    seller_nip: Optional[str] = None,
    now: Optional[datetime] = None,
    source: Optional[InvoiceSource] = None,
    transport: Optional[httpx.AsyncBaseTransport] = None,
) -> dict[str, Any]:
    """„Pobierz ponownie okres” — od 1. dnia miesiąca do dziś, bez znacznika."""

    moment = _clock(now)
    start = _local_month_start(year, month)
    local = moment.astimezone(_ZONE)
    oldest = _local_month_start(
        *add_months(local.year, local.month, -REFETCH_MONTHS_BACK)
    )
    if start > moment or start < oldest:
        raise KsefSyncError(REFETCH_RANGE_DETAIL, 422, code="range")
    config = await _manual_guard(db, moment, "refetch")
    result = await _execute(
        db,
        config,
        now=moment,
        kind="refetch",
        source=source,
        transport=transport,
        refetch_from=start,
        seller_nip=seller_nip,
    )
    logger.info(
        "ksef: „Pobierz ponownie okres” %04d-%02d uruchomił użytkownik %s",
        year,
        month,
        actor_id,
    )
    return _manual_result(result)


__all__ = [
    "JOB_KIND",
    "KsefSyncError",
    "STATE_KEY",
    "fetch_now",
    "initial_cursor",
    "known_nips",
    "load_state",
    "match",
    "refetch_period",
    "run_once",
    "store_ksef_invoice",
]
