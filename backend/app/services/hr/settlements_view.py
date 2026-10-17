"""Odczyty rozliczeń: kolejka Płac (M3), porównanie rozbieżności (M4), panel osoby (M1, M2).

Nic tu nie zapisuje. Rachunku nie ma w żadnej odpowiedzi — tylko 4 ostatnie
cyfry i źródło (``white_list``/``manual``). Kwoty widzą Płace i sama osoba
(trasy pilnują zakresu); przełożony nie dostaje tych odczytów wcale.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_date
from app.models.hr_payroll import PayrollLine, PayrollPeriod
from app.models.hr_profile import EmployeeProfile
from app.models.hr_settlement import (
    EmployeeBillingDetails,
    PayrollInvoice,
    PayrollSettlement,
)
from app.models.user import User
from app.services.hr import settlements, settlements_items
from app.services.hr.employment_terms import FORM_SHORT_LABELS, terms
from app.services.hr.payroll_periods import get_period, label
from app.services.hr.payroll_report import money
from app.services.hr.settlements_items import MonthAmounts, item_payload
from app.services.hr.payroll_rates import format_pln
from app.services.hr.settlements_rules import (
    B2B,
    URGENCY,
    net_total,
    problems_of,
    status_label,
)
from app.services.hr_settlement_schema import EMPLOYMENT_TYPES

ZERO = Decimal("0")


def _iso(value: Any) -> Optional[str]:
    return value.isoformat() if value is not None else None


def _day(moment: Any) -> Optional[str]:
    return business_date(moment).isoformat() if moment is not None else None


def _str(value: Optional[Decimal]) -> Optional[str]:
    return None if value is None else str(money(Decimal(value)))


async def _names(db: AsyncSession, ids: set[Optional[int]]) -> dict[int, str]:
    wanted = sorted(i for i in ids if i is not None)
    if not wanted:
        return {}
    rows = await db.execute(select(User.id, User.name).where(User.id.in_(wanted)))
    return {int(uid): str(name) for uid, name in rows.all()}


async def _billing(
    db: AsyncSession, user_ids: set[int]
) -> dict[int, EmployeeBillingDetails]:
    if not user_ids:
        return {}
    rows = await db.scalars(
        select(EmployeeBillingDetails).where(
            EmployeeBillingDetails.user_id.in_(sorted(user_ids))
        )
    )
    return {row.user_id: row for row in rows}


async def _invoices(
    db: AsyncSession, settlement_ids: list[int]
) -> dict[int, list[PayrollInvoice]]:
    out: dict[int, list[PayrollInvoice]] = defaultdict(list)
    if not settlement_ids:
        return out
    rows = await db.scalars(
        select(PayrollInvoice)
        .where(
            PayrollInvoice.settlement_id.in_(settlement_ids),
            PayrollInvoice.match_status == "matched",
        )
        .order_by(PayrollInvoice.issue_date, PayrollInvoice.id)
    )
    for row in rows:
        if row.settlement_id is not None:
            out[row.settlement_id].append(row)
    return out


def invoice_payload(invoice: PayrollInvoice) -> dict[str, Any]:
    return {
        "id": invoice.id,
        "source": invoice.source,
        "kind": invoice.invoice_kind,
        "invoice_number": invoice.invoice_number,
        "ksef_number": invoice.ksef_number,
        "issue_date": _iso(invoice.issue_date),
        "sale_date": _iso(invoice.sale_date),
        "received_on": settlements.received_on(invoice).isoformat(),
        "currency": invoice.currency,
        "net_amount": _str(invoice.net_amount),
        "vat_amount": _str(invoice.vat_amount),
        "gross_amount": _str(invoice.gross_amount),
    }


def _document(
    settlement: PayrollSettlement,
    invoices: list[PayrollInvoice],
    line: Optional[PayrollLine],
) -> dict[str, Any]:
    """Kolumna „Dokument” kolejki — według formy (M3)."""

    if settlement.employment_type == B2B:
        originals = [i for i in invoices if i.invoice_kind == "original"]
        if not originals:
            return {"kind": "invoice", "label": None, "date": None}
        first = originals[0]
        corrections = len(invoices) - len(originals)
        text = first.invoice_number
        if corrections:
            text = (
                f"{text} + korekta"
                if corrections == 1
                else f"{text} + {corrections} korekty"
            )
        return {
            "kind": "invoice",
            "label": text,
            "date": settlements.received_on(first).isoformat(),
            "source": first.source,
        }
    if settlement.employment_type == "zlecenie":
        confirmed = line is not None and line.timesheet_status == "approved"
        return {
            "kind": "hours",
            "label": "potwierdzenie godzin" if confirmed else "godziny niepotwierdzone",
            "date": None,
        }
    return {"kind": "payroll", "label": "dane do listy płac", "date": None}


def _override(
    settlement: PayrollSettlement, names: dict[int, str], viewer_id: int
) -> Optional[dict[str, Any]]:
    if settlement.override_requested_by is None:
        return None
    return {
        "kind": settlement.override_kind,
        "reason": settlement.override_reason,
        "requested_by": settlement.override_requested_by,
        "requested_by_name": names.get(settlement.override_requested_by),
        "requested_at": _iso(settlement.override_requested_at),
        "confirmed_by_name": names.get(settlement.override_confirmed_by)
        if settlement.override_confirmed_by
        else None,
        "confirmed_at": _iso(settlement.override_confirmed_at),
        "can_confirm": settlement.override_confirmed_by is None
        and settlement.status == "mismatch"
        and settlement.override_requested_by != viewer_id
        and settlement.user_id != viewer_id,
    }


def row_payload(
    settlement: PayrollSettlement,
    *,
    viewer_id: int,
    names: dict[int, str],
    billing: Optional[EmployeeBillingDetails],
    invoices: list[PayrollInvoice],
    line: Optional[PayrollLine],
) -> dict[str, Any]:
    mine = settlement.user_id == viewer_id
    problems = problems_of(
        employment_type=settlement.employment_type,
        discrepancy=settlement.discrepancy_amount,
        account_source=billing.account_source if billing else None,
    )
    hours_confirmed = None if line is None else line.timesheet_status == "approved"
    status = settlement.status
    return {
        "id": settlement.id,
        "user_id": settlement.user_id,
        "name": names.get(settlement.user_id, ""),
        "employment_type": settlement.employment_type,
        "form_short": FORM_SHORT_LABELS.get(settlement.employment_type, ""),
        "currency": settlement.currency,
        "expected_amount": _str(settlement.expected_amount),
        "amount_basis": settlement.amount_basis,
        "status": status,
        "status_label": status_label(status, settlement.employment_type),
        "due_on": _iso(settlement.due_on),
        "document": _document(settlement, invoices, line),
        "invoice_net": _str(
            net_total(i.net_amount for i in invoices) if invoices else None
        ),
        "invoice_gross": _str(
            net_total(i.gross_amount for i in invoices) if invoices else None
        ),
        "discrepancy": _str(settlement.discrepancy_amount),
        # Problemy liczą się tylko, dopóki dokument może zmienić stan.
        "problems": list(problems) if status in ("mismatch", "ready") else [],
        "hours_confirmed": hours_confirmed,
        "account_last4": billing.account_last4 if billing else None,
        "account_source": billing.account_source if billing else None,
        "correction_requested_at": _iso(settlement.correction_requested_at),
        "override": _override(settlement, names, viewer_id),
        "approved_at": _iso(settlement.approved_at),
        "approved_by_name": names.get(settlement.approved_by)
        if settlement.approved_by
        else None,
        "paid_on": _day(settlement.paid_at),
        "paid_source": settlement.paid_source,
        "paid_amount": _str(settlement.paid_amount),
        "mine": mine,
        "can_approve": status == "ready" and not mine,
        "can_mark_paid": status not in ("paid", "cancelled") and not mine,
        "has_pdf": settlement.employment_type == "zlecenie" and status != "cancelled",
    }


async def _rows_context(
    db: AsyncSession, rows: list[PayrollSettlement]
) -> tuple[
    dict[int, str],
    dict[int, EmployeeBillingDetails],
    dict[int, list[PayrollInvoice]],
    dict[int, PayrollLine],
]:
    people = {row.user_id for row in rows}
    extra = {
        uid
        for row in rows
        for uid in (
            row.override_requested_by,
            row.override_confirmed_by,
            row.approved_by,
        )
    }
    names = await _names(db, people | extra)
    billing = await _billing(db, people)
    invoices = await _invoices(db, [row.id for row in rows])
    line_ids = [row.line_id for row in rows if row.line_id is not None]
    lines: dict[int, PayrollLine] = {}
    if line_ids:
        lines = {
            line.id: line
            for line in await db.scalars(
                select(PayrollLine).where(PayrollLine.id.in_(line_ids))
            )
        }
    return names, billing, invoices, lines


async def month_queue(
    db: AsyncSession, *, year: int, month: int, viewer_id: int
) -> dict[str, Any]:
    """Kolejka Płac miesiąca: jeden wiersz na osobę i walutę, według pilności."""

    period = await get_period(db, year, month)
    base: dict[str, Any] = {
        "year": year,
        "month": month,
        "label": label(year, month),
        "period_status": period.status if period else "open",
    }
    if period is None or period.status != "closed":
        return {**base, "rows": [], "stats": {}, "missing": 0, "cancelled": 0}
    rows = list(
        await db.scalars(
            select(PayrollSettlement)
            .where(PayrollSettlement.period_id == period.id)
            .order_by(PayrollSettlement.id)
        )
    )
    live = [row for row in rows if row.status != "cancelled"]
    names, billing, invoices, lines = await _rows_context(db, live)
    payloads = [
        row_payload(
            row,
            viewer_id=viewer_id,
            names=names,
            billing=billing.get(row.user_id),
            invoices=invoices.get(row.id, []),
            line=lines.get(row.line_id) if row.line_id else None,
        )
        for row in live
    ]
    payloads.sort(
        key=lambda p: (URGENCY.get(p["status"], 9), p["name"].casefold(), p["id"])
    )
    covered = {(row.user_id, row.currency) for row in live}
    missing = 0
    for line in await db.scalars(
        select(PayrollLine).where(PayrollLine.period_id == period.id)
    ):
        if (
            (line.user_id, line.currency) not in covered
            and line.employment_type in EMPLOYMENT_TYPES
            and Decimal(line.total) > 0
        ):
            missing += 1
    stats = {
        "people": len({p["user_id"] for p in payloads}),
        "to_pay": sum(1 for p in payloads if p["status"] == "approved"),
        "ready": sum(1 for p in payloads if p["status"] == "ready"),
        "mismatch": sum(1 for p in payloads if p["status"] == "mismatch"),
        "awaiting_document": sum(
            1 for p in payloads if p["status"] == "awaiting_document"
        ),
        "hours_unconfirmed": sum(
            1
            for p in payloads
            if p["employment_type"] == "zlecenie" and p["hours_confirmed"] is False
        ),
        "paid": sum(1 for p in payloads if p["status"] == "paid"),
    }
    return {
        **base,
        "rows": payloads,
        "stats": stats,
        # Linie z kwotą bez rozliczenia (miesiąc zamknięty przed włączeniem modułu).
        "missing": missing,
        "cancelled": len(rows) - len(live),
    }


def _hours_hint(
    amounts: Optional[MonthAmounts], invoices: list[PayrollInvoice]
) -> Optional[str]:
    """„Godziny: 153,3 na fakturze, 152 w raporcie” — pozycja z tą samą stawką."""

    if amounts is None or amounts.hourly_rate is None:
        return None
    hours_item = next((i for i in amounts.items if i.kind == "hours"), None)
    if hours_item is None or hours_item.hours is None:
        return None
    rate = Decimal(amounts.hourly_rate)
    for invoice in invoices:
        for item in invoice.items or []:
            if not isinstance(item, dict):
                continue
            try:
                quantity = Decimal(str(item.get("quantity")))
                price = Decimal(str(item.get("unit_price")))
            except (ArithmeticError, ValueError, TypeError):
                continue
            if (
                not quantity.is_finite()
                or price != rate
                or quantity == hours_item.hours
            ):
                continue
            diff = quantity - hours_item.hours
            value = money(diff * rate)
            return (
                f"Godziny: {_num(quantity)} na fakturze, {_num(hours_item.hours)} "
                f"w raporcie. Różnica {_num(diff)} h × {format_pln(rate)} = "
                f"{format_pln(value)}."
            )
    return None


def _num(value: Decimal) -> str:
    """Godziny bez zbędnych zer: 152, 153,3, 1,25."""

    text = f"{value:f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text.replace(".", ",")


def explain(
    *,
    settlement: PayrollSettlement,
    amounts: Optional[MonthAmounts],
    invoices: list[PayrollInvoice],
    billing: Optional[EmployeeBillingDetails],
) -> list[str]:
    """„Co się nie zgadza” — zdania bez numeru rachunku."""

    if settlement.employment_type != B2B or not invoices:
        return []
    out: list[str] = []
    if settlement.discrepancy_amount is not None and settlement.discrepancy_amount != 0:
        diff = Decimal(settlement.discrepancy_amount)
        word = "wyższa" if diff > 0 else "niższa"
        out.append(
            f"Faktura netto {word} o {format_pln(abs(diff))} {settlement.currency} "
            "od kwoty z zamkniętego miesiąca."
        )
        hint = _hours_hint(amounts, invoices)
        if hint:
            out.append(hint)
    if billing is None or billing.account_last4 is None:
        out.append("Brak rachunku do przelewu w danych do rozliczeń.")
    elif billing.account_source != "white_list":
        out.append(
            "Rachunek wpisany ręcznie, nie z białej listy VAT — zapłata wymaga "
            "drugiej osoby."
        )
    return out


async def settlement_detail(
    db: AsyncSession, settlement: PayrollSettlement, *, viewer_id: int
) -> dict[str, Any]:
    """Porównanie: pozycje z NEXUSA obok faktur z KSeF (M4)."""

    names, billing, invoices, lines = await _rows_context(db, [settlement])
    line = lines.get(settlement.line_id) if settlement.line_id else None
    period = await settlements.period_of(db, settlement)
    amounts = (
        await settlements_items.frozen_amounts(
            db, line, year=period.year, month=period.month
        )
        if line is not None
        else None
    )
    own_invoices = invoices.get(settlement.id, [])
    person_billing = billing.get(settlement.user_id)
    row = row_payload(
        settlement,
        viewer_id=viewer_id,
        names=names,
        billing=person_billing,
        invoices=own_invoices,
        line=line,
    )
    return {
        **row,
        "year": period.year,
        "month": period.month,
        "label": label(period.year, period.month),
        "expected_items": [item_payload(i) for i in amounts.items] if amounts else [],
        "hours": None if amounts is None else str(amounts.hours),
        "hourly_rate": None
        if amounts is None or amounts.hourly_rate is None
        else str(amounts.hourly_rate),
        "timesheet_approved_on": _day(amounts.timesheet.approved_at)
        if amounts
        else None,
        "invoices": [
            {
                **invoice_payload(invoice),
                "items": [
                    item for item in (invoice.items or []) if isinstance(item, dict)
                ][:50],
            }
            for invoice in own_invoices
        ],
        "explain": explain(
            settlement=settlement,
            amounts=amounts,
            invoices=own_invoices,
            billing=person_billing,
        ),
        "can_request_correction": settlement.employment_type == B2B
        and settlement.status == "mismatch"
        and not row["mine"],
        "can_request_override": settlement.status == "mismatch"
        and settlement.override_requested_by is None
        and not row["mine"],
    }


# ── Panel osoby (M1, M2) ──────────────────────────────────────────────────────


def _step(
    key: str,
    label_text: str,
    state: str,
    *,
    date_value: Optional[str] = None,
    detail: Optional[str] = None,
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label_text,
        "state": state,
        "date": date_value,
        "detail": detail,
    }


#: Pierwszy krok według formy: (potwierdzony, czeka).
_HOURS_STEP: dict[str, tuple[str, str]] = {
    "b2b": ("Raport potwierdzony", "Raport godzin czeka na potwierdzenie"),
    "zlecenie": ("Godziny potwierdzone", "Godziny czekają na potwierdzenie"),
    "uop": ("Ewidencja zaakceptowana", "Ewidencja czeka na akceptację"),
}


def person_steps(
    *,
    employment_type: Optional[str],
    settlement: Optional[PayrollSettlement],
    amounts: MonthAmounts,
    invoices: list[PayrollInvoice],
    terms_days: Optional[int],
) -> list[dict[str, Any]]:
    """Kroki od godzin do „Opłacono” według formy (M1, M2)."""

    facts = amounts.timesheet
    approved = facts.status == "approved"
    done_label, waiting_label = _HOURS_STEP.get(
        employment_type or "", _HOURS_STEP["uop"]
    )
    hours_step = _step(
        "hours",
        done_label if approved else waiting_label,
        "done" if approved else "current",
        date_value=_day(facts.approved_at),
        detail=facts.approved_by_name,
    )
    status = settlement.status if settlement else "estimate"
    paid = status == "paid"
    paid_on = _day(settlement.paid_at) if settlement else None
    due = _iso(settlement.due_on) if settlement else None
    if employment_type == B2B:
        originals = [i for i in invoices if i.invoice_kind == "original"]
        has_invoice = bool(originals)
        compared = status in ("ready", "approved", "paid")
        overridden = bool(settlement and settlement.override_confirmed_by)
        return [
            hours_step,
            _step(
                "document",
                "Faktura w KSeF",
                "done" if has_invoice else ("current" if approved else "todo"),
                date_value=settlements.received_on(originals[0]).isoformat()
                if has_invoice
                else None,
                detail=originals[0].invoice_number if has_invoice else None,
            ),
            _step(
                "check",
                "Różnica uznana przez Płace"
                if overridden
                else ("Rozbieżność" if status == "mismatch" else "Kwota zgodna"),
                "done" if compared else ("warn" if status == "mismatch" else "todo"),
                detail="sprawdził NEXUS" if compared and not overridden else None,
            ),
            _step(
                "due",
                "Do zapłaty",
                "done"
                if status in ("approved", "paid")
                else ("current" if compared else "todo"),
                date_value=due,
                detail=f"{terms_days if terms_days is not None else 14} dni od numeru KSeF",
            ),
            _step(
                "paid",
                "Opłacono",
                "done" if paid else "todo",
                date_value=paid_on,
                detail=None if paid else "po przelewie",
            ),
        ]
    has_settlement = settlement is not None
    approved_payroll = status in ("approved", "paid")
    return [
        hours_step,
        _step(
            "amount",
            "Kwota policzona"
            if employment_type == "zlecenie"
            else "Dane do listy płac",
            "done" if has_settlement else ("current" if approved else "todo"),
            date_value=_day(settlement.created_at) if settlement else None,
        ),
        _step(
            "approved",
            "Przekazane do listy płac",
            "done" if approved_payroll else ("current" if has_settlement else "todo"),
            date_value=_day(settlement.approved_at) if settlement else None,
        ),
        _step(
            "paid",
            "Wypłacono" if paid else "Wypłata",
            "done" if paid else "todo",
            date_value=paid_on or due,
        ),
    ]


def _person_entry(
    *,
    amounts: MonthAmounts,
    settlement: Optional[PayrollSettlement],
    invoices: list[PayrollInvoice],
    billing: Optional[EmployeeBillingDetails],
) -> dict[str, Any]:
    employment_type = amounts.employment_type
    status = settlement.status if settlement else "estimate"
    terms_days = billing.payment_terms_days if billing else None
    invoice = None
    if invoices:
        originals = [i for i in invoices if i.invoice_kind == "original"] or invoices
        first = originals[0]
        invoice = {
            **invoice_payload(first),
            "net_total": _str(net_total(i.net_amount for i in invoices)),
            "gross_total": _str(net_total(i.gross_amount for i in invoices)),
            "corrections": sum(1 for i in invoices if i.invoice_kind == "correction"),
        }
    return {
        "settlement_id": settlement.id if settlement else None,
        "year": amounts.year,
        "month": amounts.month,
        "label": label(amounts.year, amounts.month),
        "employment_type": employment_type,
        "currency": amounts.currency,
        "final": amounts.final,
        "status": status,
        "status_label": "szacunek do zamknięcia miesiąca"
        if settlement is None
        else status_label(status, employment_type),
        "amount": _str(settlement.expected_amount if settlement else amounts.total),
        "amount_basis": "net" if employment_type == B2B else "gross",
        "hours": str(amounts.hours),
        "hourly_rate": None
        if amounts.hourly_rate is None
        else str(amounts.hourly_rate),
        "hours_confirmed": amounts.hours_confirmed,
        "items": [item_payload(item) for item in amounts.items],
        "steps": person_steps(
            employment_type=employment_type,
            settlement=settlement,
            amounts=amounts,
            invoices=invoices,
            terms_days=terms_days,
        ),
        "invoice": invoice,
        "account_last4": billing.account_last4 if billing else None,
        "account_source": billing.account_source if billing else None,
        "due_on": _iso(settlement.due_on) if settlement else None,
        "paid_on": _day(settlement.paid_at) if settlement else None,
        "correction_requested_at": _iso(settlement.correction_requested_at)
        if settlement
        else None,
        "discrepancy": _str(settlement.discrepancy_amount) if settlement else None,
        "has_pdf": bool(settlement)
        and employment_type == "zlecenie"
        and status != "cancelled",
    }


async def person_months(
    db: AsyncSession, *, user_id: int, year: int, today: date
) -> dict[str, Any]:
    """„Mój czas → Rozliczenie”: miesiące roku od najnowszego.

    Miesiąc zamknięty = rozliczenia osoby (bez anulowanych); otwarty = szacunek
    tą samą regułą co zamknięcie, tylko gdy jest co rozliczać (zaakceptowany
    raport albo premia).
    """

    profile = await db.scalar(
        select(EmployeeProfile).where(EmployeeProfile.user_id == user_id)
    )
    employment_type = profile.employment_type if profile else None
    last = 12 if year < today.year else (today.month if year == today.year else 0)
    periods = {
        int(period.month): period
        for period in await db.scalars(
            select(PayrollPeriod).where(PayrollPeriod.year == year)
        )
    }
    rows = list(
        await db.scalars(
            select(PayrollSettlement)
            .join(PayrollPeriod, PayrollPeriod.id == PayrollSettlement.period_id)
            .where(
                PayrollPeriod.year == year,
                PayrollSettlement.user_id == user_id,
                PayrollSettlement.status != "cancelled",
            )
            .order_by(PayrollSettlement.currency)
        )
    )
    by_period: dict[int, list[PayrollSettlement]] = defaultdict(list)
    for row in rows:
        by_period[row.period_id].append(row)
    _names_unused, billing_map, invoices, lines = await _rows_context(db, rows)
    billing = billing_map.get(user_id)
    months: list[dict[str, Any]] = []
    for month in range(last, 0, -1):
        period = periods.get(month)
        if period is not None and period.status == "closed":
            for settlement in by_period.get(period.id, []):
                line = lines.get(settlement.line_id) if settlement.line_id else None
                if line is None:
                    continue
                amounts = await settlements_items.frozen_amounts(
                    db, line, year=year, month=month
                )
                months.append(
                    _person_entry(
                        amounts=amounts,
                        settlement=settlement,
                        invoices=invoices.get(settlement.id, []),
                        billing=billing,
                    )
                )
            continue
        for amounts in await settlements_items.estimate_amounts(
            db,
            user_id=user_id,
            employment_type=employment_type,
            year=year,
            month=month,
        ):
            if not amounts.items:
                continue
            months.append(
                _person_entry(
                    amounts=amounts, settlement=None, invoices=[], billing=billing
                )
            )
    return {
        "year": year,
        "employment_type": employment_type,
        "settlement_word": terms(employment_type)["settlement"],
        "account_last4": billing.account_last4 if billing else None,
        "account_source": billing.account_source if billing else None,
        "nip": billing.nip if billing else None,
        "months": months,
    }


__all__ = [
    "explain",
    "invoice_payload",
    "month_queue",
    "person_months",
    "person_steps",
    "row_payload",
    "settlement_detail",
]
