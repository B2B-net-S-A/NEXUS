"""Liczniki zakładek „Ludzi” (17.10.2026) — ``GET /api/hr/counts``.

Kadrowe typy powiadomień nie mają ikony w pasku (decyzja „jedna ikona = jeden
temat”, ``docs/claude/powiadomienia/pasek-tematy-bez-dzwonka.md``), więc
trwałym miejscem spraw, na które ktoś czeka, są ekrany „Ludzi”: zakładka
„Akceptacje” pokazuje, ile wniosków i timesheetów czeka na decyzję
czytającego, a „Sprawy” — ile otwartych spraw administracja@ ma przypisanych.

Liczą te same reguły co ekrany — zapytanie kolejki wniosków
(``leave_service.pending_count`` = ``count()`` na tym samym zapytaniu co
``pending_queue``; zgłoszenia z B2B i zlecenia się nie liczą, D5)
i akceptujący timesheetu ``time_access.Actor.can_approve`` — żeby licznik
nie rozjechał się z listą.
``null`` = liczba tej osoby nie dotyczy (moduł wyłączony, brak dostępu do
Spraw). Awaria odczytu to błąd żądania, a nie zero — front nie pokazuje
wtedy liczby.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.hr_gates import HrConfigReader
from app.core.database import get_db
from app.core.scheduling import business_today
from app.models.admin_case import AdminCase
from app.models.hr_profile import EmployeeProfile
from app.models.hr_time import Timesheet
from app.models.user import User
from app.services.admin_cases import service as cases_service
from app.services.admin_cases_schema import TERMINAL_STATUSES
from app.services.hr import leave_service, time_access
from app.services.hr import modules as hr_modules
from app.services.hr.modules import HrModule

router = APIRouter()


async def _timesheets_waiting(db: AsyncSession, user: User) -> int:
    """Wysłane timesheety (każdy miesiąc), które ta osoba może zaakceptować."""

    actor = await time_access.load_actor(db, user)
    profiles = await db.scalars(
        select(EmployeeProfile)
        .join(Timesheet, Timesheet.user_id == EmployeeProfile.user_id)
        .where(
            Timesheet.status == "submitted",
            Timesheet.payroll_locked.is_(False),
            Timesheet.user_id != user.id,
        )
    )
    return sum(1 for profile in profiles if actor.can_approve(profile))


async def _open_cases(db: AsyncSession, user: User) -> Optional[int]:
    """Otwarte sprawy przypisane do osoby; ``None`` bez dostępu do Spraw."""

    if not (
        cases_service.is_handler(user)
        or await cases_service.has_assigned_cases(db, user.id)
    ):
        return None
    total = await db.scalar(
        select(func.count(AdminCase.id)).where(
            AdminCase.assignee_user_id == user.id,
            AdminCase.status.not_in(TERMINAL_STATUSES),
        )
    )
    return int(total or 0)


@router.get("")
async def hr_counts(
    current_user: HrConfigReader, db: AsyncSession = Depends(get_db)
) -> dict:
    loaded = await hr_modules.load_modules(db)

    def is_open(key: str) -> bool:
        return hr_modules.module_open_for(current_user, loaded, key)

    approvals: Optional[int] = None
    if is_open(HrModule.leave):
        # Sam `count()` na tym samym zapytaniu co lista (bez kontekstu wierszy).
        approvals = await leave_service.pending_count(
            db, actor=current_user, today=business_today()
        )
    if is_open(HrModule.time):
        approvals = (approvals or 0) + await _timesheets_waiting(db, current_user)
    return {
        "approvals": approvals,
        "cases": await _open_cases(db, current_user)
        if is_open(HrModule.cases)
        else None,
    }
