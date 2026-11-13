"""Obroty i salda oraz karta konta (K1) — z zatwierdzonych zapisów dziennika.

* **Bilans otwarcia** to dokumenty ``BO`` roku (zatwierdzone), osobno od
  obrotów. Obroty okresu = zapisy z miesięcy ``od``–``do``, narastająco = od
  stycznia do ``do``. Saldo końcowe liczy się z BO i obrotów narastająco.
* **Poziom syntetyczny** grupuje analitykę słownikową pod kontem ze słownikiem
  (``201-2-1000`` → ``201-2``); analityczny pokazuje każde konto osobno.
* **Dokumenty płacowe** (D2: kwoty osób widzą tylko Płace i admin) wchodzą do
  sum kont, bo księga musi się bilansować — ale osoba bez Płac widzi je tylko
  zbiorczo: w obrotach i saldach na poziomie analitycznym ich pozycje idą pod
  konto syntetyczne (analityka słownika to często jedna osoba), a karta konta
  i liczniki zapisów ich nie zawierają (``payroll_hidden`` mówi tylko, że są).
  Saldo narastające na karcie z ukrytymi pozycjami pozwalałoby odjąć jedną
  kwotę od drugiej (przegląd bezpieczeństwa 14.11.2026).
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Optional

from sqlalchemy import case, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ledger import LedgerDocument, LedgerLine, LedgerPeriod, LedgerYear
from app.services.finance_ledger.costs import LedgerError
from app.services.ledger import engine
from app.services.ledger.documents import Viewer, account_name, load_plan

CARD_MAX = 2000
TOTAL_KEYS = ("bo_wn", "bo_ma", "wn", "ma", "ytd_wn", "ytd_ma", "saldo_wn", "saldo_ma")


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


def _sum(condition: Any) -> Any:
    return func.coalesce(func.sum(case((condition, LedgerLine.amount), else_=0)), 0)


async def trial_balance(
    db: AsyncSession,
    viewer: Viewer,
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
    payroll = LedgerDocument.sensitivity.is_not(None)

    rows = await db.execute(
        select(
            LedgerLine.account,
            payroll.label("payroll"),
            _sum(is_bo & debit),
            _sum(is_bo & credit),
            _sum(~is_bo & in_range & debit),
            _sum(~is_bo & in_range & credit),
            _sum(~is_bo & to_end & debit),
            _sum(~is_bo & to_end & credit),
        )
        .join(LedgerDocument, LedgerDocument.id == LedgerLine.document_id)
        .join(LedgerPeriod, LedgerPeriod.id == LedgerDocument.period_id)
        .where(
            LedgerDocument.year_id == year_row.id, LedgerDocument.status == "approved"
        )
        .group_by(LedgerLine.account, payroll)
    )
    plan = await load_plan(db)
    grouped: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0, 0, 0, 0])
    analytics: dict[str, set[str]] = defaultdict(set)
    for account, is_payroll, *amounts in rows.all():
        hidden = bool(is_payroll) and not viewer.payroll
        if level == "synthetic" or hidden:
            key = engine.synthetic_of(account, plan)
        else:
            key = account
        bucket = grouped[key]
        for index, value in enumerate(amounts):
            bucket[index] += int(value)
        if key != account and not hidden:
            analytics[key].add(account)
    items = []
    for account in sorted(grouped, key=lambda number: (number.split("-")[0], number)):
        bo_wn, bo_ma, wn, ma, ytd_wn, ytd_ma = grouped[account]
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
                "analytics": len(analytics.get(account, ())),
            }
        )
    totals = {key: sum(item[key] for item in items) for key in TOTAL_KEYS}
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
    """Zapisy konta (i jego analityki) w zakresie z saldem narastającym.

    Osoba bez Płac dostaje kartę bez dokumentów płacowych — także w saldach
    (``payroll_hidden`` = na koncie są zapisy, których nie widzi).
    """

    start, end = _range(month_from, month_to)
    year_row = await _year(db, year)
    plan = await load_plan(db)
    matches = or_(
        LedgerLine.account == account, LedgerLine.account.like(f"{account}-%")
    )
    scope = [
        LedgerDocument.year_id == year_row.id,
        LedgerDocument.status == "approved",
        matches,
    ]
    visible = [] if viewer.payroll else [LedgerDocument.sensitivity.is_(None)]
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
            *scope,
            *visible,
            or_(LedgerDocument.doc_type == "BO", LedgerPeriod.month < start),
        )
    )
    opening = int(before.scalar_one() or 0)
    rows = (
        await db.execute(
            select(LedgerLine, LedgerDocument)
            .join(LedgerDocument, LedgerDocument.id == LedgerLine.document_id)
            .join(LedgerPeriod, LedgerPeriod.id == LedgerDocument.period_id)
            .where(
                *scope,
                *visible,
                LedgerDocument.doc_type != "BO",
                LedgerPeriod.month.between(start, end),
            )
            .order_by(LedgerDocument.journal_no, LedgerLine.line_no)
            .limit(CARD_MAX + 1)
        )
    ).all()
    payroll_hidden = False
    if not viewer.payroll:
        payroll_hidden = bool(
            await db.scalar(
                select(
                    exists().where(
                        LedgerLine.document_id == LedgerDocument.id,
                        *scope,
                        LedgerDocument.sensitivity.is_not(None),
                    )
                )
            )
        )
    truncated = len(rows) > CARD_MAX
    balance = opening
    items: list[dict[str, Any]] = []
    for line, doc in rows[:CARD_MAX]:
        balance += line.amount if line.side == "debit" else -line.amount
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
        "payroll_hidden": payroll_hidden,
        "truncated": truncated,
    }
