"""Pozycje rozliczenia miesiąca: „Do faktury” (B2B), rozliczenie zlecenia, dane UoP.

Jedna reguła dla panelu osoby (M1, M2), widoku rozbieżności (M4), PDF-u
zlecenia i skrótu dokumentu. Kwoty biorą się z tej samej linii co płace
(R2, R11):

* **godziny × stawka** — ``hours_amount`` linii płac (zamrożonej po
  zamknięciu miesiąca), bez płatnych dni przerwy,
* **płatne dni przerwy z umowy** (B2B z pulą) — auto-wpisy ``leave_paid``
  zaakceptowanego raportu godzin; kwota = godziny tych wpisów × stawka, a
  godziny pracy dostają resztę ``hours_amount`` (suma pozycji zgadza się
  z linią co do grosza, bez dwóch zaokrągleń),
* **każda premia osobno** — przyznane premie z okresem w tym miesiącu
  i walucie linii.

Miesiąc otwarty liczy się tą samą regułą co zamknięcie (``payroll_report``):
stawka z 1. dnia miesiąca, wyłącznie zaakceptowany raport godzin. Bez
zaakceptowanego raportu pozycji godzin nie ma (``hours_confirmed = False``).
Nic tu nie zapisuje do bazy.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hr_payroll import HrBonus, PayrollLine
from app.models.hr_time import Timesheet, TimesheetEntry
from app.models.user import User
from app.services.hr import payroll_rates
from app.services.hr.employment_terms import capitalize, terms
from app.services.hr.payroll_bonuses import CATEGORY_LABELS
from app.services.hr.payroll_periods import MONTHS_PL, month_start
from app.services.hr.payroll_report import money

ZERO = Decimal("0")
APPROVED = "approved"
LEAVE_PAID_SOURCE = "leave_paid"


@dataclass(frozen=True)
class SettlementItem:
    kind: str  # hours | paid_days | bonus
    label: str
    amount: Decimal
    hours: Optional[Decimal] = None
    rate: Optional[Decimal] = None
    days: Optional[int] = None
    bonus_id: Optional[int] = None


@dataclass(frozen=True)
class TimesheetFacts:
    status: Optional[str]
    approved_at: Optional[datetime]
    approved_by_name: Optional[str]
    pdf_hash: Optional[str]
    hours: Decimal
    paid_break_hours: Decimal
    paid_break_days: int


@dataclass(frozen=True)
class MonthAmounts:
    year: int
    month: int
    currency: str
    employment_type: Optional[str]
    final: bool
    hours: Decimal
    hourly_rate: Optional[Decimal]
    total: Decimal
    hours_confirmed: bool
    timesheet: TimesheetFacts
    items: tuple[SettlementItem, ...] = field(default_factory=tuple)


def period_text(year: int, month: int) -> str:
    return f"{MONTHS_PL[month - 1]} {year}"


def _hours_text(value: Decimal) -> str:
    text = f"{value.normalize():f}" if value == value.to_integral() else f"{value:.2f}"
    return text.replace(".", ",")


def _rate_text(value: Decimal) -> str:
    return f"{value:.2f}".replace(".", ",")


async def timesheet_facts(
    db: AsyncSession, user_id: int, year: int, month: int
) -> TimesheetFacts:
    """Raport godzin miesiąca: status, kto i kiedy potwierdził, płatne dni przerwy."""

    row = (
        await db.execute(
            select(
                Timesheet.id,
                Timesheet.status,
                Timesheet.approved_at,
                Timesheet.pdf_hash,
                User.name,
            )
            .outerjoin(User, User.id == Timesheet.approved_by)
            .where(
                Timesheet.user_id == user_id,
                Timesheet.year == year,
                Timesheet.month == month,
            )
        )
    ).first()
    if row is None:
        return TimesheetFacts(None, None, None, None, ZERO, ZERO, 0)
    sums = (
        await db.execute(
            select(
                func.coalesce(func.sum(TimesheetEntry.hours), 0),
                func.coalesce(
                    func.sum(TimesheetEntry.hours).filter(
                        TimesheetEntry.source == LEAVE_PAID_SOURCE
                    ),
                    0,
                ),
                func.count(func.distinct(TimesheetEntry.work_date)).filter(
                    TimesheetEntry.source == LEAVE_PAID_SOURCE
                ),
            ).where(TimesheetEntry.timesheet_id == row.id)
        )
    ).one()
    return TimesheetFacts(
        status=str(row.status),
        approved_at=row.approved_at,
        approved_by_name=row.name,
        pdf_hash=row.pdf_hash,
        hours=Decimal(sums[0]),
        paid_break_hours=Decimal(sums[1]),
        paid_break_days=int(sums[2] or 0),
    )


async def assigned_bonuses(
    db: AsyncSession, user_id: int, year: int, month: int, currency: str
) -> list[HrBonus]:
    return list(
        await db.scalars(
            select(HrBonus)
            .where(
                HrBonus.recipient_user_id == user_id,
                HrBonus.period_year == year,
                HrBonus.period_month == month,
                HrBonus.currency == currency,
                HrBonus.status == "assigned",
            )
            .order_by(HrBonus.assigned_at, HrBonus.id)
        )
    )


def bonus_label(bonus: HrBonus, employment_type: Optional[str] = None) -> str:
    """„Premia · Rekruter” przy UoP, „Wynagrodzenie dodatkowe · Rekruter” przy
    B2B i zleceniu — pozycja dokumentu do faktury (decyzja Artura 21.10.2026)."""

    category = CATEGORY_LABELS.get(bonus.category, bonus.category)
    text = f"{capitalize(terms(employment_type)['bonus'])} · {category}"
    if bonus.description:
        text = f"{text} · {bonus.description.strip()[:120]}"
    return text


def build_items(
    *,
    employment_type: Optional[str],
    year: int,
    month: int,
    hours: Decimal,
    hourly_rate: Optional[Decimal],
    hours_amount: Optional[Decimal],
    paid_break_hours: Decimal,
    paid_break_days: int,
    bonuses: list[HrBonus],
) -> tuple[SettlementItem, ...]:
    """Pozycje dokumentu; suma pozycji = ``hours_amount`` + premie (co do grosza)."""

    items: list[SettlementItem] = []
    if hourly_rate is not None and hours_amount is not None and hours > 0:
        # Płatne dni przerwy tylko na B2B (zlecenie nie ma puli, UoP liczy program).
        paid_hours = paid_break_hours if employment_type == "b2b" else ZERO
        paid_hours = min(paid_hours, hours)
        paid_amount = money(paid_hours * hourly_rate) if paid_hours > 0 else ZERO
        work_hours = hours - paid_hours
        work_amount = money(hours_amount - paid_amount)
        if work_hours > 0 or work_amount != 0:
            noun = {
                "b2b": "Usługi",
                "zlecenie": "Wynagrodzenie ze zlecenia",
            }.get(employment_type or "", "Godziny")
            items.append(
                SettlementItem(
                    kind="hours",
                    label=(
                        f"{noun}, {period_text(year, month)} · "
                        f"{_hours_text(work_hours)} h × {_rate_text(hourly_rate)}"
                    ),
                    amount=work_amount,
                    hours=work_hours,
                    rate=hourly_rate,
                )
            )
        if paid_hours > 0:
            days = paid_break_days or 0
            items.append(
                SettlementItem(
                    kind="paid_days",
                    label=(
                        f"Płatne dni przerwy z umowy · {days} "
                        f"{'dzień' if days == 1 else 'dni'} "
                        f"({_hours_text(paid_hours)} h × {_rate_text(hourly_rate)})"
                    ),
                    amount=paid_amount,
                    hours=paid_hours,
                    rate=hourly_rate,
                    days=days,
                )
            )
    for bonus in bonuses:
        items.append(
            SettlementItem(
                kind="bonus",
                label=bonus_label(bonus, employment_type),
                amount=money(Decimal(bonus.amount)),
                bonus_id=bonus.id,
            )
        )
    return tuple(items)


async def frozen_amounts(
    db: AsyncSession, line: PayrollLine, *, year: int, month: int
) -> MonthAmounts:
    """Pozycje zamkniętego miesiąca z zamrożonej linii płac."""

    facts = await timesheet_facts(db, line.user_id, year, month)
    bonuses = await assigned_bonuses(db, line.user_id, year, month, line.currency)
    hours = Decimal(line.hours)
    rate = None if line.hourly_rate is None else Decimal(line.hourly_rate)
    return MonthAmounts(
        year=year,
        month=month,
        currency=line.currency,
        employment_type=line.employment_type,
        final=True,
        hours=hours,
        hourly_rate=rate,
        total=money(Decimal(line.total)),
        hours_confirmed=line.timesheet_status == APPROVED,
        timesheet=facts,
        items=build_items(
            employment_type=line.employment_type,
            year=year,
            month=month,
            hours=hours,
            hourly_rate=rate,
            hours_amount=None
            if line.hours_amount is None
            else Decimal(line.hours_amount),
            # Linia zna tylko sumę godzin; auto-wpisy z raportu, gdy linia niesie godziny.
            paid_break_hours=facts.paid_break_hours if hours > 0 else ZERO,
            paid_break_days=facts.paid_break_days,
            bonuses=bonuses,
        ),
    )


async def estimate_amounts(
    db: AsyncSession,
    *,
    user_id: int,
    employment_type: Optional[str],
    year: int,
    month: int,
) -> list[MonthAmounts]:
    """Miesiąc otwarty: regułą zamknięcia (zaakceptowane godziny, stawka z 1. dnia).

    Pusta lista = nic do rozliczenia (bez godzin z zaakceptowanego raportu i bez
    premii). Waluty jak w raporcie płac: waluta stawki i waluty premii.
    """

    facts = await timesheet_facts(db, user_id, year, month)
    approved = facts.status == APPROVED
    hours = facts.hours if approved else ZERO
    rate = payroll_rates.rate_on(
        await payroll_rates.history(db, user_id), month_start(year, month)
    )
    bonus_rows = list(
        await db.scalars(
            select(HrBonus)
            .where(
                HrBonus.recipient_user_id == user_id,
                HrBonus.period_year == year,
                HrBonus.period_month == month,
                HrBonus.status == "assigned",
            )
            .order_by(HrBonus.assigned_at, HrBonus.id)
        )
    )
    currencies = {bonus.currency for bonus in bonus_rows}
    if rate is not None and hours > 0:
        currencies.add(rate.currency)
    out: list[MonthAmounts] = []
    for currency in sorted(currencies):
        bonuses = [bonus for bonus in bonus_rows if bonus.currency == currency]
        hourly: Optional[Decimal] = None
        hours_amount: Optional[Decimal] = None
        if rate is not None and rate.currency == currency:
            hourly = Decimal(rate.hourly_rate)
            hours_amount = money(hours * hourly)
        items = build_items(
            employment_type=employment_type,
            year=year,
            month=month,
            hours=hours,
            hourly_rate=hourly,
            hours_amount=hours_amount,
            paid_break_hours=facts.paid_break_hours if approved else ZERO,
            paid_break_days=facts.paid_break_days if approved else 0,
            bonuses=bonuses,
        )
        total = money((hours_amount or ZERO) + sum((b.amount for b in bonuses), ZERO))
        out.append(
            MonthAmounts(
                year=year,
                month=month,
                currency=currency,
                employment_type=employment_type,
                final=False,
                hours=hours,
                hourly_rate=hourly,
                total=total,
                hours_confirmed=approved,
                timesheet=facts,
                items=items,
            )
        )
    return out


def item_payload(item: SettlementItem) -> dict[str, Any]:
    return {
        "kind": item.kind,
        "label": item.label,
        "amount": str(item.amount),
        "hours": None if item.hours is None else str(item.hours),
        "rate": None if item.rate is None else str(item.rate),
        "days": item.days,
        "bonus_id": item.bonus_id,
    }


def document_hash(
    *, user_id: int, amounts: MonthAmounts, expected_amount: Decimal
) -> str:
    """Skrót dokumentu rozliczenia zlecenia (stopka PDF-u, kolumna ``document_sha256``).

    Liczony z treści (osoba, okres, pozycje, kwota, suma kontrolna raportu
    godzin), nie z bajtów PDF-u — WeasyPrint wpisuje do pliku datę
    wygenerowania, a skrót ma być ten sam przy każdym pobraniu.
    """

    canonical = {
        "user_id": user_id,
        "period": f"{amounts.year}-{amounts.month:02d}",
        "currency": amounts.currency,
        "employment_type": amounts.employment_type,
        "expected": str(money(Decimal(expected_amount))),
        "timesheet_pdf_hash": amounts.timesheet.pdf_hash,
        "items": [[item.kind, item.label, str(item.amount)] for item in amounts.items],
    }
    raw = json.dumps(
        canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


__all__ = [
    "MonthAmounts",
    "SettlementItem",
    "TimesheetFacts",
    "assigned_bonuses",
    "bonus_label",
    "build_items",
    "document_hash",
    "estimate_amounts",
    "frozen_amounts",
    "item_payload",
    "period_text",
    "timesheet_facts",
]
