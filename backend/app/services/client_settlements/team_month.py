"""Biuro w „Przebiegu miesiąca” — nasi ludzie na B2B (decyzje Artura z 24.11.2026).

Klientem biura jest firma, więc faktury do klienta nie ma; ekran pokazuje te
same kroki co u kontraktorów: ewidencja czasu (``timesheets``), faktura osoby
z KSeF i zapłata. Fakturę bierzemy z Płac (``payroll_invoices``): czytnik KSeF
Płac zapisuje tylko faktury od NIP-ów z „Danych do rozliczeń”
(``employee_billing_details``), więc osoba bez NIP-u ma stan ``no_nip`` —
nie dopasowujemy faktur po nazwie sprzedawcy.

Finanse widzą same stany i daty. Kwot biura w odpowiedzi nie ma: zostają
w Płacach (decyzja Artura z 24.11.2026).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Iterable, Optional

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_date
from app.models.finance_ledger import FinanceCostEntry
from app.models.finance_payments import FinanceCostPayment
from app.models.hr_profile import EmployeeProfile
from app.models.hr_settlement import (
    EmployeeBillingDetails,
    PayrollInvoice,
    PayrollSettlement,
)
from app.models.hr_time import Timesheet
from app.models.user import User
from app.services.client_order_lines import month_bounds
from app.services.hr.program import program_enabled

TEAM_EMPLOYMENT = "b2b"
#: Źródło wpisu kosztu dla faktury osoby zespołu (``finance_ledger.costs``).
PAYROLL_SOURCE = "payroll_invoice"


def _iso(value: Optional[date | datetime]) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return business_date(value).isoformat()
    return value.isoformat()


def timesheet_state(sheet: Optional[Timesheet]) -> str:
    """Ewidencja za miesiąc: brak, szkic, zwrócona, złożona albo zatwierdzona."""

    if sheet is None:
        return "missing"
    if sheet.status == "draft":
        return "returned" if sheet.returned_at is not None else "draft"
    return sheet.status


def invoice_state(
    has_nip: bool,
    invoice: Optional[PayrollInvoice],
    settlement: Optional[PayrollSettlement],
) -> str:
    """Faktura osoby z KSeF: brak NIP-u, brak faktury, inna kwota albo jest."""

    if invoice is None:
        return "missing" if has_nip else "no_nip"
    if settlement is not None and settlement.status == "mismatch":
        return "differs"
    return "in_ksef"


def paid_on(
    settlement: Optional[PayrollSettlement], cost_paid: Optional[date]
) -> Optional[date]:
    """Zapłata z rozliczenia Płac, a bez niego z przelewu w Kosztach."""

    if settlement is not None and settlement.status == "paid" and settlement.paid_at:
        return business_date(settlement.paid_at)
    return cost_paid


def person_row(
    user_id: int,
    name: str,
    has_nip: bool,
    sheet: Optional[Timesheet],
    invoice: Optional[PayrollInvoice],
    settlement: Optional[PayrollSettlement],
    cost_paid: Optional[date],
) -> dict[str, Any]:
    paid = paid_on(settlement, cost_paid) if invoice is not None else None
    return {
        "user_id": user_id,
        "person": name,
        "timesheet": timesheet_state(sheet),
        "timesheet_on": _iso(sheet.approved_at) if sheet is not None else None,
        "invoice": invoice_state(has_nip, invoice, settlement),
        "invoice_on": _iso(invoice.issue_date) if invoice is not None else None,
        "paid": paid is not None,
        "paid_on": _iso(paid),
    }


def _for_month(invoice: PayrollInvoice, year: int, month: int) -> bool:
    if invoice.period_year and invoice.period_month:
        return (invoice.period_year, invoice.period_month) == (year, month)
    return invoice.sale_date is not None and (
        invoice.sale_date.year,
        invoice.sale_date.month,
    ) == (year, month)


def pick_invoice(
    invoices: Iterable[PayrollInvoice], year: int, month: int
) -> Optional[PayrollInvoice]:
    """Faktura pierwotna za miesiąc (bez korekt i bez odrzuconych przez Płace).

    Wygrywa faktura dopasowana przez Płace do rozliczenia, potem najwcześniejsza."""

    found = [
        i
        for i in invoices
        if i.invoice_kind != "correction"
        and i.match_status != "ignored"
        and _for_month(i, year, month)
    ]
    found.sort(key=lambda i: (i.match_status != "matched", i.issue_date, i.id))
    return found[0] if found else None


def in_team(
    *,
    profile_b2b: bool,
    active: bool,
    start: Optional[date],
    end: Optional[date],
    first: date,
    last: date,
    sheet_type: Optional[str],
    has_invoice: bool,
) -> bool:
    """Czy osoba należy do biura w miesiącu ``first``–``last``.

    Zatwierdzona ewidencja zapisuje formę współpracy z tego miesiąca (zlecenie
    w październiku, B2B od listopada) i rozstrzyga. Faktura za miesiąc też.
    Bez nich liczy się profil B2B i okno zatrudnienia z profilu: start
    (``work_start_date`` albo ``hired_on``) i ostatni dzień pracy
    (``last_working_day`` albo dzień ``exited_at``). Osoba, która odeszła 31.10,
    zostaje w październiku, choć konto wyłączono 1.11 i ewidencja to szkic;
    osoba zatrudniona 3.11 nie wisi w październiku jako brak. Konto wyłączone
    bez daty końca nie trafia do żadnego miesiąca — nie wiemy, kiedy pracowała."""

    if sheet_type:
        return sheet_type == TEAM_EMPLOYMENT
    if has_invoice:
        return True
    if not profile_b2b:
        return False
    if start is not None and start > last:
        return False
    if end is not None:
        return end >= first
    return active


async def team_month(db: AsyncSession, month: str) -> dict[str, Any]:
    """Biuro w miesiącu: osoba po osobie, bez kwot."""

    if not program_enabled():
        return {"month": month, "people": []}
    year, mon = (int(part) for part in month.split("-"))
    first, last = month_bounds(month)
    for_month = or_(
        and_(PayrollInvoice.period_year == year, PayrollInvoice.period_month == mon),
        and_(
            PayrollInvoice.period_year.is_(None),
            PayrollInvoice.sale_date.between(first, last),
        ),
    )
    # Wszystkie profile B2B (także konta wyłączone): okno zatrudnienia rozstrzyga w ``in_team``.
    profile_b2b = set(
        (
            await db.scalars(
                select(EmployeeProfile.user_id).where(
                    EmployeeProfile.employment_type == TEAM_EMPLOYMENT,
                    EmployeeProfile.employment_type_pending.is_(False),
                )
            )
        ).all()
    )
    with_sheet = set(
        (
            await db.scalars(
                select(Timesheet.user_id).where(
                    Timesheet.year == year, Timesheet.month == mon
                )
            )
        ).all()
    )
    with_invoice = set(
        (
            await db.scalars(
                select(PayrollInvoice.user_id).where(
                    PayrollInvoice.user_id.is_not(None),
                    PayrollInvoice.match_status != "ignored",
                    for_month,
                )
            )
        ).all()
    )
    ids = sorted(profile_b2b | with_sheet | with_invoice)
    if not ids:
        return {"month": month, "people": []}
    people = (
        await db.execute(
            select(
                User.id,
                User.name,
                User.is_active,
                EmployeeBillingDetails.nip,
                EmployeeProfile.work_start_date,
                EmployeeProfile.hired_on,
                EmployeeProfile.last_working_day,
                EmployeeProfile.exited_at,
            )
            .outerjoin(EmployeeProfile, EmployeeProfile.user_id == User.id)
            .outerjoin(
                EmployeeBillingDetails, EmployeeBillingDetails.user_id == User.id
            )
            .where(User.id.in_(ids))
            .order_by(User.name)
        )
    ).all()

    sheets = {
        s.user_id: s
        for s in (
            await db.scalars(
                select(Timesheet).where(
                    Timesheet.user_id.in_(ids),
                    Timesheet.year == year,
                    Timesheet.month == mon,
                )
            )
        ).all()
    }
    by_user: dict[int, list[PayrollInvoice]] = {}
    for invoice in (
        await db.scalars(
            select(PayrollInvoice).where(
                PayrollInvoice.user_id.in_(ids),
                PayrollInvoice.match_status != "ignored",
                for_month,
            )
        )
    ).all():
        by_user.setdefault(int(invoice.user_id), []).append(invoice)
    chosen = {uid: pick_invoice(found, year, mon) for uid, found in by_user.items()}

    settlement_ids = [i.settlement_id for i in chosen.values() if i and i.settlement_id]
    settlements = (
        {
            s.id: s
            for s in (
                await db.scalars(
                    select(PayrollSettlement).where(
                        PayrollSettlement.id.in_(settlement_ids)
                    )
                )
            ).all()
        }
        if settlement_ids
        else {}
    )
    invoice_ids = [i.id for i in chosen.values() if i is not None]
    cost_paid = (
        dict(
            (
                await db.execute(
                    select(FinanceCostEntry.source_id, FinanceCostPayment.paid_on)
                    .join(
                        FinanceCostPayment,
                        FinanceCostPayment.entry_id == FinanceCostEntry.id,
                    )
                    .where(
                        FinanceCostEntry.source_type == PAYROLL_SOURCE,
                        FinanceCostEntry.source_id.in_(invoice_ids),
                        FinanceCostPayment.state == "paid",
                    )
                )
            ).all()
        )
        if invoice_ids
        else {}
    )

    rows = []
    for row in people:
        invoice = chosen.get(row.id)
        sheet = sheets.get(row.id)
        end = row.last_working_day or (
            business_date(row.exited_at) if row.exited_at is not None else None
        )
        if not in_team(
            profile_b2b=row.id in profile_b2b,
            active=bool(row.is_active),
            start=row.work_start_date or row.hired_on,
            end=end,
            first=first,
            last=last,
            sheet_type=sheet.employment_type if sheet is not None else None,
            has_invoice=invoice is not None,
        ):
            continue
        settlement = (
            settlements.get(invoice.settlement_id)
            if invoice is not None and invoice.settlement_id
            else None
        )
        rows.append(
            person_row(
                row.id,
                row.name,
                bool(row.nip),
                sheets.get(row.id),
                invoice,
                settlement,
                cost_paid.get(invoice.id) if invoice is not None else None,
            )
        )
    return {"month": month, "people": rows}
