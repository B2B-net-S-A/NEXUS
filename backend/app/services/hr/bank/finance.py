"""Ekran „Dla Finansów”: zatwierdzone do zapłaty, eksport CSV i lista NIP-ów.

Przelewy robią Finanse jak dziś (decyzja 17.10.2026): faktury B2B w eBI24 albo
w banku, wynagrodzenia zlecenia i UoP z Symfonii. NEXUS mówi, CO jest do
zapłaty (rozliczenia ``approved`` z ``settlements.payable``), ile, do kiedy
i z jakim tytułem (numer KSeF), a „opłacono” przychodzi z wyciągu.

* B2B — kwota do zapłaty to brutto faktury (pierwotna + korekty, jak netto
  w ``settlements``), tytuł z numerem KSeF,
* zlecenie i UoP — kwotę na rękę liczy Symfonia (NEXUS nie liczy podatków
  ani składek, R4): lista pokazuje brutto i „netto z programu płacowego”.

Rachunek: tylko ostatnie 4 cyfry i to, czy pochodzi z białej listy — pełnego
numeru nie ma ani na ekranie, ani w CSV (pełny trafia wyłącznie do pliku
paczki przelewów, gdy Płace ją włączą).

Lista NIP-ów (CSV) służy regule w eBI24: faktury od tych NIP-ów rozlicza
NEXUS. Bierze osoby z NIP-em w danych do rozliczeń, które pracują albo
odeszły w ostatnich ``NIP_LIST_GRACE_DAYS`` dniach (ostatnia faktura
przychodzi po odejściu).
"""

from __future__ import annotations

import csv
import io
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.export_safety import safe_row
from app.models.hr_payroll import PayrollPeriod
from app.models.hr_profile import EmployeeProfile
from app.models.hr_settlement import (
    EmployeeBillingDetails,
    PayrollInvoice,
    PayrollPayment,
    PayrollSettlement,
)
from app.models.user import User
from app.services.hr import settlements as settlement_service
from app.services.hr.bank.elixir import amount_text
from app.services.hr.bank.titles import InvoiceRef, transfer_title
from app.services.hr.employment_terms import FORM_SHORT_LABELS
from app.services.hr.payroll_report import money
from app.services.hr_foundation_schema import EmploymentStatus

NIP_LIST_GRACE_DAYS = 92
B2B = "b2b"


@dataclass(frozen=True)
class PayableInvoice:
    id: int
    invoice_number: str
    ksef_number: Optional[str]
    gross_amount: Decimal
    kind: str


@dataclass(frozen=True)
class PayableRow:
    settlement_id: int
    user_id: int
    name: str
    employment_type: str
    year: int
    month: int
    currency: str
    expected_amount: Decimal
    amount_basis: str
    #: Brutto faktur (B2B); ``None`` = kwotę na rękę liczy program płacowy.
    amount_to_pay: Optional[Decimal]
    due_on: Optional[date]
    approved_at: Optional[datetime]
    approved_by_name: Optional[str]
    title: str
    nip: Optional[str]
    registry_name: Optional[str]
    account_last4: Optional[str]
    account_source: Optional[str]
    account_checked_at: Optional[datetime]
    #: Rachunek spoza białej listy uznany przez dwie osoby (R10).
    white_list_override: bool
    batch_key: Optional[str]
    invoices: tuple[PayableInvoice, ...] = field(default_factory=tuple)


async def period_id_of(db: AsyncSession, year: int, month: int) -> Optional[int]:
    return await db.scalar(
        select(PayrollPeriod.id).where(
            PayrollPeriod.year == year, PayrollPeriod.month == month
        )
    )


async def matched_invoices(
    db: AsyncSession, settlement_ids: Sequence[int]
) -> dict[int, list[PayableInvoice]]:
    if not settlement_ids:
        return {}
    rows = await db.scalars(
        select(PayrollInvoice)
        .where(
            PayrollInvoice.settlement_id.in_(settlement_ids),
            PayrollInvoice.match_status == "matched",
        )
        .order_by(PayrollInvoice.issue_date, PayrollInvoice.id)
    )
    found: dict[int, list[PayableInvoice]] = defaultdict(list)
    for invoice in rows:
        found[int(invoice.settlement_id)].append(
            PayableInvoice(
                id=invoice.id,
                invoice_number=invoice.invoice_number,
                ksef_number=invoice.ksef_number,
                gross_amount=Decimal(invoice.gross_amount),
                kind=invoice.invoice_kind,
            )
        )
    return found


