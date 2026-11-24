"""„Podgląd PDF” faktury z kolejki kosztów (karta i kolejka Finansów).

Faktura z KSeF → wizualizacja pliku XML (``hr/ksef/fa_visual.py``). XML-a
kosztów pętla KSeF nie pobiera (budżet pobrań zostaje dla Płac i kontraktorów),
więc podgląd pobiera go **na żądanie** przy pierwszym otwarciu i zapamiętuje
na wolumenie (``hr/ksef/xml_cache.py``) — kolejne otwarcia nie pytają KSeF.
Pomiar z 22.11.2026: ok. 600–670 faktur kosztowych miesięcznie (ok. 20
dziennie) przy limicie 64 pobrań na godzinę, z którego pętle zużywają
kilkadziesiąt; podgląd bierze najwyżej ``ON_DEMAND_PER_HOUR`` pobrań na
godzinę w procesie i czeka, gdy pętla zapisała blokadę 429.

Plik z KSeF musi mieć tego samego sprzedawcę co wpis kolejki (a przy
fakturze Płac — ten sam skrót SHA-256 co przy pobraniu); inaczej podglądu nie
ma i plik nie trafia do pamięci. Faktura spoza KSeF (PDF wgrany do Płac albo
do zgody) → ten PDF bez zmian.

Bramki jak karta: ta sama trasa sekcji i modułu, a faktury osób zespołu widzą
tylko Płace i admin (D2, ``costs._payroll_scope``) — dla reszty 404.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.process_role import web_process_count
from app.core.scheduling import DEFAULT_TZ
from app.models.client_settlement import ClientContractorInvoice
from app.models.finance_ledger import FinanceCostEntry
from app.models.hr_approval import ApprovalDocument
from app.models.hr_settlement import PayrollInvoice
from app.services.finance_ledger.costs import LedgerError, _payroll_scope
from app.services.hr.ksef import fa, fa_visual, pdf_store, xml_cache
from app.services.hr.ksef.client import KsefApiError
from app.services.hr.ksef.environment import load_config
from app.services.hr.ksef.source import InvoiceSource, open_source

logger = logging.getLogger(__name__)

#: Pobrania na żądanie na godzinę w jednym procesie — zapas limitu 64/h dla pętli.
ON_DEMAND_PER_HOUR = 20
_HOUR = 3600.0
_downloads: deque[float] = deque()

SOURCES: dict[str, Any] = {
    "payroll_invoice": PayrollInvoice,
    "contractor_invoice": ClientContractorInvoice,
    "approval_document": ApprovalDocument,
}
NOT_FOUND = "Nie ma takiej faktury w kolejce."
NO_PDF = "Ta faktura nie ma pliku PDF ani numeru KSeF — podglądu nie ma z czego zrobić."
KSEF_OFF = (
    "Pobieranie z KSeF jest wyłączone — podglądu tej faktury nie da się przygotować."
)
BUSY = "Podgląd pobrał w tej godzinie dużo faktur z KSeF — spróbuj za kilka minut."
OTHER_SELLER = (
    "Plik z KSeF ma innego sprzedawcę niż faktura w kolejce — podglądu nie pokazujemy."
)
OTHER_FILE = "Plik z KSeF różni się od pobranego wcześniej przez Płace — podglądu nie pokazujemy."
KSEF_ERRORS = {
    "not_ready": (
        "Faktura nie jest jeszcze gotowa do pobrania z KSeF — spróbuj za chwilę.",
        409,
    ),
    "not_found": ("Nie ma tej faktury w KSeF.", 404),
    "rate_limited": (
        "KSeF chwilowo ogranicza liczbę zapytań — spróbuj za kilka minut.",
        503,
    ),
}
KSEF_FAILED = ("KSeF nie odpowiada — spróbuj za chwilę.", 502)


@dataclass(frozen=True)
class Preview:
    filename: str
    media_type: str = "application/pdf"
    content: Optional[bytes] = None
    path: Optional[Path] = None


def _digits(value: Optional[str]) -> str:
    return "".join(ch for ch in (value or "") if ch.isdigit())


def _take_slot() -> bool:
    now = time.monotonic()
    while _downloads and now - _downloads[0] > _HOUR:
        _downloads.popleft()
    # Licznik w pamięci procesu: przy kilku procesach web każdy ma swoją część.
    if len(_downloads) >= -(-ON_DEMAND_PER_HOUR // web_process_count()):
        return False
    _downloads.append(now)
    return True


async def _download(
    db: AsyncSession, ksef_number: str, now: datetime, source: Optional[InvoiceSource]
) -> bytes:
    if source is None:
        config = load_config()
        if not config.enabled:
            raise LedgerError(KSEF_OFF, status=409)
        from app.services.hr.ksef import sync  # noqa: PLC0415 — sync ciągnie pół Płac

        until = await sync._blocked_any(db, now)
        if until is not None:
            local = until.astimezone(ZoneInfo(DEFAULT_TZ))
            raise LedgerError(
                "KSeF chwilowo ogranicza liczbę zapytań — podgląd będzie dostępny "
                f"po {local.strftime('%H:%M')}.",
                status=503,
            )
        source = open_source(config, now=lambda: now)
    if not _take_slot():
        raise LedgerError(BUSY, status=503)
    try:
        async with source:
            return await source.download_invoice(ksef_number)
    except KsefApiError as exc:
        logger.warning(
            "finance-preview: pobranie XML-a z KSeF nieudane (%s)", exc.category
        )
        message, status = KSEF_ERRORS.get(exc.category, KSEF_FAILED)
        raise LedgerError(message, status=status) from None


async def _ksef_preview(
    db: AsyncSession,
    *,
    ksef_number: str,
    seller_nip: Optional[str],
    xml_sha256: Optional[str],
    now: datetime,
    source: Optional[InvoiceSource],
) -> Preview:
    xml = xml_cache.load(ksef_number)
    cached = xml is not None
    if xml is None or (xml_sha256 and hashlib.sha256(xml).hexdigest() != xml_sha256):
        xml = await _download(db, ksef_number, now, source)
        cached = False
    if xml_sha256 and hashlib.sha256(xml).hexdigest() != xml_sha256:
        raise LedgerError(OTHER_FILE, status=409)
    try:
        visual = fa_visual.render_html(
            xml, ksef_number=ksef_number, environment=load_config().mode
        )
    except fa.InvoiceParseError as exc:
        raise LedgerError(
            f"Plik faktury z KSeF jest nieczytelny: {exc}.", status=422
        ) from None
    if seller_nip and _digits(visual.seller_nip) != _digits(seller_nip)[-10:]:
        raise LedgerError(OTHER_SELLER, status=409)
    if not cached:
        try:
            xml_cache.save(ksef_number, xml)
        except OSError:
            logger.exception("finance-preview: zapis XML-a w pamięci nieudany")
    content = await asyncio.to_thread(fa_visual.render_pdf, visual)
    return Preview(filename=fa_visual.filename(visual), content=content)


def _file_preview(entry: FinanceCostEntry, row: Any) -> Preview:
    from app.services.hr.approvals import store  # noqa: PLC0415

    try:
        if isinstance(row, PayrollInvoice) and row.pdf_storage_key:
            path = pdf_store.path_for(row.pdf_storage_key)
        elif (
            isinstance(row, ApprovalDocument)
            and row.file_path
            and (row.mime or "").lower() == "application/pdf"
        ):
            path = store.path_for(row.file_path)
        else:
            raise LedgerError(NO_PDF, status=404)
    except FileNotFoundError:
        raise LedgerError(
            "Pliku PDF tej faktury nie ma w magazynie.", status=404
        ) from None
    return Preview(filename=f"faktura-{entry.id}.pdf", path=path)


async def preview(
    db: AsyncSession,
    entry_id: int,
    *,
    payroll: bool,
    now: datetime,
    source: Optional[InvoiceSource] = None,
) -> Preview:
    entry = await db.scalar(
        select(FinanceCostEntry).where(
            FinanceCostEntry.id == entry_id, *_payroll_scope(payroll)
        )
    )
    if entry is None:
        raise LedgerError(NOT_FOUND, status=404)
    row = await db.get(SOURCES[entry.source_type], entry.source_id)
    if row is None:
        raise LedgerError(NOT_FOUND, status=404)
    ksef_number = getattr(row, "ksef_number", None)
    if ksef_number:
        return await _ksef_preview(
            db,
            ksef_number=ksef_number,
            seller_nip=entry.seller_nip or getattr(row, "seller_nip", None),
            xml_sha256=getattr(row, "xml_sha256", None),
            now=now,
            source=source,
        )
    return _file_preview(entry, row)


__all__ = ["ON_DEMAND_PER_HOUR", "Preview", "preview"]
