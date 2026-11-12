"""Zapłaty faktur do klientów odczytane z eBI24 (decyzja Artura z 10.11.2026).

Faktury do klientów NEXUS ma z KSeF; to, czy klient zapłacił, Finanse
oznaczają w eBI24. Przebieg co godzinę czyta nagłówki faktur przychodowych
eBI24 z ostatnich ``LOOKBACK_DAYS`` dni (``bucket/index`` — zapłata jest
w nagłówku listy, ``getDocument`` jej nie ma; pomiar na UAT 12.11.2026)
i dopasowuje je do faktur NEXUSA wyłącznie po numerze KSeF.

Jeden dokument eBI24 = najwyżej jeden wiersz ``kind='ebi24'``, który jest
lustrem stanu w eBI24: kwota zapłacona (``paidAmount``, a bez niej całe
brutto przy ``paid``) i data (``paidDate``). Zmiana w eBI24 zmienia wiersz,
cofnięcie zapłaty zostawia go jako ``ignored`` z powodem.

Własny zapis NEXUSA wygrywa: gdy faktura ma uznanie z wyciągu albo ręczne
„opłacono”, wiersz z eBI24 jest ``ignored`` („zastąpiona”), żeby ta sama
wpłata nie liczyła się dwa razy.

Zapis tylko w trybie ``EBI24_MODE=prod``; na UAT ``run_once(dry_run=True)``
daje same liczniki. Logi: liczby, bez numerów, NIP-ów i kwot.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Callable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_today
from app.models.client_sales_invoice import (
    ClientSalesInvoice,
    ClientSalesInvoicePayment,
)
from app.models.hr_ops import HrJobRun
from app.services.client_invoicing import ledger
from app.services.client_invoicing import settings as module_settings
from app.services.client_invoicing.billing import money
from app.services.client_invoicing.ledger import ZERO, Chain
from app.services.client_invoicing.payments import EBI24_SUPERSEDED as SUPERSEDED
from app.services.client_sales_invoices_schema import EBI24_DOCUMENT_ID_MAX
from app.services.ebi24.client import PAGE_SIZE_MAX, Ebi24ApiError, Ebi24Client
from app.services.ebi24.environment import Ebi24Config, load_config
from app.services.hr import job_runs

logger = logging.getLogger(__name__)

JOB_KIND = "sales_ebi24_payments"
LOOKBACK_DAYS = 180
MAX_PAGES = 20
#: Grosze; więcej niż ``AMOUNT_MAX`` z ograniczenia tabeli to błąd danych.
MAX_MINOR = 10_000_000_000
HEALTHY_WITHIN = timedelta(hours=3)

REVOKED = "W eBI24 faktura nie jest już oznaczona jako opłacona."
REPLACED = "Zastąpiona nowszym dokumentem eBI24 tej samej faktury."


@dataclass(frozen=True)
class Ebi24Paid:
    """Nagłówek faktury eBI24 w kształcie potrzebnym do zapłaty."""

    document_id: str
    ksef_number: Optional[str]
    paid: bool
    paid_amount: Optional[Decimal]
    gross: Optional[Decimal]
    paid_on: Optional[date]

    @property
    def value(self) -> Optional[Decimal]:
        """Ile zapłacono według eBI24; ``None`` = nic."""

        if self.paid_amount is not None and self.paid_amount > ZERO:
            return self.paid_amount
        if self.paid and self.gross is not None and self.gross > ZERO:
            return self.gross
        return None


@dataclass(frozen=True)
class Existing:
    amount: Decimal
    booked_on: Optional[date]
    match_status: str


@dataclass(frozen=True)
class Decision:
    """``create`` | ``update`` | ``revoke`` | ``keep`` | ``skip``."""

    action: str
    amount: Optional[Decimal] = None
    booked_on: Optional[date] = None
    reason: Optional[str] = None


# ── Czyste reguły ────────────────────────────────────────────────────────────


def _minor(value: object) -> Optional[Decimal]:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value < 0 or value > MAX_MINOR:
        return None
    return money(Decimal(value) / 100)


def _day(value: object) -> Optional[date]:
    if not isinstance(value, str) or len(value) < 10:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def read_header(row: dict[str, Any]) -> Optional[Ebi24Paid]:
    """Nagłówek z ``bucket/index``; dokument bez poprawnego ``_id`` pomijamy."""

    document_id = row.get("_id")
    if not isinstance(document_id, str) or not (
        0 < len(document_id) <= EBI24_DOCUMENT_ID_MAX
    ):
        return None
    ksef = row.get("_ksefReferenceNumber")
    return Ebi24Paid(
        document_id=document_id,
        ksef_number=ksef.strip() if isinstance(ksef, str) and ksef.strip() else None,
        paid=row.get("paid") is True,
        paid_amount=_minor(row.get("paidAmount")),
        gross=_minor(row.get("grossAmount")),
        paid_on=_day(row.get("paidDate")),
    )


def decide(
    paid: Ebi24Paid,
    existing: Optional[Existing],
    *,
    recorded_elsewhere: bool,
    today: date,
) -> Decision:
    """Co zrobić z wierszem ``ebi24`` dla jednej faktury (testy bez bazy)."""

    active = existing is not None and existing.match_status == "matched"
    if recorded_elsewhere:
        return Decision("revoke", reason=SUPERSEDED) if active else Decision("skip")
    value = paid.value
    if value is None:
        return Decision("revoke", reason=REVOKED) if active else Decision("skip")
    booked_on = paid.paid_on or (existing.booked_on if existing else None) or today
    if active and existing.amount == value and existing.booked_on == booked_on:
        return Decision("keep")
    return Decision(
        "update" if existing is not None else "create",
        amount=value,
        booked_on=booked_on,
    )


def recorded_in_nexus(chain: Chain) -> bool:
    """Uznanie z wyciągu, ręczne „opłacono” albo zapłata w treści faktury."""

    if chain.head.paid_in_invoice_on is not None:
        return True
    return any(p.kind != "ebi24" for p in chain.payments)


# ── Odczyt z eBI24 ───────────────────────────────────────────────────────────


def criteria(since: date) -> dict[str, Any]:
    return {
        "_constructor": "AdvancedCriteria",
        "operator": "and",
        "criteria": [
            {
                "fieldName": "_schemaName",
                "operator": "equals",
                "value": "INCOME_INVOICE",
            },
            {
                "fieldName": "issuedDate",
                "operator": "greaterOrEqual",
                "value": since.isoformat(),
            },
        ],
    }


async def fetch_headers(client: Ebi24Client, since: date) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    start = 0
    for _ in range(MAX_PAGES):
        page = await client.list_documents(
            criteria(since),
            start_row=start,
            end_row=start + PAGE_SIZE_MAX,
            sort_by=["_bucketNumber"],
        )
        rows.extend(page.documents)
        start += PAGE_SIZE_MAX
        if not page.documents or start >= page.total:
            return rows
    logger.warning(
        "[ebi24-payments] więcej niż %s stron — reszta w kolejnym przebiegu", MAX_PAGES
    )
    return rows


# ── Zapis ────────────────────────────────────────────────────────────────────


async def apply(
    db: AsyncSession,
    headers: list[dict[str, Any]],
    *,
    today: date,
    dry_run: bool,
) -> Counter[str]:
    """Nagłówki eBI24 → wiersze ``ebi24`` (bez commita)."""

    counts: Counter[str] = Counter(fetched=len(headers))
    read = [h for h in (read_header(row) for row in headers) if h is not None]
    counts["unreadable"] = len(headers) - len(read)
    by_ksef: dict[str, list[Ebi24Paid]] = {}
    for item in read:
        if item.ksef_number:
            by_ksef.setdefault(item.ksef_number, []).append(item)
    counts["without_ksef"] = sum(1 for item in read if not item.ksef_number)
    if not by_ksef:
        return counts

    invoices = {
        invoice.ksef_number: invoice
        for invoice in await db.scalars(
            select(ClientSalesInvoice).where(
                ClientSalesInvoice.ksef_number.in_(list(by_ksef))
            )
        )
    }
    counts["not_in_nexus"] = sum(
        len(items) for ksef, items in by_ksef.items() if ksef not in invoices
    )
    chain_of: dict[int, Chain] = {}
    for chain in await ledger.build_chains(
        db, list(await db.scalars(select(ClientSalesInvoice)))
    ):
        for invoice in chain.invoices:
            chain_of[invoice.id] = chain
    existing = {
        row.ebi24_document_id: row
        for row in await db.scalars(
            select(ClientSalesInvoicePayment).where(
                ClientSalesInvoicePayment.kind == "ebi24",
                ClientSalesInvoicePayment.ebi24_document_id.in_(
                    [item.document_id for items in by_ksef.values() for item in items]
                ),
            )
        )
    }

    for ksef, items in by_ksef.items():
        invoice = invoices.get(ksef)
        if invoice is None:
            continue
        if len(items) > 1:
            # Ten sam numer KSeF na kilku dokumentach eBI24 — nie zgadujemy.
            counts["ambiguous"] += len(items)
            continue
        item = items[0]
        row = existing.get(item.document_id)
        chain = chain_of[invoice.id]
        decision = decide(
            item,
            Existing(money(Decimal(row.amount)), row.booked_on, row.match_status)
            if row is not None
            else None,
            recorded_elsewhere=recorded_in_nexus(chain),
            today=today,
        )
        counts[decision.action] += 1
        if dry_run or decision.action in {"keep", "skip"}:
            continue
        if decision.action == "revoke":
            row.match_status = "ignored"
            row.reason = decision.reason
            continue
        # Inny dokument eBI24 tej samej faktury (skasowany i założony od nowa)
        # przestaje się liczyć — łańcuch ma najwyżej jedno lustro z eBI24.
        for other in chain.payments:
            if other.kind == "ebi24" and other.ebi24_document_id != item.document_id:
                other.match_status = "ignored"
                other.reason = REPLACED
                counts["replaced"] += 1
        if row is None:
            row = ClientSalesInvoicePayment(
                kind="ebi24", ebi24_document_id=item.document_id
            )
            db.add(row)
        row.invoice_id = invoice.id
        row.match_status = "matched"
        row.amount = decision.amount
        row.currency = invoice.currency
        row.booked_on = decision.booked_on
        row.reason = None
    await db.flush()
    return counts


async def run_once(
    db: AsyncSession,
    *,
    dry_run: bool = False,
    now: Optional[datetime] = None,
    client_factory: Callable[[Ebi24Config], Ebi24Client] = Ebi24Client,
) -> dict[str, Any]:
    """Przebieg pętli (raz na godzinę) albo podgląd z liczbami (``dry_run``)."""

    config = load_config()
    if not config.enabled:
        return {"status": "disabled", "reason": "ebi24_off"}
    if not dry_run and config.mode != "prod":
        return {"status": "disabled", "reason": "not_prod"}
    if not await module_settings.is_enabled(db):
        return {"status": "disabled", "reason": "module_off"}
    moment = now or datetime.now(timezone.utc)
    run_id = None
    if not dry_run:
        run_id = await job_runs.claim(
            db, JOB_KIND, moment.strftime("%Y-%m-%dT%H"), moment
        )
        if run_id is None:
            return {"status": "skipped", "reason": "already_ran"}
    today = business_today()
    try:
        async with client_factory(config) as client:
            headers = await fetch_headers(client, today - timedelta(days=LOOKBACK_DAYS))
        counts = dict(await apply(db, headers, today=today, dry_run=dry_run))
    except Ebi24ApiError as exc:
        await db.rollback()
        if run_id is not None:
            await job_runs.finish(
                db, run_id, status="failed", counts={}, error=exc.category
            )
        logger.warning("[ebi24-payments] przerwane: %s", exc.category)
        return {"status": "failed", "error": exc.category}
    if run_id is None:
        await db.rollback()
    else:
        await job_runs.finish(db, run_id, status="done", counts=counts, commit=False)
        await db.commit()
    logger.info("[ebi24-payments] %s", counts)
    return {"status": "dry_run" if dry_run else "done", "counts": counts}


async def health_state(db: AsyncSession, *, now: Optional[datetime] = None) -> str:
    """Sonda ``/api/health``: disabled poza PROD, healthy po udanym przebiegu."""

    config = load_config()
    if not config.enabled or config.mode != "prod":
        return "disabled"
    last = await db.scalar(
        select(HrJobRun)
        .where(HrJobRun.kind == JOB_KIND)
        .order_by(HrJobRun.claimed_at.desc())
        .limit(1)
    )
    if last is None:
        return "degraded"
    moment = now or datetime.now(timezone.utc)
    fresh = last.claimed_at is not None and moment - last.claimed_at < HEALTHY_WITHIN
    return "healthy" if fresh and last.status != "failed" else "degraded"


__all__ = [
    "Decision",
    "Ebi24Paid",
    "Existing",
    "JOB_KIND",
    "REVOKED",
    "SUPERSEDED",
    "apply",
    "criteria",
    "decide",
    "fetch_headers",
    "health_state",
    "read_header",
    "recorded_in_nexus",
    "run_once",
]
