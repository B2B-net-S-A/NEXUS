"""Sprzedaż → KPI tygodniowe handlowców i cele (prefiks ``/api/sales/kpi``).

Odczyt KPI: „Sprzedaż: podgląd” (jak w Atlasie widział je cały zespół
sprzedaży). Cele wpisuje administrator — trasa ma bramkę „Sprzedaż: edycja”,
a handler sprawdza rolę admina (wzorzec ``/owner-labels/assign``). Definicje
liczb: ``services/sales/kpi.py``.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.sales_gates import SalesEditUser, SalesViewUser, is_admin
from app.core.database import get_db
from app.core.scheduling import business_today
from app.models.sales import SalesTarget
from app.models.user import User
from app.services.action_permissions import ProductAction, has_permission
from app.services.effective_access import resolve_effective_access
from app.services.sales.kpi import METRICS, build_kpi

router = APIRouter()

ADMIN_ONLY_DETAIL = "Cele sprzedaży ustawia administrator."


class CellOut(BaseModel):
    actual: int
    target: int
    light: Optional[str]


class WeekOut(BaseModel):
    start: date
    iso_year: int
    iso_week: int


class PersonOut(BaseModel):
    user_id: int
    name: str
    team: Optional[str]
    has_targets: bool
    targets: dict[str, int]
    weeks: list[dict[str, CellOut]]
    margin_goal_amount: Optional[Decimal]
    margin_goal_deadline: Optional[date]
    margin_actual: Decimal


class MonthOut(BaseModel):
    month: date
    net_mrr: Decimal
    cum_net_mrr: Decimal


class CompanyOut(BaseModel):
    net_mrr_goal: Optional[Decimal]
    goal_deadline: Optional[date]
    won_net_mrr: Decimal
    missing_margin: int
    months: list[MonthOut]


class KpiOut(BaseModel):
    weeks: list[WeekOut]
    people: list[PersonOut]
    company: CompanyOut
    offers_history_since: Optional[date]


@router.get("", response_model=KpiOut)
async def sales_kpi(
    current_user: SalesViewUser,
    db: AsyncSession = Depends(get_db),
    weeks: int = Query(8, ge=1, le=26),
) -> KpiOut:
    """Spotkania, leady i wejścia na etap oferty per osoba w ostatnich tygodniach."""

    kpi = await build_kpi(db, today=business_today(), weeks=weeks)
    return KpiOut(
        weeks=[
            WeekOut(
                start=monday,
                iso_year=monday.isocalendar().year,
                iso_week=monday.isocalendar().week,
            )
            for monday in kpi.weeks
        ],
        people=[
            PersonOut(
                user_id=p.user_id,
                name=p.name,
                team=p.team,
                has_targets=p.has_targets,
                targets=p.targets,
                weeks=[
                    {
                        metric: CellOut(
                            actual=cell.actual, target=cell.target, light=cell.light
                        )
                        for metric, cell in week.items()
                    }
                    for week in p.weeks
                ],
                margin_goal_amount=p.margin_goal_amount,
                margin_goal_deadline=p.margin_goal_deadline,
                margin_actual=p.margin_actual,
            )
            for p in kpi.people
        ],
        company=CompanyOut(
            net_mrr_goal=kpi.company.net_mrr_goal,
            goal_deadline=kpi.company.goal_deadline,
            won_net_mrr=kpi.company.won_net_mrr,
            missing_margin=kpi.company.missing_margin,
            months=[
                MonthOut(month=m.month, net_mrr=m.net_mrr, cum_net_mrr=m.cum_net_mrr)
                for m in kpi.company.months
            ],
        ),
        offers_history_since=kpi.offers_history_since,
    )


# ── Cele (admin) ─────────────────────────────────────────────────────────


class PersonTargetIn(BaseModel):
    meetings: int = Field(ge=0, le=1000)
    qualified: int = Field(ge=0, le=1000)
    offers_stage: int = Field(ge=0, le=1000)
    margin_goal_amount: Optional[Decimal] = Field(
        default=None, ge=0, max_digits=14, decimal_places=2
    )
    margin_goal_deadline: Optional[date] = None
    team: Optional[str] = Field(default=None, max_length=60)

    @field_validator("team")
    @classmethod
    def _blank_team_is_none(cls, value: Optional[str]) -> Optional[str]:
        return (value or "").strip() or None


class CompanyTargetIn(BaseModel):
    net_mrr_goal: Optional[Decimal] = Field(
        default=None, ge=0, max_digits=14, decimal_places=2
    )
    goal_deadline: Optional[date] = None


class PersonTargetOut(BaseModel):
    user_id: int
    name: str
    is_active: bool
    has_targets: bool
    meetings: int
    qualified: int
    offers_stage: int
    margin_goal_amount: Optional[Decimal]
    margin_goal_deadline: Optional[date]
    team: Optional[str]


class TargetsOut(BaseModel):
    company: CompanyTargetIn
    people: list[PersonTargetOut]


def _ensure_admin(user: User) -> None:
    if not is_admin(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=ADMIN_ONLY_DETAIL)


def _person_out(user: User, row: Optional[SalesTarget]) -> PersonTargetOut:
    return PersonTargetOut(
        user_id=user.id,
        name=user.name,
        is_active=user.is_active,
        has_targets=row is not None,
        meetings=row.meetings if row else 0,
        qualified=row.qualified if row else 0,
        offers_stage=row.offers_stage if row else 0,
        margin_goal_amount=row.margin_goal_amount if row else None,
        margin_goal_deadline=row.margin_goal_deadline if row else None,
        team=row.team if row else None,
    )


@router.get("/targets", response_model=TargetsOut)
async def list_targets(
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> TargetsOut:
    """Cel firmy i osoby, którym można ustawić cele: z „Sprzedaż: edycja” albo już z celem."""

    _ensure_admin(current_user)
    rows = list((await db.execute(select(SalesTarget))).scalars())
    company = next((r for r in rows if r.user_id is None), None)
    by_user = {r.user_id: r for r in rows if r.user_id is not None}

    active = list(
        (await db.execute(select(User).where(User.is_active.is_(True)))).scalars()
    )
    await resolve_effective_access(db, active)
    users = {u.id: u for u in active if has_permission(u, ProductAction.sales_edit)}
    missing = set(by_user) - set(users)
    if missing:
        for user in (
            await db.execute(select(User).where(User.id.in_(missing)))
        ).scalars():
            users[user.id] = user

    people = sorted(
        (_person_out(user, by_user.get(user.id)) for user in users.values()),
        key=lambda p: (not p.has_targets, p.name),
    )
    return TargetsOut(
        company=CompanyTargetIn(
            net_mrr_goal=company.margin_goal_amount if company else None,
            goal_deadline=company.margin_goal_deadline if company else None,
        ),
        people=people,
    )


@router.put("/targets/company", response_model=CompanyTargetIn)
async def set_company_target(
    payload: CompanyTargetIn,
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> CompanyTargetIn:
    _ensure_admin(current_user)
    row = (
        await db.execute(select(SalesTarget).where(SalesTarget.user_id.is_(None)))
    ).scalar_one_or_none()
    if row is None:
        row = SalesTarget(user_id=None)
        db.add(row)
    row.margin_goal_amount = payload.net_mrr_goal
    row.margin_goal_deadline = payload.goal_deadline
    row.updated_by_user_id = current_user.id
    await db.commit()
    return payload


@router.put("/targets/{user_id}", response_model=PersonTargetOut)
async def set_person_target(
    user_id: int,
    payload: PersonTargetIn,
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> PersonTargetOut:
    _ensure_admin(current_user)
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Nie ma takiej osoby.")
    row = (
        await db.execute(select(SalesTarget).where(SalesTarget.user_id == user_id))
    ).scalar_one_or_none()
    if row is None:
        row = SalesTarget(user_id=user_id)
        db.add(row)
    for metric in METRICS:
        setattr(row, metric, getattr(payload, metric))
    row.margin_goal_amount = payload.margin_goal_amount
    row.margin_goal_deadline = payload.margin_goal_deadline
    row.team = payload.team
    row.updated_by_user_id = current_user.id
    await db.commit()
    await db.refresh(row)
    return _person_out(user, row)


@router.delete("/targets/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_person_target(
    user_id: int,
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Zdejmij osobę z tabeli celów (wyniki z jej szans dalej się liczą)."""

    _ensure_admin(current_user)
    row = (
        await db.execute(select(SalesTarget).where(SalesTarget.user_id == user_id))
    ).scalar_one_or_none()
    if row is not None:
        await db.delete(row)
        await db.commit()
