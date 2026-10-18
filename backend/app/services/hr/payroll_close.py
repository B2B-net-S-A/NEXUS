"""Zamknięcie i ponowne otwarcie miesiąca płac.

Zamknięcie (Płace):

1. blokada wiersza okresu (``FOR UPDATE``) — drugie żądanie czeka i dostaje
   „już zamknięty” (idempotentnie; restart przy nocnym wdrożeniu nie robi
   niczego dwa razy, bo całość to jedna transakcja) — i wszystkich
   timesheetów miesiąca, ZANIM policzymy raport: akceptacja timesheetu czy
   premii w toku albo kończy się przed liczeniem, albo czeka na koniec
   zamknięcia i dostaje „zamknięty” (``payroll_periods.assert_open``),
2. propozycje premii z tym okresem muszą mieć decyzję (409 ``pending_bonuses``),
3. ostrzeżenia (timesheety niezatwierdzone, godziny bez stawki, stawka na
   zleceniu poniżej minimum roku miesiąca) wymagają
   potwierdzenia (409 ``close_warnings``, potem ``acknowledge_warnings``),
4. linie zamrożone w ``payroll_lines``, ``payroll_locked`` na timesheetach
   osób z listy (most ``payroll_time_bridge``), wpis w ``hr_job_runs``
   (bez kwot) i ślad w ``hr_audit_events`` z ``sensitivity='payroll'``.

Ponowne otwarcie: wyłącznie administrator, z powodem; linie znikają (raport
znów liczy się z danych), timesheety odblokowane, ślad z poprzednimi sumami.

Rozliczenia (etap 4, moduł ``settlements``): zamknięcie zakłada rozliczenie
każdej linii z kwotą (``settlements.ensure_for_period`` — B2B czeka na
fakturę, zlecenie i UoP mają kwotę od razu; faktury, które przyszły
wcześniej, dopinają się same). Przy wyłączonym module rozliczeń nic nie
powstaje (moduł ciemny — ``POST /api/hr/settlements/months/…/prepare``
założy je później). Ponowne otwarcie anuluje nieopłacone rozliczenia zawsze,
także przy wyłączonym module; opłacone zostają jako dowód.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

from sqlalchemy import delete, func, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import local_now
from app.models.hr_ops import HrJobRun
from app.models.hr_payroll import HrBonus, PayrollLine
from app.services.hr import audit, payroll_time_bridge, settlements, settlements_rules
from app.services.hr import modules as hr_modules
from app.services.hr.payroll_errors import PayrollConflict, PayrollError
from app.services.hr.payroll_periods import (
    get_period,
    label,
    lock_period,
    month_end,
    validate_period,
)
from app.services.hr.payroll_report import (
    PersonPayroll,
    compute_live,
    line_rows,
    minimum_rate_warnings,
)

CLOSE_JOB_KIND = "payroll_close"
WARNING_PEOPLE_LIMIT = 50


def close_warnings(people: list[PersonPayroll]) -> list[dict[str, Any]]:
    """Ostrzeżenia przed zamknięciem — same imiona i liczby, bez kwot."""

    unapproved = [
        {"user_id": p.user_id, "name": p.name, "timesheet_status": p.timesheet_status}
        for p in people
        if p.timesheet_required and p.timesheet_status != "approved"
    ]
    missing_rates = [
        {"user_id": p.user_id, "name": p.name} for p in people if p.rate_missing
    ]
    warnings: list[dict[str, Any]] = []
    if unapproved:
        warnings.append(
            {
                "code": "unapproved_timesheets",
                "message": (
                    f"{len(unapproved)} os. bez zatwierdzonego timesheetu — "
                    "ich godziny nie wejdą do płac tego miesiąca."
                ),
                "count": len(unapproved),
                "people": unapproved[:WARNING_PEOPLE_LIMIT],
            }
        )
    if missing_rates:
        warnings.append(
            {
                "code": "missing_rates",
                "message": (
                    f"{len(missing_rates)} os. ma godziny bez stawki — "
                    "za godziny nic nie zostanie naliczone."
                ),
                "count": len(missing_rates),
                "people": missing_rates[:WARNING_PEOPLE_LIMIT],
            }
        )
    warnings.extend(minimum_rate_warnings(people, people_limit=WARNING_PEOPLE_LIMIT))
    return warnings


async def pending_bonus_count(db: AsyncSession, year: int, month: int) -> int:
    return int(
        await db.scalar(
            select(func.count())
            .select_from(HrBonus)
            .where(
                HrBonus.period_year == year,
                HrBonus.period_month == month,
                HrBonus.status == "proposed",
            )
        )
        or 0
    )


def _totals(rows: list[dict[str, Any]]) -> dict[str, str]:
    sums: dict[str, Any] = {}
    for row in rows:
        sums[row["currency"]] = sums.get(row["currency"], 0) + row["total"]
    return {currency: str(total) for currency, total in sorted(sums.items())}


async def close_month(
    db: AsyncSession,
    *,
    year: int,
    month: int,
    actor_id: int,
    acknowledge_warnings: bool,
    today: date,
) -> dict[str, Any]:
    validate_period(year, month)
    if month_end(year, month) > today:
        raise PayrollError(
            f"{label(year, month).capitalize()} jeszcze trwa — miesiąc zamyka się "
            "od jego ostatniego dnia."
        )
    period = await lock_period(db, year, month)
    if period.status == "closed":
        return {
            "year": year,
            "month": month,
            "status": "closed",
            "already_closed": True,
            "people": int(
                await db.scalar(
                    select(func.count(func.distinct(PayrollLine.user_id))).where(
                        PayrollLine.period_id == period.id
                    )
                )
                or 0
            ),
        }

    await payroll_time_bridge.lock_month_timesheets(db, year, month)
    pending = await pending_bonus_count(db, year, month)
    if pending:
        raise PayrollConflict(
            f"{pending} propozycji premii z tego miesiąca czeka na decyzję — "
            "zatwierdź je, odrzuć albo przenieś na kolejny miesiąc.",
            code="pending_bonuses",
            data={"count": pending},
        )

    people = await compute_live(db, year, month)
    warnings = close_warnings(people)
    if warnings and not acknowledge_warnings:
        raise PayrollConflict(
            "Przed zamknięciem sprawdź ostrzeżenia.",
            code="close_warnings",
            data={"warnings": warnings},
        )

    await db.execute(delete(PayrollLine).where(PayrollLine.period_id == period.id))
    rows = line_rows(period.id, people)
    if rows:
        await db.execute(insert(PayrollLine), rows)
    user_ids = [p.user_id for p in people]
    locked = await payroll_time_bridge.set_payroll_lock(
        db, year, month, user_ids, locked=True
    )

    period.status = "closed"
    period.closed_by = actor_id
    period.closed_at = local_now()
    period.close_count = (period.close_count or 0) + 1
    created: Optional[dict[str, int]] = None
    # Miesiąc sprzed rozliczeń w NEXUSIE (archiwum Compassa) zamyka się bez nich.
    if (await hr_modules.load_modules(db)).get(
        hr_modules.HrModule.settlements
    ) and settlements_rules.settled_in_nexus(
        year, month, await settlements.load_settlements_since(db)
    ):
        await db.flush()
        created = await settlements.ensure_for_period(db, period, actor_id=actor_id)
    counts = {
        "people": len(people),
        "lines": len(rows),
        "timesheets_locked": locked,
        "warnings": [w["code"] for w in warnings],
        **({"settlements": created["created"]} if created is not None else {}),
    }
    # Ślad przebiegu (bez kwot); kolejne zamknięcie po ponownym otwarciu ma
    # własny klucz. Upsert: ślad nie może zablokować zamknięcia.
    run = pg_insert(HrJobRun).values(
        kind=CLOSE_JOB_KIND,
        period_key=f"{year}-{month:02d}#{period.close_count}",
        status="done",
        counts=counts,
        finished_at=local_now(),
    )
    await db.execute(
        run.on_conflict_do_update(
            index_elements=[HrJobRun.kind, HrJobRun.period_key],
            set_={
                "status": run.excluded.status,
                "counts": run.excluded.counts,
                "finished_at": run.excluded.finished_at,
            },
        )
    )
    audit.record(
        db,
        actor_user_id=actor_id,
        subject_user_id=None,
        entity_type="payroll_period",
        entity_id=period.id,
        action="month_closed",
        sensitivity="payroll",
        details={
            "year": year,
            "month": month,
            "people": len(people),
            "totals": _totals(rows),
            "acknowledged": [w["code"] for w in warnings],
        },
    )
    await db.flush()
    result: dict[str, Any] = {
        "year": year,
        "month": month,
        "status": "closed",
        "already_closed": False,
        "people": len(people),
        "timesheets_locked": locked,
    }
    if created is not None:
        result["settlements"] = created
    return result


async def reopen_month(
    db: AsyncSession, *, year: int, month: int, actor_id: int, reason: str
) -> dict[str, Any]:
    validate_period(year, month)
    note = (reason or "").strip()
    if len(note) < 3:
        raise PayrollError("Podaj powód ponownego otwarcia (co najmniej 3 znaki).")
    if await get_period(db, year, month) is None:
        raise PayrollConflict("Ten miesiąc nie jest zamknięty.")
    period = await lock_period(db, year, month)
    if period.status != "closed":
        raise PayrollConflict("Ten miesiąc nie jest zamknięty.")

    lines = list(
        await db.scalars(select(PayrollLine).where(PayrollLine.period_id == period.id))
    )
    previous = _totals(
        [{"currency": line.currency, "total": line.total} for line in lines]
    )
    user_ids = {line.user_id for line in lines}
    user_ids |= await payroll_time_bridge.locked_user_ids(db, year, month)
    cancelled = await settlements.cancel_for_period(db, period, actor_id=actor_id)
    await db.execute(delete(PayrollLine).where(PayrollLine.period_id == period.id))
    unlocked = await payroll_time_bridge.set_payroll_lock(
        db, year, month, user_ids, locked=False
    )
    period.status = "open"
    period.reopened_by = actor_id
    period.reopened_at = local_now()
    period.reopen_reason = note[:1000]
    audit.record(
        db,
        actor_user_id=actor_id,
        subject_user_id=None,
        entity_type="payroll_period",
        entity_id=period.id,
        action="month_reopened",
        sensitivity="payroll",
        details={
            "year": year,
            "month": month,
            "reason": note[:1000],
            "previous_totals": previous,
            "settlements_cancelled": cancelled,
        },
    )
    await db.flush()
    return {
        "year": year,
        "month": month,
        "status": "open",
        "timesheets_unlocked": unlocked,
    }


__all__ = ["close_month", "close_warnings", "pending_bonus_count", "reopen_month"]
