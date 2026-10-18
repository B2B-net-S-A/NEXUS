"""Nieobecności w API v1: kto i kiedy jest nieobecny (odczyt).

Scope ``absences:read``. Nieobecność = zatwierdzony wniosek urlopowy; dni to
dni robocze wniosku (``leave_request_days``: kalendarz firmy bez weekendów
i świąt, pół dnia = 0.5). Rodzaju nieobecności, notatki, zastępcy ani treści
autoodpowiedzi nie ma w żadnym polu — decyzja D6 (16.10.2026): rodzaj widzą
tylko osoba, jej przełożony i Kadry. Wyłączony moduł „Urlopy” = 404
``module_disabled``, jak na ekranach.

Zdarzenia ``leave.approved`` i ``leave.cancelled`` (``services/integration_events``)
niosą ``leave_request_id`` — szczegóły daje ``GET /absences/{request_id}``.

Moduł NIE MOŻE mieć ``from __future__ import annotations`` (slowapi #579).
"""

import uuid
from datetime import date, datetime
from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Caller, require_service_scope
from app.api.hr_gates import MODULE_DISABLED_DETAIL
from app.api.integrations_v1.common import (
    IntegrationRoute,
    Page,
    PageQuery,
    PageSizeQuery,
    page_of,
    principal_rate_key,
    read_rate_limit,
)
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.models.hr_leave import LeaveRequest, LeaveRequestDay
from app.models.service_account import ServiceScope
from app.models.user import User
from app.services.hr import modules as hr_modules

router = APIRouter(route_class=IntegrationRoute)

AbsencesRead = Annotated[
    Caller,
    Depends(require_service_scope(ServiceScope.absences_read, allow_admin_jwt=False)),
]

MODULE = "leave"
#: Najdłuższy zakres listy (dni kalendarzowe, z obu końcami) — kwartał.
MAX_RANGE_DAYS = 93
_APPROVED = "approved"
_NOT_FOUND = "Nieobecność nie istnieje."


async def require_module(db: AsyncSession, key: str) -> None:
    """Wyłączony moduł HR = 404 ``module_disabled`` (klucz nie ma wyjątku admina)."""
    if not (await hr_modules.load_modules(db)).get(key):
        raise HTTPException(
            404, detail={"error": "module_disabled", "message": MODULE_DISABLED_DETAIL}
        )


# ── Modele odpowiedzi ────────────────────────────────────────────────────────


class AbsenceDayOut(BaseModel):
    date: date
    fraction: float = Field(description="1.0 — cały dzień, 0.5 — pół dnia.")
    request_id: uuid.UUID = Field(description="Wniosek, z którego jest ten dzień.")


class AbsentPersonOut(BaseModel):
    user_id: int
    name: Optional[str]
    days_total: float = Field(description="Suma dni roboczych w zakresie.")
    days: list[AbsenceDayOut] = Field(
        description="Dni robocze nieobecności w zakresie, rosnąco."
    )


class AbsenceRequestDayOut(BaseModel):
    date: date
    fraction: float


class AbsenceRequestOut(BaseModel):
    request_id: uuid.UUID
    user_id: int
    name: Optional[str]
    status: Literal["approved", "cancelled"] = Field(
        description="cancelled — zatwierdzona nieobecność, którą anulowano."
    )
    start_date: date
    end_date: date
    half_day: Optional[Literal["morning", "afternoon"]]
    days_total: float
    days: list[AbsenceRequestDayOut] = Field(
        description="Dni robocze wniosku (przy anulowanym — te, które były zajęte)."
    )
    decided_at: Optional[datetime]
    updated_at: datetime


# ── Trasy ────────────────────────────────────────────────────────────────────


def _range_or_422(date_from: date, date_to: date) -> None:
    if date_to < date_from:
        raise HTTPException(
            422,
            detail={
                "error": "invalid_period",
                "message": "`to` nie może być przed `from`.",
            },
        )
    if (date_to - date_from).days + 1 > MAX_RANGE_DAYS:
        raise HTTPException(
            422,
            detail={
                "error": "invalid_period",
                "message": f"Zakres najwyżej {MAX_RANGE_DAYS} dni.",
            },
        )


