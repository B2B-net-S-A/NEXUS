"""Stan zapłaty wpisu kolejki kosztów (E3) — wyrażenie SQL i etykiety.

Osobny moduł bez zależności od ``costs.py`` (kolejka importuje go do kolumny
i filtra „Zapłata”, a serwis płatności importuje kolejkę).

* Faktura dostawcy, kontraktora albo dokument wydatku — stan z
  ``finance_cost_payments`` (brak wiersza = „Do zapłaty”).
* Faktura osoby zespołu — zapłatę prowadzą Płace, więc stan czytamy
  z rozliczenia miesiąca: opłacone rozliczenie = „Zapłacona”, rozliczenie
  w paczce Płac, która czeka = „W paczce”, inaczej „Do zapłaty”. Kolejka
  kosztów nie zapisuje zapłaty takich faktur (inna ścieżka NEXUSA).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy import case, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.finance_ledger import FinanceCostEntry
from app.models.finance_payments import FinanceCostPayment
from app.models.hr_settlement import PayrollInvoice, PayrollPayment, PayrollSettlement
from app.services.finance_payments_schema import PAYMENT_STATES

STATE_LABELS: dict[str, str] = {
    "unpaid": "Do zapłaty",
    "in_batch": "W paczce",
    "paid": "Zapłacona",
    "partially_paid": "Zapłacona częściowo",
}
SOURCE_LABELS: dict[str, str] = {
    "statement": "wyciąg",
    "manual": "ręcznie",
    "other_path": "Płace (rozliczenie miesiąca)",
}


def _payroll_state():
    entry = FinanceCostEntry
    waiting = exists().where(
        PayrollPayment.settlement_id == PayrollSettlement.id,
        PayrollPayment.kind == "transfer_batch",
        PayrollPayment.match_status == "matched",
    )
    return (
        select(
            case(
                (PayrollSettlement.status == "paid", "paid"),
                (waiting, "in_batch"),
                else_="unpaid",
            )
        )
        .select_from(PayrollInvoice)
        .join(PayrollSettlement, PayrollSettlement.id == PayrollInvoice.settlement_id)
        .where(PayrollInvoice.id == entry.source_id)
        .correlate(entry)
        .scalar_subquery()
    )


def state_sql():
    """Stan zapłaty wpisu ``FinanceCostEntry`` (wyrażenie do SELECT i WHERE)."""

    entry = FinanceCostEntry
    own = (
        select(FinanceCostPayment.state)
        .where(FinanceCostPayment.entry_id == entry.id)
        .correlate(entry)
        .scalar_subquery()
    )
    return case(
        (
            entry.source_type == "payroll_invoice",
            func.coalesce(_payroll_state(), "unpaid"),
        ),
        else_=func.coalesce(own, "unpaid"),
    )


def condition(state: str):
    if state not in PAYMENT_STATES:
        raise ValueError(state)
    return state_sql() == state


def summary(
    state: str, *, payroll: bool, paid_on: Any = None, source: Any = None
) -> dict[str, Any]:
    return {
        "state": state,
        "label": STATE_LABELS.get(state, state),
        "path": "payroll" if payroll else "costs",
        "paid_on": paid_on.isoformat() if paid_on is not None else None,
        "source": source,
        "source_label": SOURCE_LABELS.get(source or ""),
    }


async def for_entries(
    db: AsyncSession, entries: Iterable[FinanceCostEntry]
) -> dict[int, dict[str, Any]]:
    """Krótki stan zapłaty dla wierszy listy (jedno zapytanie)."""

    ids = [entry.id for entry in entries]
    if not ids:
        return {}
    rows = await db.execute(
        select(
            FinanceCostEntry.id,
            FinanceCostEntry.source_type,
            state_sql(),
            FinanceCostPayment.paid_on,
            FinanceCostPayment.paid_source,
        )
        .outerjoin(
            FinanceCostPayment, FinanceCostPayment.entry_id == FinanceCostEntry.id
        )
        .where(FinanceCostEntry.id.in_(ids))
    )
    result: dict[int, dict[str, Any]] = {}
    for entry_id, source_type, state, paid_on, source in rows.all():
        payroll = source_type == "payroll_invoice"
        result[int(entry_id)] = summary(
            state,
            payroll=payroll,
            paid_on=None if payroll else paid_on,
            source="other_path" if payroll and state == "paid" else source,
        )
    return result


__all__ = [
    "SOURCE_LABELS",
    "STATE_LABELS",
    "condition",
    "for_entries",
    "state_sql",
    "summary",
]