def invoice_gross(invoices: Sequence[PayableInvoice]) -> Optional[Decimal]:
    """Brutto do zapłaty: faktura pierwotna + korekty (korekta niesie różnicę)."""

    if not invoices:
        return None
    return money(sum((invoice.gross_amount for invoice in invoices), Decimal("0")))


async def active_batches(
    db: AsyncSession, settlement_ids: Sequence[int]
) -> dict[int, str]:
    """Rozliczenie → klucz paczki, w której czeka na wysłanie (bez anulowanych)."""

    if not settlement_ids:
        return {}
    rows = await db.execute(
        select(PayrollPayment.settlement_id, PayrollPayment.batch_key).where(
            PayrollPayment.kind == "transfer_batch",
            PayrollPayment.match_status == "matched",
            PayrollPayment.settlement_id.in_(settlement_ids),
        )
    )
    return {int(sid): str(key) for sid, key in rows.all()}


async def describe(
    db: AsyncSession, settlements: Sequence[PayrollSettlement]
) -> list[PayableRow]:
    """Wiersze ekranu dla podanych rozliczeń (jedno zapytanie na rodzaj danych)."""

    if not settlements:
        return []
    ids = [s.id for s in settlements]
    user_ids = {s.user_id for s in settlements} | {
        s.approved_by for s in settlements if s.approved_by
    }
    names = {
        int(uid): str(name)
        for uid, name in (
            await db.execute(select(User.id, User.name).where(User.id.in_(user_ids)))
        ).all()
    }
    periods = {
        int(pid): (int(year), int(month))
        for pid, year, month in (
            await db.execute(
                select(PayrollPeriod.id, PayrollPeriod.year, PayrollPeriod.month).where(
                    PayrollPeriod.id.in_({s.period_id for s in settlements})
                )
            )
        ).all()
    }
    billing = {
        details.user_id: details
        for details in await db.scalars(
            select(EmployeeBillingDetails).where(
                EmployeeBillingDetails.user_id.in_({s.user_id for s in settlements})
            )
        )
    }
    invoices = await matched_invoices(db, ids)
    batches = await active_batches(db, ids)
    rows: list[PayableRow] = []
    for settlement in settlements:
        year, month = periods.get(settlement.period_id, (0, 0))
        own = invoices.get(settlement.id, [])
        details = billing.get(settlement.user_id)
        refs = [InvoiceRef(i.invoice_number, i.ksef_number) for i in own]
        rows.append(
            PayableRow(
                settlement_id=settlement.id,
                user_id=settlement.user_id,
                name=names.get(settlement.user_id, f"Osoba {settlement.user_id}"),
                employment_type=settlement.employment_type,
                year=year,
                month=month,
                currency=settlement.currency,
                expected_amount=Decimal(settlement.expected_amount),
                amount_basis=settlement.amount_basis,
                amount_to_pay=invoice_gross(own)
                if settlement.employment_type == B2B
                else None,
                due_on=settlement.due_on,
                approved_at=settlement.approved_at,
                approved_by_name=names.get(settlement.approved_by)
                if settlement.approved_by
                else None,
                title=transfer_title(settlement.employment_type, year, month, refs),
                nip=details.nip if details else None,
                registry_name=details.registry_name if details else None,
                account_last4=details.account_last4 if details else None,
                account_source=details.account_source if details else None,
                account_checked_at=details.account_checked_at if details else None,
                white_list_override=settlement.override_kind == "white_list"
                and settlement.override_confirmed_by is not None,
                batch_key=batches.get(settlement.id),
                invoices=tuple(own),
            )
        )
    return rows


async def payable_rows(
    db: AsyncSession, *, year: Optional[int] = None, month: Optional[int] = None
) -> list[PayableRow]:
    period_id: Optional[int] = None
    if year is not None and month is not None:
        period_id = await period_id_of(db, year, month)
        if period_id is None:
            return []
    return await describe(db, await settlement_service.payable(db, period_id=period_id))


