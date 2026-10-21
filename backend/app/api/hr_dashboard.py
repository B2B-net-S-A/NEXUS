"""Dane kafelków pulpitu „Ludzi w NEXUSIE”, których nie dają inne trasy.

Prefiks ``/api/hr/dashboard`` (wpięty w ``app/main.py``). Kafelki „Mój czas”,
„Do akceptacji” i „Sprzęt do zrobienia” czytają istniejące trasy modułów
(``/api/hr/leave``, ``/api/hr/time``, ``/api/equipment``); tu jest tylko
„W zastępstwie”, bo zastępstwa liczy silnik dostępności, a nie moduł urlopów.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_onboarded_user
from app.api.hr_gates import ensure_module
from app.core.database import get_db
from app.models.user import User, UserRole
from app.services.hr.modules import HrModule
from app.services.hr.substitution_summary import substitution_summary

router = APIRouter()

#: Zastępstwa wynikają z urlopów — kafelek żyje razem z modułem urlopów.
MODULE = HrModule.leave
STAFF_DETAIL = "Zastępstwa widzą pracownicy firmy."
#: Konta, które nie są ludźmi zatrudnionymi w firmie (jak „Nieobecni dziś”).
_NOT_STAFF = {UserRole.automation, UserRole.user, UserRole.board}


def require_hr_substitution_reader():
    """Pracownik firmy (bez kont technicznych i podglądu) przy otwartym module."""

    async def _check(
        current_user: User = Depends(require_onboarded_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        await ensure_module(db, current_user, MODULE)
        if current_user.has_role(UserRole.admin):
            return current_user
        if not set(current_user.get_all_roles()) - _NOT_STAFF:
            raise HTTPException(status.HTTP_403_FORBIDDEN, STAFF_DETAIL)
        return current_user

    return _check


SubstitutionReader = Annotated[User, Depends(require_hr_substitution_reader())]


@router.get("/substitution")
async def my_substitution(
    current_user: SubstitutionReader, db: AsyncSession = Depends(get_db)
) -> dict:
    """Za kogo osoba dziś pracuje i ile pracy przejęła; ostrzeżenia zastępstw."""

    return await substitution_summary(db, viewer=current_user)
