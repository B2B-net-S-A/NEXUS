"""Obrót sprzed KSeF do rabatu od obrotu: faktury z archiwum eBI24 (24.11.2026).

Faktur sprzed KSeF (u Nordei styczeń–marzec 2026) nie ma w
``client_sales_invoices``. Są w archiwum eBI24: wiersz w
``finance_archive_documents``, pozycje w pliku JSON faktury. Do obrotu progu
idzie dokument, który:

* jest fakturą sprzedaży wystawioną w eBI24 (``INVOICE_SCHEMAS``, plik JSON);
  PDF wgrany do eBI24 nie ma pozycji, więc obrotu przed rabatem z niego się
  nie odtworzy, a proforma, zamówienie i nota nie są obrotem;
* nie ma numeru KSeF (te z numerem są już w fakturach z KSeF) ani numeru
  faktury, którą klient ma w KSeF (eksport archiwum bywa starszy niż wysyłka);
  ten sam numer w archiwum drugi raz to duplikat faktury, liczy się raz;
* ma nabywcę, którego numer prowadzi do klienta tak samo jak przy fakturach
  z KSeF (``clients.nip_registry``); oddział albo spółka z grupy z innym
  numerem się nie liczy (decyzja Artura 24.11.2026);
* jest za miesiąc roku według daty sprzedaży (``transactionDate``), a bez niej
  według daty wystawienia.

Plik czytamy raz na proces, bo plik archiwum się nie zmienia (klucz: ścieżka
i suma SHA-256 z bazy), a kilkaset plików przy każdej karcie faktury trwałoby za
długo. Plik nieczytelny albo bez kwot nie wchodzi do obrotu, a karta pokazuje,
ile takich jest (``unreadable``), żeby zaniżony obrót nie wyglądał na pełny.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client_sales_invoice import ClientSalesInvoice
from app.models.finance_archive import FinanceArchiveDocument
from app.services.client_invoicing import clients
from app.services.finance_ledger import archive
from app.services.finance_ledger.archive import _grosze
from app.services.order_client_identity import normalize_buyer_number

INVOICE_SCHEMAS = ("INCOME_INVOICE", "EUROPEAN_INCOME_INVOICE")
CORRECTION_TYPE = "CORRECTIVE_INVOICE"
#: Ile plików trzymamy w pamięci procesu (rok Nordei to ok. 2,7 tys. faktur).
CACHE_MAX = 50_000


@dataclass(frozen=True)
class EbiInvoice:
    """Netto i pozycje faktury z pliku eBI24 w kształcie ``client_sales_invoices``."""

    net_amount: Decimal
    items: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class ArchiveInvoice:
    currency: str
    net_amount: Decimal
    items: tuple[dict[str, Any], ...]
    sale_date: date


def _items(raw: Any, *, before: bool = False) -> list[dict[str, Any]]:
    out = []
    for item in raw if isinstance(raw, list) else ():
        if not isinstance(item, dict):
            continue
        price, net = _grosze(item.get("unitNettPrice")), _grosze(item.get("nettAmount"))
        row: dict[str, Any] = {
            "name": str(item.get("name") or ""),
            "quantity": str(item.get("amountOfUnits") or ""),
            "unit_price": None if price is None else format(price, "f"),
            "net": None if net is None else format(net, "f"),
        }
        if before:
            row["before_correction"] = True
        out.append(row)
    return out


def _corrected(raw: Any) -> Optional[dict[str, Any]]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return None
    return raw if isinstance(raw, dict) else None


def ebi_invoice(data: Any) -> Optional[EbiInvoice]:
    """Faktura z pliku eBI24 (kwoty w groszach); korekta = stan po minus stan przed.

    Cena jednostkowa eBI24 jest przed rabatem, netto pozycji po nim — tak jak
    ``P_9A`` i ``P_11`` w KSeF, więc obrót przed rabatem liczy ten sam
    ``rebate.service_base``. Stan przed korektą to pozycje z treści faktury
    korygowanej z ``before_correction``; bez tej treści zostaje sama różnica netto.
    """

    if not isinstance(data, dict):
        return None
    net = _grosze(data.get("nettAmount"))
    if net is None:
        return None
    items = _items(data.get("items"))
    if data.get("invoiceType") != CORRECTION_TYPE:
        return EbiInvoice(net, tuple(items))
    before_net = _grosze(data.get("correctedInvoiceNettAmount"))
    if before_net is None:
        return None
    before = _corrected(data.get("correctedInvoiceContent"))
    if before is None:
        return EbiInvoice(net - before_net, ())
    return EbiInvoice(
        net - before_net, tuple(items + _items(before.get("items"), before=True))
    )


_PARSED: dict[tuple[str, str], EbiInvoice] = {}


def _load(files: list[tuple[str, str]]) -> list[Optional[EbiInvoice]]:
    out: list[Optional[EbiInvoice]] = []
    for key in files:
        parsed = _PARSED.get(key)
        if parsed is None:
            try:
                parsed = ebi_invoice(json.loads(archive.read_path(key[0])))
            except (OSError, ValueError, ArithmeticError):
                parsed = None
            if parsed is not None:
                if len(_PARSED) >= CACHE_MAX:
                    _PARSED.clear()
                _PARSED[key] = parsed
        out.append(parsed)
    return out


def _day(raw: Optional[str]) -> Optional[date]:
    try:
        return date.fromisoformat(raw[:10]) if raw else None
    except ValueError:
        return None


async def pre_ksef_invoices(
    db: AsyncSession, *, client_id: int, year: int
) -> tuple[list[ArchiveInvoice], int]:
    """Faktury klienta za rok z archiwum eBI24 spoza KSeF i liczba nieczytelnych plików."""

    registry = await clients.nip_registry(db)
    numbers = {
        number for number, owner in registry.by_nip.items() if owner == client_id
    }
    if not numbers:
        return [], 0
    doc = FinanceArchiveDocument
    partner = func.regexp_replace(func.upper(doc.partner_id), "[^A-Z0-9]", "", "g")
    sale = func.coalesce(
        func.substr(doc.meta["transactionDate"].astext, 1, 10),
        func.to_char(doc.issue_date, "YYYY-MM-DD"),
    )
    rows = (
        await db.execute(
            select(
                doc.partner_id,
                doc.invoice_number,
                doc.currency,
                doc.file_path,
                doc.file_sha256,
                sale.label("sale"),
            )
            .where(
                doc.kind == "sale",
                doc.file_type == "ebi",
                doc.schema_name.in_(INVOICE_SCHEMAS),
                doc.ksef_number.is_(None),
                partner.in_(numbers | {f"PL{n}" for n in numbers if n.isdigit()}),
                sale >= f"{year}-01-01",
                sale < f"{year + 1}-01-01",
            )
            .order_by(doc.issue_date, doc.id)
        )
    ).all()
    seen = set(
        await db.scalars(
            select(func.lower(ClientSalesInvoice.invoice_number)).where(
                ClientSalesInvoice.client_id == client_id
            )
        )
    )
    docs = []
    for row in rows:
        number = (row.invoice_number or "").lower()
        if normalize_buyer_number(row.partner_id or "") not in numbers or (
            number in seen
        ):
            continue
        # Ten sam numer drugi raz to duplikat faktury z eBI24 (ta sama kwota,
        # wystawiony później), a nie nowa sprzedaż.
        if number:
            seen.add(number)
        docs.append(row)
    if not docs:
        return [], 0
    parsed = await asyncio.to_thread(
        _load, [(row.file_path, row.file_sha256) for row in docs]
    )
    invoices, unreadable = [], 0
    for row, invoice in zip(docs, parsed):
        day = _day(row.sale)
        if invoice is None or day is None:
            unreadable += 1
            continue
        invoices.append(
            ArchiveInvoice(
                (row.currency or "PLN").upper(),
                invoice.net_amount,
                invoice.items,
                day,
            )
        )
    return invoices, unreadable


__all__ = [
    "ArchiveInvoice",
    "EbiInvoice",
    "ebi_invoice",
    "pre_ksef_invoices",
]