@router.get(
    "/absences",
    response_model=Page[AbsentPersonOut],
    summary="Kto jest nieobecny w zakresie dat (bez rodzaju nieobecności)",
)
@limiter.limit(read_rate_limit, key_func=principal_rate_key)
async def list_absences(
    request: Request,
    _caller: AbsencesRead,
    db: AsyncSession = Depends(get_db),
    date_from: date = Query(
        ..., alias="from", description="Pierwszy dzień zakresu (włącznie)."
    ),
    date_to: date = Query(
        ...,
        alias="to",
        description=f"Ostatni dzień zakresu (włącznie, najwyżej {MAX_RANGE_DAYS} dni).",
    ),
    page: PageQuery = 1,
    page_size: PageSizeQuery = 100,
):
    """Osoby z zatwierdzoną nieobecnością w zakresie, po imieniu i nazwisku:
    dni robocze (cały dzień albo pół) z identyfikatorem wniosku. Bez rodzaju
    nieobecności, notatki i zastępcy."""
    _range_or_422(date_from, date_to)
    await require_module(db, MODULE)
    in_range = (
        LeaveRequestDay.day >= date_from,
        LeaveRequestDay.day <= date_to,
        LeaveRequestDay.active.is_(True),
        LeaveRequest.status == _APPROVED,
    )
    absent = (
        select(LeaveRequestDay.user_id)
        .join(LeaveRequest, LeaveRequest.id == LeaveRequestDay.leave_request_id)
        .where(*in_range)
        .distinct()
    )
    total = int(
        await db.scalar(select(func.count()).select_from(absent.subquery())) or 0
    )
    people = (
        await db.execute(
            select(User.id, User.name)
            .where(User.id.in_(absent))
            .order_by(User.name, User.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    ids = [user_id for user_id, _ in people]
    days: dict[int, list[AbsenceDayOut]] = {user_id: [] for user_id in ids}
    if ids:
        rows = await db.execute(
            select(
                LeaveRequestDay.user_id,
                LeaveRequestDay.day,
                LeaveRequestDay.fraction,
                LeaveRequestDay.leave_request_id,
            )
            .join(LeaveRequest, LeaveRequest.id == LeaveRequestDay.leave_request_id)
            .where(LeaveRequestDay.user_id.in_(ids), *in_range)
            .order_by(LeaveRequestDay.user_id, LeaveRequestDay.day)
        )
        for user_id, day, fraction, request_id in rows.all():
            days[user_id].append(
                AbsenceDayOut(date=day, fraction=float(fraction), request_id=request_id)
            )
    items = [
        AbsentPersonOut(
            user_id=user_id,
            name=name,
            days_total=sum(day.fraction for day in days[user_id]),
            days=days[user_id],
        )
        for user_id, name in people
    ]
    return page_of(items, page=page, page_size=page_size, total=total)


@router.get(
    "/absences/{request_id}",
    response_model=AbsenceRequestOut,
    summary="Nieobecność (wniosek zatwierdzony albo anulowany po zatwierdzeniu)",
)
@limiter.limit(read_rate_limit, key_func=principal_rate_key)
async def get_absence(
    request: Request,
    request_id: uuid.UUID,
    _caller: AbsencesRead,
    db: AsyncSession = Depends(get_db),
) -> AbsenceRequestOut:
    """Osoba, okres i dni robocze wniosku. Wniosek oczekujący, odrzucony albo
    anulowany przed decyzją nie był nieobecnością — 404. Bez rodzaju
    nieobecności, notatki i zastępcy."""
    await require_module(db, MODULE)
    row = (
        await db.execute(
            select(
                LeaveRequest.id,
                LeaveRequest.user_id,
                LeaveRequest.status,
                LeaveRequest.start_date,
                LeaveRequest.end_date,
                LeaveRequest.half_day,
                LeaveRequest.decided_at,
                LeaveRequest.updated_at,
                User.name,
            )
            .join(User, User.id == LeaveRequest.user_id)
            .where(LeaveRequest.id == request_id)
        )
    ).first()
    was_absence = row is not None and (
        row.status == _APPROVED
        or (row.status == "cancelled" and row.decided_at is not None)
    )
    if not was_absence:
        raise HTTPException(404, detail=_NOT_FOUND)
    days = [
        AbsenceRequestDayOut(date=day, fraction=float(fraction))
        for day, fraction in (
            await db.execute(
                select(LeaveRequestDay.day, LeaveRequestDay.fraction)
                .where(LeaveRequestDay.leave_request_id == request_id)
                .order_by(LeaveRequestDay.day)
            )
        ).all()
    ]
    return AbsenceRequestOut(
        request_id=row.id,
        user_id=row.user_id,
        name=row.name,
        status=row.status,
        start_date=row.start_date,
        end_date=row.end_date,
        half_day=row.half_day,
        days_total=sum(day.fraction for day in days),
        days=days,
        decided_at=row.decided_at,
        updated_at=row.updated_at,
    )
