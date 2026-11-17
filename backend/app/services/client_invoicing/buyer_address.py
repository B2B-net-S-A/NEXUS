"""Adres nabywcy faktury sprzedażowej (``Podmiot2/Adres``, 0730).

Adres trafia do kartoteki kontrahentów Symfonii (lista „Czeka na Symfonię”,
``finance_ledger.symfonia_partners``): bez niego księgowa szuka go ręcznie dla
każdego nabywcy. XML-a faktury nie trzymamy (tylko ``xml_sha256``), więc nowe
faktury zapisują adres przy pobraniu (``sync.store_invoice``), a faktury sprzed
0730 doczytuje pętla KSeF:

1. z XML-a, który już jest w bazie — faktura wystawiona w NEXUSIE
   (``client_issued_invoices.xml``) albo e-faktura Peppol
   (``client_sales_invoice_einvoices.fa_xml``), bez pobrania z KSeF,
2. z KSeF, z resztki budżetu pobrań przebiegu (po bieżących fakturach,
   e-fakturach i zaległych oknach).

Plik przyjmujemy tylko ze skrótem równym ``xml_sha256`` — inny plik pod tym
numerem to nie ta faktura. ``buyer_address_read_at`` oznacza fakturę
przeczytaną także wtedy, gdy adresu w niej nie było albo pliku nie da się
odczytać, żeby jedna faktura nie zjadała budżetu co godzinę.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client_einvoice import ClientSalesInvoiceEinvoice
from app.models.client_issued_invoice import ClientIssuedInvoice
from app.models.client_sales_invoice import ClientSalesInvoice
from app.services.client_invoicing import fa_sales
from app.services.hr.ksef import fa
from app.services.hr.ksef.client import KsefApiError

logger = logging.getLogger(__name__)

#: Faktur z XML-em w bazie na jeden przebieg (bez pobrań, sam odczyt).
LOCAL_BATCH = 200
#: Kategorie błędów KSeF, przy których faktura czeka na następny przebieg.
_RETRY_LATER = frozenset({"not_ready", "unavailable"})


def columns(sales: Optional[fa_sales.SalesInvoice], now: datetime) -> dict[str, Any]:
    """Kolumny adresu dla ``ClientSalesInvoice`` (``None`` = pliku nie da się odczytać)."""

    address = sales.buyer_address if sales is not None else None
    return {
        "buyer_country": address.country if address else None,
        "buyer_address_line1": address.line1 if address else None,
        "buyer_address_line2": address.line2 if address else None,
        "buyer_address_read_at": now,
    }


def _apply(invoice: ClientSalesInvoice, xml: Optional[bytes], now: datetime) -> bool:
    """Adres z pliku, gdy skrót się zgadza; ``True`` = adres zapisany."""

    sales = None
    if xml is not None and hashlib.sha256(xml).hexdigest() == invoice.xml_sha256:
        try:
            sales = fa_sales.parse_sales_invoice(xml)
        except fa.InvoiceParseError as exc:
            logger.warning(
                "[client-invoicing] adres nabywcy faktury %s: %s", invoice.id, exc.code
            )
    elif xml is not None:
        logger.warning(
            "[client-invoicing] adres nabywcy faktury %s: inny plik niż przy pobraniu",
            invoice.id,
        )
    for name, value in columns(sales, now).items():
        setattr(invoice, name, value)
    return invoice.buyer_address_line1 is not None or (
        invoice.buyer_address_line2 is not None
    )


async def backfill_local(db: AsyncSession, now: datetime) -> int:
    """Faktury sprzed 0730, których XML jest już w bazie; zwraca liczbę adresów."""

    rows = (
        await db.execute(
            select(
                ClientSalesInvoice,
                ClientIssuedInvoice.xml,
                ClientSalesInvoiceEinvoice.fa_xml,
            )
            .outerjoin(
                ClientIssuedInvoice,
                ClientIssuedInvoice.ksef_number == ClientSalesInvoice.ksef_number,
            )
            .outerjoin(
                ClientSalesInvoiceEinvoice,
                ClientSalesInvoiceEinvoice.invoice_id == ClientSalesInvoice.id,
            )
            .where(
                ClientSalesInvoice.buyer_address_read_at.is_(None),
                or_(
                    ClientIssuedInvoice.xml.is_not(None),
                    ClientSalesInvoiceEinvoice.fa_xml.is_not(None),
                ),
            )
            .order_by(ClientSalesInvoice.issue_date.desc(), ClientSalesInvoice.id)
            .limit(LOCAL_BATCH)
        )
    ).all()
    filled = 0
    for invoice, issued_xml, einvoice_xml in rows:
        if invoice.buyer_address_read_at is not None:
            continue  # ten sam wiersz z dwóch źródeł
        candidates = [
            text.encode("utf-8") for text in (issued_xml, einvoice_xml) if text
        ]
        matching = next(
            (
                xml
                for xml in candidates
                if hashlib.sha256(xml).hexdigest() == invoice.xml_sha256
            ),
            None,
        )
        if matching is None:
            continue  # plik w bazie to nie ta wersja — doczyta KSeF
        filled += _apply(invoice, matching, now)
    await db.flush()
    return filled


async def backfill_ksef(
    db: AsyncSession, source: Any, budget: int, now: datetime
) -> tuple[int, int]:
    """Do ``budget`` pobrań z KSeF; zwraca (liczba pobrań, liczba adresów).

    Blokada 429 przerywa (wyjątek idzie do pętli, która zapisuje blokadę)."""

    if budget <= 0:
        return 0, 0
    invoices = list(
        await db.scalars(
            select(ClientSalesInvoice)
            .where(ClientSalesInvoice.buyer_address_read_at.is_(None))
            .order_by(ClientSalesInvoice.issue_date.desc(), ClientSalesInvoice.id)
            .limit(budget)
        )
    )
    attempted = filled = 0
    for invoice in invoices:
        attempted += 1
        try:
            xml = await source.download_invoice(invoice.ksef_number)
        except KsefApiError as exc:
            if exc.category == "rate_limited":
                await db.flush()
                raise
            if exc.category in _RETRY_LATER:
                break
            logger.warning(
                "[client-invoicing] adres nabywcy faktury %s: ksef:%s",
                invoice.id,
                exc.category,
            )
            _apply(invoice, None, now)
            continue
        filled += _apply(invoice, xml, now)
    await db.flush()
    return attempted, filled


__all__ = ["backfill_ksef", "backfill_local", "columns"]
