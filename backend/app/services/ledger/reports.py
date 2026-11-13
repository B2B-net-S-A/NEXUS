"""Obroty i salda oraz karta konta (K1) — z zatwierdzonych zapisów dziennika.

* **Bilans otwarcia** to dokumenty ``BO`` roku (zatwierdzone), osobno od
  obrotów. Obroty okresu = zapisy z miesięcy ``od``–``do``, narastająco = od
  stycznia do ``do``. Saldo końcowe liczy się z BO i obrotów narastająco.
* **Poziom syntetyczny** grupuje analitykę słownikową pod kontem ze słownikiem
  (``201-2-1000`` → ``201-2``); analityczny pokazuje każde konto osobno.
* **Dokumenty płacowe** (D2) wchodzą do sum kont, bo księga musi się
  bilansować. Na karcie konta osoba bez Płac widzi je jednym wierszem
  zbiorczym na okres, bez dokumentów i opisów.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Optional

from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ledger import LedgerDocument, LedgerLine, LedgerPeriod, LedgerYear
from app.services.finance_ledger.costs import LedgerError
from app.services.ledger import engine
from app.services.ledger.documents import Viewer, account_name, load_plan

CARD_MAX = 2000


def _range(month_from: Optional[int], month_to: Optional[int]) -> tuple[int, int]:
    start = month_from or 1
    end = month_to or 12
    if not (1 <= start <= 12 and 1 <= end <= 12) or start > end:
        raise LedgerError("Niepoprawny zakres miesięcy.", status=422)
    return start, end


async def _year(db: AsyncSession, year: int) -> LedgerYear:
    row = await db.scalar(select(LedgerYear).where(LedgerYear.year == year))
    if row is None:
        raise LedgerError(f"Nie ma roku obrotowego {year}.", status=404)
    return row


def _split(amount: int) -> tuple[int, int]:
    """Saldo (Wn − Ma) → (saldo Wn, saldo Ma)."""

    return (amount, 0) if amount >= 0 else (0, -amount)


async def trial_balance(
    db: AsyncSession,
    *,
    year: int,
    month_from: Optional[int] = None,
    month_to: Optional[int] = None,
    level: str = "synthetic",
) -> dict[str, Any]:
    start, end = _range(month_from, month_to)
    year_row = await _year(db, year)
    is_bo = LedgerDocument.doc_type == "BO"
    in_range = LedgerPeriod.month.between(start, end)
    to_end = LedgerPeriod.month <= end
    debit = LedgerLine.side == "debit"
    credit = LedgerLine.side == "credit"

    rows = await db.execute(
        select(
            LedgerLine.account,
            func.coalesce(
                func.sum(case(((is_bo) & debit, LedgerLine.amount), else_=0)), 0
            ),
            func.coalesce(
                func.sum(case(((is_bo) & credit, LedgerLine.amount), else_=0)), 0
            ),
            func.coalesce(
                func.sum(
                    case(((~is_bo) & in_range & debit, LedgerLine.amount), else_=0)
                ),
                0,
            ),
            func.coalesce(
                func.sum(
                    case(((~is_bo) & in_range & credit, LedgerLine.amount), else_=0)
                ),
                0,
            ),
            func.coalesce(
                func.sum(case(((~is_bo) & to_end & debit, LedgerLine.amount), else_=0)),
                0,
            ),
            func.coalesce(
                func.sum(
                    case(((~is_bo) & to_end & credit, LedgerLine.amount), else_=0)
                ),
                0,
            ),
        )
        .join(LedgerDocument, LedgerDocument.id == LedgerLine.document_id)
        .join(LedgerPeriod, LedgerPeriod.id == LedgerDocument.period_id)
        .where(
            LedgerDocument.year_id == year_row.id, LedgerDocument.status == "approved"
        )
        .group_by(LedgerLine.account)
    )
    plan = await load_plan(db)
    grouped: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0, 0, 0, 0, 0])
    for account, bo_wn, bo_ma, wn, ma, ytd_wn, ytd_ma in rows.all():
        key = engine.synthetic_of(account, plan) if level == "synthetic" else account
        bucket = grouped[key]
        for index, value in enumerate((bo_wn, bo_ma, wn, ma, ytd_wn, ytd_ma)):
            bucket[index] += int(value)
        if key != account:
            bucket[6] += 1
    items = []
    for account in sorted(grouped, key=lambda number: (number.split("-")[0], number)):
        bo_wn, bo_ma, wn, ma, ytd_wn, ytd_ma, analytics = grouped[account]
        saldo_wn, saldo_ma = _split(bo_wn - bo_ma + ytd_wn - ytd_ma)
        items.append(
            {
                "account": account,
                "name": account_name(account, plan) or "— konta nie ma w planie —",
                "class": account[0],
                "bo_wn": bo_wn,
                "bo_ma": bo_ma,
                "wn": wn,
                "ma": ma,
                "ytd_wn": ytd_wn,
                "ytd_ma": ytd_ma,
                "saldo_wn": saldo_wn,
                "saldo_ma": saldo_ma,
                "analytics": analytics,
            }
        )
    totals = {
        key: sum(item[key] for item in items)
        for key in (
            "bo_wn",
            "bo_ma",
            "wn",
            "ma",
            "ytd_wn",
            "ytd_ma",
            "saldo_wn",
            "saldo_ma",
        )
    }
    return {
        "year": year,
        "month_from": start,
        "month_to": end,
        "level": level,
        "items": items,
        "totals": totals,
        "balanced": totals["wn"] == totals["ma"]
        and totals["bo_wn"] == totals["bo_ma"]
        and totals["saldo_wn"] == totals["saldo_ma"],
    }


async def account_card(
    db: AsyncSession,
    viewer: Viewer,
    *,
    account: str,
    year: int,
    month_from: Optional[int] = None,
    month_to: Optional[int] = None,
) -> dict[str, Any]:
    """Zapisy konta (i jego analityki) w zakresie z saldem narastającym."""

    start, end = _range(month_from, month_to)
    year_row = await _year(db, year)
    plan = await load_plan(db)
    matches = or_(
        LedgerLine.account == account, LedgerLine.account.like(f"{account}-%")
    )
    base = (
        select(LedgerLine, LedgerDocument, LedgerPeriod.month)
        .join(LedgerDocument, LedgerDocument.id == LedgerLine.document_id)
        .join(LedgerPeriod, LedgerPeriod.id == LedgerDocument.period_id)
        .where(
            LedgerDocument.year_id == year_row.id,
            LedgerDocument.status == "approved",
            matches,
        )
    )
    before = await db.execute(
        select(
            func.coalesce(
                func.sum(
                    case(
                        (LedgerLine.side == "debit", LedgerLine.amount),
                        else_=-LedgerLine.amount,
                    )
                ),
                0,
            )
        )
        .select_from(LedgerLine)
        .join(LedgerDocument, LedgerDocument.id == LedgerLine.document_id)
        .join(LedgerPeriod, LedgerPeriod.id == LedgerDocument.period_id)
        .where(
            LedgerDocument.year_id == year_row.id,
            LedgerDocument.status == "approved",
            matches,
            or_(LedgerDocument.doc_type == "BO", LedgerPeriod.month < start),
        )
    )
    opening = int(before.scalar_one() or 0)
    rows = (
        await db.execute(
            base.where(
                LedgerDocument.doc_type != "BO", LedgerPeriod.month.between(start, end)
            )
            .order_by(LedgerDocument.journal_no, LedgerLine.line_no)
            .limit(CARD_MAX + 1)
        )
    ).all()
    truncated = len(rows) > CARD_MAX
    balance = opening
    items: list[dict[str, Any]] = []
    hidden: dict[int, list[int]] = defaultdict(lambda: [0, 0, 0])
    for line, doc, month in rows[:CARD_MAX]:
        signed = line.amount if line.side == "debit" else -line.amount
        balance += signed
        if doc.sensitivity is not None and not viewer.payroll:
            bucket = hidden[month]
            bucket[0 if line.side == "debit" else 1] += line.amount
            bucket[2] += 1
            continue
        items.append(
            {
                "journal_no": doc.journal_no,
                "document_id": doc.id,
                "doc_type": doc.doc_type,
                "number": doc.number,
                "op_date": doc.op_date.isoformat(),
                "description": line.description or doc.description,
                "account": line.account,
                "wn": line.amount if line.side == "debit" else 0,
                "ma": line.amount if line.side == "credit" else 0,
                "balance": balance,
            }
        )
    payroll_rows = [
        {
            "month": month,
            "wn": values[0],
            "ma": values[1],
            "lines": values[2],
            "label": "Dokumenty płacowe — szczegóły widzą Płace i administrator",
        }
        for month, values in sorted(hidden.items())
    ]
    exact = plan.get(account)
    resolved, _ = engine.resolve(account, plan)
    if exact is not None:
        dictionary = exact.dictionary
    elif resolved is not None and resolved.analytic:
        dictionary = resolved.plan.dictionary
    else:
        dictionary = None
    return {
        "account": account,
        "name": account_name(account, plan),
        "dictionary": dictionary,
        "year": year,
        "month_from": start,
        "month_to": end,
        "opening": opening,
        "closing": balance,
        "items": items,
        "payroll_rows": payroll_rows,
        "truncated": truncated,
    }
