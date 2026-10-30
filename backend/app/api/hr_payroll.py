"""Płace i premie — stawki, premie, zamknięcie miesiąca, eksport.

Prefiks ``/api/hr/payroll`` (wpięty w ``app/main.py``). Każda trasa ma nazwaną bramkę
``require_hr_*`` (``app/api/hr_gates.py`` albo własną w tym module) i sprawdza
przełącznik modułu w ``app_settings['hr_modules']``.

Bramki:

* ``require_hr_payroll_admin`` — uprawnienie „Płace” (Finanse z roli, admin
  zawsze): stawki, miesiące, zamknięcie, eksport, reguły premii,
* ``require_hr_payroll_member`` — Płace, osoba z kartoteką albo przełożony;
  zakres (swoje / zespół bez stawek / wszyscy) liczy handler
  (``payroll_access.PayrollViewer``),
* ``require_hr_payroll_reopen`` — ponowne otwarcie miesiąca: tylko admin.

Kwoty nie trafiają do logów ani ``critical_events`` — ślad zmian płacowych to
``hr_audit_events`` z ``sensitivity='payroll'``.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_onboarded_user
from app.api.hr_gates import ensure_module
from app.core.database import get_db
from app.core.scheduling import business_today
from app.models.hr_payroll import HrBonus
from app.models.hr_profile import EmployeeProfile
from app.models.user import User, UserRole
from app.services.action_permissions import ProductAction
from app.services.hr import audit, people
from app.services.hr import modules as hr_modules
from app.services.hr import (
    bonus_decisions,
    bonus_flags,
    bonus_rules,
    my_settlement,
    placement_bonuses,
    payroll_bonuses,
    payroll_close,
    payroll_export,
    payroll_jobs,
    payroll_periods,
    payroll_rates,
    settlement_import,
    payroll_report,
)
from app.services.hr.modules import HrModule
from app.services.hr.payroll_access import PayrollViewer, is_payroll, load_viewer
from app.services.hr.payroll_errors import PayrollError
from app.services.permission_denial import permission_denied

router = APIRouter()
logger = logging.getLogger(__name__)

MODULE = HrModule.payroll
NOT_MEMBER_DETAIL = (
    "Płace widzą osoby z kartoteką w NEXUSIE, ich koordynatorzy i dział Płac."
)
NOT_ADMIN_DETAIL = "Miesiąc płac otwiera ponownie tylko administrator."
NO_PROFILE_DETAIL = "Rozliczenie widzą osoby z kartoteką w NEXUSIE."
MONTHS_LISTED = 13


# ── Bramki ────────────────────────────────────────────────────────────────────


def require_hr_payroll_admin():
    """Uprawnienie „Płace” (admin zawsze)."""

    async def _check(
        current_user: User = Depends(require_onboarded_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        await ensure_module(db, current_user, MODULE)
        if not is_payroll(current_user):
            raise permission_denied(ProductAction.payroll)
        return current_user

    _check.required_permissions = (ProductAction.payroll,)
    return _check


def require_hr_payroll_member():
    """Płace, osoba z kartoteką albo przełożony (zakres w handlerze)."""

    async def _check(
        current_user: User = Depends(require_onboarded_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        await ensure_module(db, current_user, MODULE)
        if is_payroll(current_user):
            return current_user
        if await people.has_live_profile(db, current_user.id):
            return current_user
        if await people.direct_report_ids(db, current_user.id):
            return current_user
        raise HTTPException(status.HTTP_403_FORBIDDEN, NOT_MEMBER_DETAIL)

    return _check


def require_hr_payroll_reopen():
    """Ponowne otwarcie zamkniętego miesiąca — wyłącznie administrator."""

    async def _check(
        current_user: User = Depends(require_onboarded_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        await ensure_module(db, current_user, MODULE)
        if not current_user.has_role(UserRole.admin):
            raise HTTPException(status.HTTP_403_FORBIDDEN, NOT_ADMIN_DETAIL)
        return current_user

    return _check


PayrollAdmin = Annotated[User, Depends(require_hr_payroll_admin())]
PayrollMember = Annotated[User, Depends(require_hr_payroll_member())]
PayrollReopener = Annotated[User, Depends(require_hr_payroll_reopen())]


@contextmanager
def _http_errors() -> Iterator[None]:
    try:
        yield
    except PayrollError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc
    except bonus_rules.BonusRulesError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


# ── Ciała żądań ───────────────────────────────────────────────────────────────


class RateIn(BaseModel):
    hourly_rate: Decimal
    currency: str = Field(default="PLN", max_length=3)
    effective_from: date
    reason: Optional[str] = Field(default=None, max_length=500)


class MinimumRatesIn(BaseModel):
    """Minimalna stawka godzinowa na zleceniu per rok (``{"2026": "31.40"}``)."""

    rates: dict[str, Decimal] = Field(max_length=50)


class BonusIn(BaseModel):
    recipient_user_id: int
    amount: Decimal
    currency: str = Field(default="PLN", max_length=3)
    category: str = Field(default="custom", max_length=16)
    period_year: int
    period_month: int
    description: Optional[str] = Field(default=None, max_length=1000)
    contract_id: Optional[int] = Field(default=None, ge=1)


class BonusPatch(BaseModel):
    recipient_user_id: Optional[int] = Field(default=None, ge=1)
    contract_id: Optional[int] = Field(default=None, ge=1)
    change_reason: Optional[str] = Field(default=None, max_length=1000)
    amount: Optional[Decimal] = None
    currency: Optional[str] = Field(default=None, max_length=3)
    category: Optional[str] = Field(default=None, max_length=16)
    period_year: Optional[int] = None
    period_month: Optional[int] = None
    description: Optional[str] = Field(default=None, max_length=1000)


class BonusBatchIn(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=100)


class PayrollCancelIn(BaseModel):
    note: Optional[str] = Field(default=None, max_length=1000)


class CloseIn(BaseModel):
    acknowledge_warnings: bool = False


class ReopenIn(BaseModel):
    reason: str = Field(max_length=1000)


class ExtraDlIn(BaseModel):
    dl_user_id: int
    recipient_user_id: int


class DlHoursIn(BaseModel):
    user_id: int
    hours: int


class IndividualRecruiterIn(BaseModel):
    user_id: int
    base_percent: Decimal
    step_percent: Decimal
    expert_percent: Decimal


class RulesIn(BaseModel):
    recruiter_tier_bounds: Optional[list[Decimal]] = Field(default=None, max_length=2)
    recruiter_tier_amounts: Optional[list[Decimal]] = Field(default=None, max_length=3)
    dl_percent: Optional[Decimal] = None
    monthly_hours: Optional[int] = None
    eligible_business_days: Optional[int] = None
    extra_dl: Optional[list[ExtraDlIn]] = Field(default=None, max_length=50)
    dl_hours: Optional[list[DlHoursIn]] = Field(default=None, max_length=50)
    individual_recruiters: Optional[list[IndividualRecruiterIn]] = Field(
        default=None, max_length=20
    )
    automation_since: Optional[date] = None
    league_types: Optional[list[str]] = Field(default=None, max_length=10)


# ── Pomocnicze ────────────────────────────────────────────────────────────────


def _person_payload(
    person: payroll_report.PersonPayroll, *, with_amounts: bool
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "user_id": person.user_id,
        "name": person.name,
        "employment_type": person.employment_type,
        "timesheet_required": person.timesheet_required,
        "timesheet_status": person.timesheet_status,
        "hours": str(person.hours),
        "overtime_hours": str(person.overtime_hours),
        "paid_leave_days": str(person.paid_leave_days),
        "other_leave_days": str(person.other_leave_days),
    }
    if with_amounts:
        payload["rate_missing"] = person.rate_missing
        payload["lines"] = [
            {
                "currency": line.currency,
                "hourly_rate": None
                if line.hourly_rate is None
                else str(line.hourly_rate),
                "hours_amount": None
                if line.hours_amount is None
                else str(line.hours_amount),
                "bonus_total": str(line.bonus_total),
                "total": str(line.total),
            }
            for line in person.lines
        ]
    else:
        # Przełożony: premie tak, stawki i kwoty wynagrodzenia nie (D2).
        payload["bonuses"] = [
            {"currency": line.currency, "bonus_total": str(line.bonus_total)}
            for line in person.lines
            if line.bonus_total > 0
        ]
    return payload


def _timesheet_stats(people_rows: list[payroll_report.PersonPayroll]) -> dict[str, int]:
    required = [p for p in people_rows if p.timesheet_required]
    return {
        "timesheets_approved": sum(
            1 for p in required if p.timesheet_status == "approved"
        ),
        "timesheets_submitted": sum(
            1 for p in required if p.timesheet_status == "submitted"
        ),
        "timesheets_missing": sum(
            1 for p in required if p.timesheet_status in (None, "draft")
        ),
    }


async def _bonus_list(
    db: AsyncSession,
    bonuses: list[HrBonus],
    viewer: PayrollViewer,
    *,
    today: date,
) -> list[dict[str, Any]]:
    names = await payroll_bonuses.names_for(db, bonuses)
    ended_early = await placement_bonuses.ended_early_bonus_ids(db, bonuses)
    flags = (
        await bonus_flags.bonus_flags(db, bonuses, today=today)
        if viewer.payroll
        else {}
    )
    return [
        {
            **payroll_bonuses.bonus_payload(
                bonus, names, with_snapshot=viewer.payroll, today=today
            ),
            # Propozycję ręczną przełożonego zatwierdzają tylko Płace (19.10.2026).
            "can_approve": payroll_bonuses.can_approve(viewer, bonus),
            "contract_ended_early": bonus.id in ended_early,
            "flags": flags.get(bonus.id, []),
        }
        for bonus in bonuses
    ]


async def _later_and_missing(
    db: AsyncSession, viewer: PayrollViewer, year: int, month: int, *, today: date
) -> dict[str, Any]:
    """Płace: propozycje z późniejszych miesięcy i kontrakty bez stawki."""

    later = list(
        await db.scalars(
            select(HrBonus)
            .where(
                HrBonus.status == "proposed",
                (HrBonus.period_year * 12 + HrBonus.period_month) > year * 12 + month,
            )
            .order_by(HrBonus.period_year, HrBonus.period_month, HrBonus.id)
            .limit(300)
        )
    )
    return {
        "later": await _bonus_list(db, later, viewer, today=today),
        "missing_rates": await bonus_decisions.contracts_missing_rates(db, today=today),
    }


async def _in_progress(
    db: AsyncSession, viewer: PayrollViewer, *, today: date
) -> list[dict[str, Any]]:
    """Propozycje z placementów przed terminem („liczy się”) — z postępem."""

    query = (
        select(HrBonus)
        .where(
            HrBonus.status == "proposed",
            HrBonus.eligible_on.is_not(None),
            HrBonus.eligible_on > today,
        )
        .order_by(HrBonus.eligible_on, HrBonus.id)
        .limit(200)
    )
    if not viewer.payroll:
        query = query.where(HrBonus.recipient_user_id.in_(sorted(viewer.report_ids)))
    rows = list(await db.scalars(query))
    items = await _bonus_list(db, rows, viewer, today=today)
    await _add_progress(db, items, rows, await bonus_rules.load_rules(db), today=today)
    return items


async def _add_progress(
    db: AsyncSession,
    items: list[dict[str, Any]],
    bonuses: list[HrBonus],
    rules: bonus_rules.BonusRules,
    *,
    today: date,
) -> None:
    """Pasek „X z 21 dni roboczych” przy propozycji z placementu przed terminem.

    Jedno liczenie dla widoku miesiąca płac i dla „Mojego czasu” — osoba
    widzi tę samą liczbę co Płace; dni robocze z kalendarza firmy (z dniami
    wolnymi firmy, jak urlop).
    """

    starts: dict[int, date] = {}
    for index, bonus in enumerate(bonuses):
        start = (bonus.rule_snapshot or {}).get("start_date")
        if bonus.eligible_on is not None and bonus.eligible_on > today and start:
            starts[index] = date.fromisoformat(start)
    if not starts:
        return
    calendar = await bonus_rules.load_bonus_calendar(
        db, min(starts.values()), today, rules
    )
    for index, (item, bonus) in enumerate(zip(items, bonuses)):
        if bonus.eligible_on is None or bonus.eligible_on <= today:
            continue
        start = starts.get(index)
        item["business_days_elapsed"] = (
            bonus_rules.business_days_elapsed(start, today, calendar=calendar)
            if start
            else None
        )
        item["business_days_required"] = rules.eligible_business_days


# ── Moje ──────────────────────────────────────────────────────────────────────


@router.get("/me")
async def my_payroll(
    current_user: PayrollMember, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Moja stawka, moje premie i prognoza premii z podpisanych kontraktów.

    Premie w każdym stanie — także anulowane przez automat, z kodem powodu
    (``cancel_reason``), żeby nie znikały bez śladu. Propozycja przed terminem
    ma postęp „X z 21 dni”, przyznana — kto i kiedy ją przyznał, a każda —
    czy jej miesiąc jest już zamknięty w płacach (``period_closed``).
    """

    today = business_today()
    viewer = await load_viewer(db, current_user)
    rules = await bonus_rules.load_rules(db)
    rates = await payroll_rates.history(db, current_user.id)
    current = payroll_rates.rate_on(rates, today)
    bonuses = await payroll_bonuses.list_bonuses(
        db, viewer, user_id=current_user.id, limit=200
    )
    names = await payroll_bonuses.names_for(db, bonuses)
    assigners = {b.assigned_by for b in bonuses if b.assigned_by} - set(names)
    if assigners:
        names.update(
            {
                int(uid): str(name)
                for uid, name in (
                    await db.execute(
                        select(User.id, User.name).where(User.id.in_(assigners))
                    )
                ).all()
            }
        )
    closed = await payroll_periods.closed_months(db)
    # R11: przy włączonych rozliczeniach premia wypłacona = rozliczenie opłacone.
    paid = await payroll_bonuses.paid_flags(db, bonuses)
    items = [
        {
            **payroll_bonuses.bonus_payload(b, names, with_snapshot=False, today=today),
            "assigned_by_name": names.get(b.assigned_by) if b.assigned_by else None,
            # Miesiąc premii zamknięty w płacach = premia rozliczona z wypłatą.
            "period_closed": (b.period_year, b.period_month) in closed,
            **({"paid": paid.get(b.id, False)} if paid is not None else {}),
        }
        for b in bonuses
    ]
    await _add_progress(db, items, bonuses, rules, today=today)
    stages = await bonus_decisions.stages_for(
        db, [b.contract_id for b in bonuses if b.contract_id], today=today
    )
    for item, bonus in zip(items, bonuses):
        if bonus.contract_id in stages:
            item["stages"] = stages[bonus.contract_id]
    forecast = await my_settlement.bonus_forecast(
        db, user_id=current_user.id, today=today, rules=rules
    )
    forecast_stages = await bonus_decisions.stages_for(
        db, [item["contract_id"] for item in forecast], today=today
    )
    for item in forecast:
        item["stages"] = forecast_stages.get(item["contract_id"])
    return {
        "current_rate": payroll_rates.rate_payload(current) if current else None,
        "rates": [payroll_rates.rate_payload(rate) for rate in rates],
        "bonuses": items,
        "forecast": forecast,
        "business_days_required": rules.eligible_business_days,
    }