def _money(value: Optional[Decimal]) -> str:
    return "" if value is None else amount_text(value)


def account_label(row: PayableRow) -> str:
    if not row.account_last4:
        return "brak rachunku w danych do rozliczeń"
    source = {
        "white_list": "z białej listy VAT",
        "manual": "wpisany przez Kadry",
    }.get(row.account_source or "", "")
    if row.white_list_override:
        source = "spoza białej listy — uznany przez dwie osoby"
    return f"•• {row.account_last4}" + (f" ({source})" if source else "")


FINANCE_COLUMNS = (
    "Osoba",
    "Forma",
    "Okres",
    "Dokument",
    "Numer KSeF",
    "Kwota do zapłaty",
    "Kwota z NEXUSA",
    "Podstawa",
    "Waluta",
    "Termin",
    "Rachunek",
    "Tytuł przelewu",
    "Zatwierdził",
)


def finance_csv(rows: Sequence[PayableRow]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
    writer.writerow(FINANCE_COLUMNS)
    for row in rows:
        writer.writerow(
            safe_row(
                [
                    row.name,
                    FORM_SHORT_LABELS.get(row.employment_type, row.employment_type),
                    f"{row.month:02d}/{row.year}",
                    ", ".join(i.invoice_number for i in row.invoices)
                    or (
                        "potwierdzenie godzin"
                        if row.employment_type == "zlecenie"
                        else "lista płac"
                    ),
                    ", ".join(i.ksef_number for i in row.invoices if i.ksef_number),
                    _money(row.amount_to_pay)
                    if row.amount_to_pay is not None
                    else "netto z programu płacowego",
                    _money(row.expected_amount),
                    "netto" if row.amount_basis == "net" else "brutto",
                    row.currency,
                    row.due_on.isoformat() if row.due_on else "",
                    account_label(row),
                    row.title,
                    row.approved_by_name or "",
                ]
            )
        )
    return ("﻿" + buffer.getvalue()).encode("utf-8")


@dataclass(frozen=True)
class NipRow:
    nip: str
    registry_name: Optional[str]
    name: str
    employment_type: Optional[str]


async def nip_rows(db: AsyncSession, *, today: date) -> list[NipRow]:
    cutoff = today - timedelta(days=NIP_LIST_GRACE_DAYS)
    rows = await db.execute(
        select(
            EmployeeBillingDetails.nip,
            EmployeeBillingDetails.registry_name,
            User.name,
            EmployeeProfile.employment_type,
            EmployeeProfile.employment_status,
            EmployeeProfile.last_working_day,
        )
        .join(User, User.id == EmployeeBillingDetails.user_id)
        .join(
            EmployeeProfile, EmployeeProfile.user_id == EmployeeBillingDetails.user_id
        )
        .where(EmployeeBillingDetails.nip.is_not(None))
        .order_by(User.name, EmployeeBillingDetails.nip)
    )
    found: list[NipRow] = []
    for nip, registry, name, form, status, last_day in rows.all():
        if status == EmploymentStatus.exited and (
            last_day is None or last_day < cutoff
        ):
            continue
        found.append(
            NipRow(nip=nip, registry_name=registry, name=name, employment_type=form)
        )
    return found


NIP_COLUMNS = ("NIP", "Nazwa z wykazu VAT", "Osoba", "Forma")


def nip_csv(rows: Sequence[NipRow]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
    writer.writerow(NIP_COLUMNS)
    for row in rows:
        writer.writerow(
            safe_row(
                [
                    row.nip,
                    row.registry_name or "",
                    row.name,
                    FORM_SHORT_LABELS.get(row.employment_type or "", ""),
                ]
            )
        )
    return ("﻿" + buffer.getvalue()).encode("utf-8")


__all__ = [
    "FINANCE_COLUMNS",
    "NIP_COLUMNS",
    "NipRow",
    "PayableInvoice",
    "PayableRow",
    "account_label",
    "describe",
    "finance_csv",
    "invoice_gross",
    "matched_invoices",
    "nip_csv",
    "nip_rows",
    "payable_rows",
    "period_id_of",
]
