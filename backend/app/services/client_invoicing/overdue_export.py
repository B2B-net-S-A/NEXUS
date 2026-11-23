"""Należności po terminie na zamknięcie miesiąca — plik dla księgowej (CSV, XLSX).

Główna księgowa co miesiąc ok. 20. dnia składała tę listę ręcznie z rozrachunków
Symfonii i wysyłała osobie, która fakturuje (przegląd skrzynek 23.11.2026).
NEXUS daje ją na ostatni dzień miesiąca (albo na dziś, gdy miesiąc trwa):
faktury i wpłaty po tym dniu się nie liczą (``receivables.as_of``).

Dwa rodzaje wierszy, bo „po terminie” bez dowodu to brak danych, nie zaległość
(``faktury-do-klientow-z-ksef.md``): najpierw faktury po terminie z dowodem
z wyciągów (z dniami i poziomem monitu), potem faktury z terminem za sobą bez
danych o zapłacie — z powodem, bez dni. Reguła:
``docs/claude/zamowienia/monity-i-naleznosci-po-terminie.md``.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Sequence
from datetime import date
from typing import Any, Optional

from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.export_safety import safe_row
from app.models.client import Client
from app.models.client_sales_invoice import ClientSalesInvoice
from app.services.client_invoicing import (
    clients,
    ledger,
    payment_proof,
    payment_reminders,
    receivables,
)
from app.services.client_invoicing.ledger import ZERO
from app.services.client_invoicing.views import Late, late_chains
from app.services.order_client_identity import normalize_buyer_number

COLUMNS: tuple[str, ...] = (
    "Klient",
    "NIP / VAT UE",
    "Faktura",
    "Numer KSeF",
    "Data wystawienia",
    "Termin płatności",
    "Waluta",
    "Brutto",
    "Zapłacono",
    "Do zapłaty",
    "VAT w PLN do zapłaty",
    "Dni po terminie",
    "Poziom monitu",
    "Stan",
    "Ostatni monit",
)
_NUMERIC = {7, 8, 9, 10, 11}


def _day(value: Optional[date]) -> str:
    return value.strftime("%d.%m.%Y") if value else ""


def state_text(item: Late) -> str:
    verdict = item.verdict
    if verdict.overdue_days > 0:
        base = (
            "VAT w PLN nieopłacony (netto zapłacone)"
            if item.vat is not None
            else "po terminie"
            if item.chain.paid <= ZERO
            else "po terminie, zapłacono część"
        )
        return f"{base}; wpłaty do {_day(verdict.until)}" if verdict.until else base
    label = payment_proof.REASONS.get(verdict.reason or "statements", "")
    account = f" (rachunek …{verdict.account})" if verdict.account else ""
    return f"brak danych o zapłacie: {label}{account}"


def table(
    items: Sequence[Late],
    *,
    names: dict[int, str],
    numbers: dict[int, str],
    last: dict[int, Any],
) -> list[list[Any]]:
    proven = sorted(
        (i for i in items if i.proven),
        key=lambda i: (-i.verdict.overdue_days, i.chain.head.id),
    )
    unknown = sorted(
        (i for i in items if i.verdict.unknown),
        key=lambda i: (i.chain.head.due_date or date.min, i.chain.head.id),
    )
    out: list[list[Any]] = []
    for item in [*proven, *unknown]:
        chain = item.chain
        head = chain.head
        client = head.client_id
        sent = last.get(client) if client else None
        out.append(
            [
                names.get(client, "") if client else head.buyer_name or "",
                numbers.get(client, "")
                if client
                else normalize_buyer_number(
                    head.buyer_nip or head.buyer_foreign_id or ""
                ),
                head.invoice_number,
                head.ksef_number or "",
                _day(head.issue_date),
                _day(head.due_date),
                head.currency,
                str(chain.gross),
                str(chain.paid),
                str(chain.to_pay),
                str(item.vat_pln) if item.vat_pln is not None else "",
                str(item.verdict.overdue_days) if item.proven else "",
                receivables.LEVEL_LABELS.get(
                    receivables.escalation(item.verdict.overdue_days) or "", ""
                ),
                state_text(item),
                _day(sent[0].date()) if sent else "",
            ]
        )
    return out


async def month_close(db: AsyncSession, *, day: date) -> list[list[Any]]:
    """Wiersze pliku na koniec ``day``: z dowodem, potem bez danych o zapłacie."""

    invoices = list(
        await db.scalars(
            select(ClientSalesInvoice).where(
                ClientSalesInvoice.paid_in_invoice_on.is_(None),
                ClientSalesInvoice.issue_date <= day,
            )
        )
    )
    chains = [
        current
        for chain in await ledger.build_chains(db, invoices)
        if (current := receivables.as_of(chain, day)) is not None
    ]
    proof = await payment_proof.load(db)
    items = await late_chains(db, chains, day=day, proof=proof)
    ids = {i.chain.head.client_id for i in items if i.chain.head.client_id}
    names = await clients.names(db, ids)
    numbers: dict[int, str] = {}
    if ids:
        for client_id, raw in await db.execute(
            select(Client.id, Client.nip).where(Client.id.in_(sorted(ids)))
        ):
            numbers[int(client_id)] = normalize_buyer_number(raw or "")
    last = await payment_reminders.last_sent(db, ids)
    return table(items, names=names, numbers=numbers, last=last)


def _decimal_text(value: Any) -> Any:
    if (
        isinstance(value, str)
        and value.replace(".", "", 1).replace("-", "", 1).isdigit()
    ):
        return value.replace(".", ",")
    return value


def to_csv(lines: Sequence[Sequence[Any]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
    writer.writerow(COLUMNS)
    for line in lines:
        writer.writerow(safe_row([_decimal_text(value) for value in line]))
    return ("﻿" + buffer.getvalue()).encode("utf-8")


def to_xlsx(lines: Sequence[Sequence[Any]], *, title: str) -> bytes:
    book = Workbook()
    sheet = book.active
    sheet.title = title[:31]
    sheet.append(list(COLUMNS))
    for line in lines:
        values = safe_row(line)
        for index in _NUMERIC:
            raw = line[index]
            if isinstance(raw, str) and raw:
                try:
                    values[index] = float(raw)
                except ValueError:
                    pass
        sheet.append(values)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


__all__ = ["COLUMNS", "month_close", "state_text", "table", "to_csv", "to_xlsx"]