@router.get("/me/settlement")
async def my_payroll_settlement(
    current_user: PayrollMember,
    db: AsyncSession = Depends(get_db),
    year: Optional[int] = Query(default=None, ge=2020, le=2100),
) -> dict[str, Any]:
    """„Moje rozliczenie”: miesiące zamknięte z linii płac, otwarte jako szacunek.

    Tylko o sobie i tylko z kartoteką — Płace albo przełożony bez własnej
    kartoteki dostają 403 (nie mają czego rozliczać).
    """

    if not await people.has_live_profile(db, current_user.id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, NO_PROFILE_DETAIL)
    today = business_today()
    return await my_settlement.settlement(
        db, user_id=current_user.id, year=year or today.year, today=today
    )


# ── Miesiące ──────────────────────────────────────────────────────────────────


@router.get("/months")
async def list_months(
    current_user: PayrollAdmin, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    today = business_today()
    last = (today.year, today.month)
    first = payroll_periods.add_months(today.year, today.month, -(MONTHS_LISTED - 1))
    months = payroll_periods.months_between(first, last)
    pending = dict(
        (
            (int(y), int(m)),
            int(n),
        )
        for y, m, n in (
            await db.execute(
                select(HrBonus.period_year, HrBonus.period_month, func.count())
                .where(HrBonus.status == "proposed")
                .group_by(HrBonus.period_year, HrBonus.period_month)
            )
        ).all()
    )
    items = []
    for year, month in reversed(months):
        report = await payroll_report.month_report(db, year, month)
        items.append(
            {
                "year": year,
                "month": month,
                "label": payroll_periods.label(year, month),
                "status": report.status,
                "people": len(report.people),
                "totals": {k: str(v) for k, v in report.totals().items()},
                "pending_proposals": pending.get((year, month), 0),
                "can_close": report.status == "open"
                and payroll_periods.month_end(year, month) <= today,
            }
        )
    return {"items": items}


@router.get("/months/{year}/{month}")
async def month_detail(
    year: int,
    month: int,
    current_user: PayrollMember,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    with _http_errors():
        payroll_periods.validate_period(year, month)
    today = business_today()
    viewer = await load_viewer(db, current_user)
    if not viewer.payroll and not viewer.is_manager:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Miesiąc płac widzą Płace i przełożeni (swój zespół).",
        )
    report = await payroll_report.month_report(db, year, month)
    visible = [
        person
        for person in report.people
        if viewer.payroll or person.user_id in viewer.report_ids
    ]
    period = await payroll_periods.get_period(db, year, month)
    bonuses = await payroll_bonuses.list_bonuses(db, viewer, year=year, month=month)
    payload: dict[str, Any] = {
        "year": year,
        "month": month,
        "label": payroll_periods.label(year, month),
        "status": report.status,
        "frozen": report.frozen,
        "scope": "payroll" if viewer.payroll else "team",
        "closed_at": period.closed_at.isoformat()
        if period and period.closed_at
        else None,
        "reopened_at": period.reopened_at.isoformat()
        if period and period.reopened_at
        else None,
        "reopen_reason": period.reopen_reason if period and viewer.payroll else None,
        "can_close": viewer.payroll
        and report.status == "open"
        and payroll_periods.month_end(year, month) <= today,
        "can_reopen": viewer.admin and report.status == "closed",
        "stats": {
            "people": len(visible),
            **_timesheet_stats(visible),
            "proposals": sum(1 for b in bonuses if b.status == "proposed"),
        },
        "people": [_person_payload(p, with_amounts=viewer.payroll) for p in visible],
        "bonuses": await _bonus_list(db, bonuses, viewer, today=today),
        **(
            await _later_and_missing(db, viewer, year, month, today=today)
            if viewer.payroll
            else {}
        ),
        "in_progress": await _in_progress(db, viewer, today=today),
    }
    if viewer.payroll:
        payload["totals"] = {k: str(v) for k, v in report.totals().items()}
        payload["warnings"] = (
            payroll_close.close_warnings(report.people)
            + await payroll_close.ended_early_warnings(db, year, month)
            if report.status == "open"
            else []
        )
    return payload


@router.get("/months/{year}/{month}/export.xlsx")
async def export_month(
    year: int,
    month: int,
    current_user: PayrollAdmin,
    db: AsyncSession = Depends(get_db),
) -> Response:
    with _http_errors():
        payroll_periods.validate_period(year, month)
    report = await payroll_report.month_report(db, year, month)
    content = await payroll_export.render(report)
    audit.record(
        db,
        actor_user_id=current_user.id,
        subject_user_id=None,
        entity_type="payroll_period",
        entity_id=f"{year}-{month:02d}",
        action="month_exported",
        sensitivity="payroll",
        details={"year": year, "month": month, "status": report.status},
    )
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{payroll_export.filename(year, month)}"'
            )
        },
    )


@router.post("/months/{year}/{month}/close")
async def close_month(
    year: int,
    month: int,
    payload: CloseIn,
    current_user: PayrollAdmin,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    with _http_errors():
        return await payroll_close.close_month(
            db,
            year=year,
            month=month,
            actor_id=current_user.id,
            acknowledge_warnings=payload.acknowledge_warnings,
            today=business_today(),
        )


@router.post("/months/{year}/{month}/reopen")
async def reopen_month(
    year: int,
    month: int,
    payload: ReopenIn,
    current_user: PayrollReopener,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    with _http_errors():
        return await payroll_close.reopen_month(
            db, year=year, month=month, actor_id=current_user.id, reason=payload.reason
        )


# ── Osoba (kartoteka → Płace) ─────────────────────────────────────────────────


@router.get("/people/{user_id}")
async def person_payroll(
    user_id: int, current_user: PayrollMember, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    today = business_today()
    viewer = await load_viewer(db, current_user)
    profile = await people.profile_of(db, user_id)
    if profile is None or not viewer.sees_person(user_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie ma takiej osoby w Płacach.")
    bonuses = await payroll_bonuses.list_bonuses(db, viewer, user_id=user_id, limit=200)
    payload: dict[str, Any] = {
        "user_id": user_id,
        "scope": "full" if viewer.sees_rates_of(user_id) else "team",
        # Własną stawkę zmienia druga osoba z Płac albo admin (19.10.2026).
        "can_edit_rates": viewer.payroll
        and (user_id != viewer.user_id or viewer.admin),
        "can_add_bonus": viewer.manages_bonuses_of(user_id),
        "bonuses": await _bonus_list(db, bonuses, viewer, today=today),
    }
    if viewer.sees_rates_of(user_id):
        rates = await payroll_rates.history(db, user_id)
        current = payroll_rates.rate_on(rates, today)
        payload["current_rate"] = (
            payroll_rates.rate_payload(current) if current else None
        )
        payload["rates"] = [payroll_rates.rate_payload(rate) for rate in rates]
    return payload


@router.post("/people/{user_id}/rates", status_code=status.HTTP_201_CREATED)
async def set_rate(
    user_id: int,
    payload: RateIn,
    current_user: PayrollAdmin,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    with _http_errors():
        rate = await payroll_rates.set_rate(
            db,
            user_id=user_id,
            hourly_rate=payload.hourly_rate,
            currency=payload.currency,
            effective_from=payload.effective_from,
            reason=payload.reason,
            actor_id=current_user.id,
            today=business_today(),
            actor_is_admin=current_user.has_role(UserRole.admin),
        )
        # Zlecenie bez minimum dla roku albo w innej walucie — zapis z ostrzeżeniem.
        warning = await payroll_rates.mandate_minimum_check(
            db,
            user_id=user_id,
            hourly_rate=rate.hourly_rate,
            currency=rate.currency,
            effective_from=rate.effective_from,
        )
    return {**payroll_rates.rate_payload(rate), "warning": warning}


@router.delete("/rates/{rate_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rate(
    rate_id: int, current_user: PayrollAdmin, db: AsyncSession = Depends(get_db)
) -> Response:
    with _http_errors():
        await payroll_rates.delete_rate(
            db,
            rate_id=rate_id,
            actor_id=current_user.id,
            actor_is_admin=current_user.has_role(UserRole.admin),
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── Premie ────────────────────────────────────────────────────────────────────


@router.get("/bonuses")
async def list_bonuses(
    current_user: PayrollMember,
    db: AsyncSession = Depends(get_db),
    year: Optional[int] = Query(default=None, ge=2020, le=2100),
    month: Optional[int] = Query(default=None, ge=1, le=12),
    status_filter: Optional[str] = Query(
        default=None, alias="status", pattern="^(proposed|assigned|cancelled)$"
    ),
    user_id: Optional[int] = Query(default=None, ge=1),
) -> dict[str, Any]:
    viewer = await load_viewer(db, current_user)
    bonuses = await payroll_bonuses.list_bonuses(
        db, viewer, year=year, month=month, status=status_filter, user_id=user_id
    )
    return {"items": await _bonus_list(db, bonuses, viewer, today=business_today())}


async def _bonus_response(
    db: AsyncSession, bonus: HrBonus, viewer: PayrollViewer
) -> dict[str, Any]:
    (payload,) = await _bonus_list(db, [bonus], viewer, today=business_today())
    return payload


@router.post("/bonuses", status_code=status.HTTP_201_CREATED)
async def create_bonus(
    payload: BonusIn, current_user: PayrollMember, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    viewer = await load_viewer(db, current_user)
    with _http_errors():
        bonus = await payroll_bonuses.create_manual(
            db,
            viewer,
            payroll_bonuses.BonusInput(
                recipient_user_id=payload.recipient_user_id,
                amount=payload.amount,
                currency=payload.currency,
                category=payload.category,
                period_year=payload.period_year,
                period_month=payload.period_month,
                description=payload.description,
                contract_id=payload.contract_id,
            ),
            today=business_today(),
        )
    return await _bonus_response(db, bonus, viewer)


@router.patch("/bonuses/{bonus_id}")
async def update_bonus(
    bonus_id: int,
    payload: BonusPatch,
    current_user: PayrollMember,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    viewer = await load_viewer(db, current_user)
    changes = {k: v for k, v in payload.model_dump(exclude_unset=True).items()}
    for required in ("amount", "currency", "category", "period_year", "period_month"):
        if required in changes and changes[required] is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "Pole nie może być puste."
            )
    with _http_errors():
        bonus = await payroll_bonuses.update_bonus(
            db, viewer, bonus_id, changes, today=business_today()
        )
    return await _bonus_response(db, bonus, viewer)


@router.post("/bonuses/{bonus_id}/approve")
async def approve_bonus(
    bonus_id: int, current_user: PayrollMember, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    viewer = await load_viewer(db, current_user)
    await _reconcile_before_approval(db, viewer, bonus_id)
    with _http_errors():
        bonus = await payroll_bonuses.approve_bonus(
            db, viewer, bonus_id, today=business_today()
        )
    return await _bonus_response(db, bonus, viewer)


@router.post("/bonuses/approve-batch")
async def approve_bonuses(
    payload: BonusBatchIn,
    current_user: PayrollAdmin,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """„Zatwierdź zaznaczone” (Płace): wszystko albo nic.

    Każda premia przechodzi tę samą ścieżkę co pojedyncze „Zatwierdź”
    (``payroll_bonuses.approve_bonus``: zakres, autor propozycji, termin,
    otwarty miesiąc, dzwonek osobie) w jednej transakcji żądania. Pierwsza
    odmowa cofa całość i mówi, przy czyjej premii — nikt nie dostaje dzwonka
    o premii, która nie weszła. Uzgodnienie kontraktów biegnie wcześniej
    i zostaje (jak przy pojedynczym zatwierdzeniu). Kolejność id rosnąca —
    blokady wierszy zawsze w tym samym porządku.
    """

    viewer = await load_viewer(db, current_user)
    ids = sorted(set(payload.ids))
    for bonus_id in ids:
        await _reconcile_before_approval(db, viewer, bonus_id)
    today = business_today()
    approved: list[HrBonus] = []
    for bonus_id in ids:
        try:
            approved.append(
                await payroll_bonuses.approve_bonus(db, viewer, bonus_id, today=today)
            )
        except PayrollError as exc:
            await db.rollback()
            who = await db.scalar(
                select(User.name)
                .join(HrBonus, HrBonus.recipient_user_id == User.id)
                .where(HrBonus.id == bonus_id)
            )
            prefix = (
                f"Nic nie zatwierdzono — premia: {who}. "
                if who
                else ("Nic nie zatwierdzono. ")
            )
            raise HTTPException(exc.status_code, prefix + exc.message) from exc
    items = [await _bonus_response(db, bonus, viewer) for bonus in approved]
    return {"approved": len(items), "items": items}


async def _reconcile_before_approval(
    db: AsyncSession, viewer: PayrollViewer, bonus_id: int
) -> None:
    """Propozycja z placementu: uzgodnij kontrakt tuż przed zatwierdzeniem.

    Pętla biegnie raz dziennie — kontrakt zakończony przed terminem po porannym
    przebiegu nie może dać zatwierdzonej premii tego samego dnia. Błąd
    uzgodnienia nie blokuje decyzji (zostaje w logu).

    Najpierw zakres: uzgodnienie zapisuje i commituje, więc biegnie tylko dla
    widza, który może o tej premii zdecydować (ten sam warunek co
    ``payroll_bonuses.approve_bonus``). Obcy dostaje od serwisu 404 bez żadnego
    zapisu (audyt A2, 19.10.2026).
    """

    found = (
        await db.execute(
            select(HrBonus.contract_id, HrBonus.recipient_user_id).where(
                HrBonus.id == bonus_id,
                HrBonus.source == placement_bonuses.SOURCE,
                HrBonus.status == "proposed",
            )
        )
    ).first()
    if found is None:
        return
    contract_id, recipient_user_id = found
    if contract_id is None:
        return
    # ``manages_bonuses_of`` zawiera ``sees_person`` (Płace albo przełożony).
    if not viewer.manages_bonuses_of(recipient_user_id):
        return
    try:
        async with db.begin_nested():
            await placement_bonuses.reconcile_contract(db, contract_id)
        # Utrwalone od razu: odmowa zatwierdzenia (409) cofa transakcję żądania,
        # a anulowanie nieaktualnej propozycji ma zostać.
        await db.commit()
    except Exception as exc:  # noqa: BLE001 — decyzja Płac ważniejsza niż odświeżenie
        await db.rollback()
        # Klasa wyjątku, nie treść — DETAIL Postgresa niesie kwoty wiersza.
        logger.error(
            "[payroll] uzgodnienie kontraktu przed zatwierdzeniem premii (%s)",
            type(exc).__name__,
        )


@router.post("/bonuses/{bonus_id}/cancel")
async def cancel_bonus(
    bonus_id: int,
    payload: PayrollCancelIn,
    current_user: PayrollMember,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    viewer = await load_viewer(db, current_user)
    with _http_errors():
        bonus = await payroll_bonuses.cancel_bonus(
            db, viewer, bonus_id, note=payload.note
        )
    return await _bonus_response(db, bonus, viewer)


@router.get("/contracts/{contract_id}/bonuses")
async def contract_bonuses(
    contract_id: int, current_user: PayrollAdmin, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Karta „Premie z tego kontraktu”; kwoty tylko dla Płac (bramka trasy)."""

    viewer = await load_viewer(db, current_user)
    bonuses = list(
        await db.scalars(
            select(HrBonus)
            .where(HrBonus.contract_id == contract_id)
            .order_by(HrBonus.id)
        )
    )
    return {"items": await _bonus_list(db, bonuses, viewer, today=business_today())}


@router.get("/placement-options")
async def placement_options(
    current_user: PayrollAdmin, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Pole „Za kogo” w premii: kontrakty ze startem z ostatnich 200 dni i przyszłe."""

    return {
        "items": await bonus_decisions.placement_options(db, today=business_today())
    }


@router.get("/decisions")
async def bonus_decisions_panel(
    current_user: PayrollAdmin, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Ikona w górnym pasku: premie i vouchery czekające na decyzję Płac."""

    viewer = await load_viewer(db, current_user)
    today = business_today()
    proposals = list(
        await db.scalars(
            select(HrBonus)
            .where(HrBonus.status == "proposed")
            .order_by(HrBonus.period_year, HrBonus.period_month, HrBonus.id)
            .limit(300)
        )
    )
    items = await _bonus_list(db, proposals, viewer, today=today)
    return {
        **bonus_decisions.group_decisions(items, viewer_id=viewer.user_id),
        "vouchers": await bonus_decisions.pending_vouchers(db),
    }


@router.post("/vouchers/{winner_id}/confirm")
async def confirm_voucher(
    winner_id: int, current_user: PayrollAdmin, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Wyścig miesięczny: potwierdzenie vouchera. Bez przelewu i bez Płac."""

    viewer = await load_viewer(db, current_user)
    with _http_errors():
        return await bonus_decisions.confirm_voucher(db, viewer, winner_id)


# ── Reguły premii i automat ───────────────────────────────────────────────────


async def _rules_response(
    db: AsyncSession, rules: bonus_rules.BonusRules
) -> dict[str, Any]:
    payload = bonus_rules.rules_payload(rules)
    ids = (
        {r.user_id for r in rules.dl_hours}
        | {r.user_id for r in rules.individual_recruiters}
        | {r.dl_user_id for r in rules.extra_dl}
        | {r.recipient_user_id for r in rules.extra_dl}
    )
    names: dict[int, str] = {}
    if ids:
        names = {
            int(uid): str(name)
            for uid, name in (
                await db.execute(select(User.id, User.name).where(User.id.in_(ids)))
            ).all()
        }
    payload["dl_hours"] = [
        {**item, "name": names.get(item["user_id"])} for item in payload["dl_hours"]
    ]
    payload["individual_recruiters"] = [
        {**item, "name": names.get(item["user_id"])}
        for item in payload["individual_recruiters"]
    ]
    payload["extra_dl"] = [
        {
            **item,
            "dl_name": names.get(item["dl_user_id"]),
            "recipient_name": names.get(item["recipient_user_id"]),
        }
        for item in payload["extra_dl"]
    ]
    return payload


@router.get("/rules")
async def get_rules(
    current_user: PayrollAdmin, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return await _rules_response(db, await bonus_rules.load_rules(db))


@router.put("/rules")
async def put_rules(
    payload: RulesIn, current_user: PayrollAdmin, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    saved = await bonus_rules.load_rules(db)
    current = bonus_rules.rules_payload(saved)
    changes = payload.model_dump(exclude_unset=True, mode="json")
    merged = {**current, **changes}
    if "automation_since" in changes:
        with _http_errors():
            new_since = bonus_rules.parse_rules(
                {"automation_since": changes["automation_since"]}
            ).automation_since
        imported = await db.scalar(
            select(HrBonus.id).where(HrBonus.source == "compass_import").limit(1)
        )
        refusal = bonus_rules.automation_since_change_error(
            saved.automation_since, new_since, has_compass_imports=imported is not None
        )
        if refusal:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, refusal)
    ids = {
        int(item[key])
        for item in (merged.get("extra_dl") or [])
        for key in ("dl_user_id", "recipient_user_id")
    } | {
        int(item["user_id"])
        for key in ("dl_hours", "individual_recruiters")
        for item in (merged.get(key) or [])
    }
    if ids:
        found = set(
            await db.scalars(
                select(EmployeeProfile.user_id).where(EmployeeProfile.user_id.in_(ids))
            )
        )
        missing = ids - found
        if missing:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Reguły premii: każda wskazana osoba musi mieć kartotekę w NEXUSIE.",
            )
    with _http_errors():
        rules = await bonus_rules.save_rules(db, merged, actor_id=current_user.id)
    audit.record(
        db,
        actor_user_id=current_user.id,
        subject_user_id=None,
        entity_type="hr_bonus_rules",
        entity_id=bonus_rules.SETTING_KEY,
        action="rules_changed",
        sensitivity="payroll",
        details={"changed": sorted(changes)},
    )
    return await _rules_response(db, rules)


# ── Minimalna stawka na zleceniu (etap 2, D7) ─────────────────────────────────


def _minimum_rates_response(rates: dict[int, Decimal]) -> dict[str, Any]:
    return {
        "rates": [
            {"year": year, "hourly_rate": f"{amount:.2f}"}
            for year, amount in sorted(rates.items())
        ],
        "currency": "PLN",
    }


@router.get("/settings/minimum-rates")
async def get_minimum_rates(
    current_user: PayrollAdmin, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return _minimum_rates_response(await payroll_rates.load_minimum_rates(db))


@router.put("/settings/minimum-rates")
async def put_minimum_rates(
    payload: MinimumRatesIn,
    current_user: PayrollAdmin,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    with _http_errors():
        rates = await payroll_rates.save_minimum_rates(
            db,
            {year: str(amount) for year, amount in payload.rates.items()},
            actor_id=current_user.id,
        )
    audit.record(
        db,
        actor_user_id=current_user.id,
        subject_user_id=None,
        entity_type="hr_minimum_hourly_rates",
        entity_id=payroll_rates.MINIMUM_RATES_SETTING,
        action="minimum_rates_changed",
        sensitivity="payroll",
        details={"rates": payroll_rates.minimum_rates_payload(rates)},
    )
    return _minimum_rates_response(rates)


class SettlementRowIn(BaseModel):
    index: int = Field(ge=1)
    candidate: str = Field(max_length=500)
    amount: Decimal = Field(ge=0)
    recipient_user_id: Optional[int] = Field(default=None, ge=1)
    contract_id: Optional[int] = Field(default=None, ge=1)
    contract_label: Optional[str] = Field(default=None, max_length=500)
    role: Optional[str] = Field(default=None, max_length=16)
    keyed: bool = False
    category: str = Field(default="custom", max_length=16)


class SettlementApplyIn(BaseModel):
    rows: list[SettlementRowIn] = Field(
        min_length=1, max_length=settlement_import.MAX_ROWS
    )
    as_proposal: bool = False


@router.post("/months/{year}/{month}/settlement-import/preview")
async def preview_settlement_import(
    year: int,
    month: int,
    current_user: PayrollAdmin,
    db: AsyncSession = Depends(get_db),
    file: UploadFile = File(...),
) -> dict[str, Any]:
    """Porównanie arkusza z NEXUSEM; plik nie jest zapisywany, nic się nie zmienia."""

    viewer = await load_viewer(db, current_user)
    with _http_errors():
        payroll_periods.validate_period(year, month)
        content = await file.read(settlement_import.MAX_FILE_BYTES + 1)
        return await settlement_import.build_preview(
            db, viewer, content, year=year, month=month
        )


@router.post("/months/{year}/{month}/settlement-import")
async def apply_settlement_import(
    year: int,
    month: int,
    payload: SettlementApplyIn,
    current_user: PayrollAdmin,
    db: AsyncSession = Depends(get_db),
) -> dict[str, int]:
    viewer = await load_viewer(db, current_user)
    with _http_errors():
        return await settlement_import.apply_rows(
            db,
            viewer,
            [row.model_dump() for row in payload.rows],
            year=year,
            month=month,
            as_proposal=payload.as_proposal,
        )


@router.post("/proposals/refresh")
async def refresh_proposals(
    current_user: PayrollAdmin, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Przelicza propozycje teraz (to samo, co dzienna pętla)."""

    loaded = await hr_modules.load_modules(db)
    if not loaded.get(MODULE):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Automat premii działa po włączeniu modułu Płac.",
        )
    return await payroll_jobs.refresh_proposals(db, today=business_today())


__all__ = ["router"]
