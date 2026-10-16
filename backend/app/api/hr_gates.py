"""Bramki tras „Ludzi w NEXUSIE”.

Moduł kadrowy nie ma własnej sekcji produktu (sekcje opisują pracę
rekrutacyjną). O dostępie decydują:

* **kartoteka** — osoba zatrudniona w firmie (``employee_profiles``, status
  inny niż ``exited``) widzi swój czas i katalog ludzi,
* **uprawnienia z grupy „Ludzie”** — Kadry, Płace, Sprzęt, Sprawy (ekran
  Osoby i role); admin ma wszystkie,
* **przełącznik modułu** (``app_settings['hr_modules']``) — wyłączony moduł
  odpowiada 404 każdemu poza adminem.

Nazwy fabryk zaczynają się od ``require_hr_`` — test kontraktu tras
(``tests/test_route_authz_contract.py``) rozpoznaje je jako bramki.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_onboarded_user, require_permission
from app.core.database import get_db
from app.models.user import User, UserRole
from app.services.action_permissions import ProductAction, has_permission
from app.services.hr import modules as hr_modules
from app.services.hr import people

MODULE_DISABLED_DETAIL = "Ten moduł nie jest jeszcze włączony."
NO_PROFILE_DETAIL = (
    "Nie masz kartoteki pracownika w NEXUSIE — poproś Kadry o jej założenie."
)

#: Uprawnienia, z którymi konto bez kartoteki i tak czyta katalog ludzi.
_DIRECTORY_PERMISSIONS = (
    ProductAction.people_admin,
    ProductAction.payroll,
    ProductAction.equipment,
    ProductAction.cases,
)


def require_hr_config_reader():
    """Każde zalogowane konto po onboardingu (stan modułów i własne prawa)."""

    async def _check(current_user: User = Depends(require_onboarded_user)) -> User:
        return current_user

    return _check


async def _ensure_module(db: AsyncSession, user: User, module: str) -> None:
    loaded = await hr_modules.load_modules(db)
    if not hr_modules.module_open_for(user, loaded, module):
        raise HTTPException(status.HTTP_404_NOT_FOUND, MODULE_DISABLED_DETAIL)


def require_hr_people_reader(module: str = "people"):
    """Katalog ludzi: osoba z kartoteką albo z uprawnieniem z grupy „Ludzie”."""

    async def _check(
        current_user: User = Depends(require_onboarded_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        await _ensure_module(db, current_user, module)
        if current_user.has_role(UserRole.admin):
            return current_user
        if any(has_permission(current_user, p) for p in _DIRECTORY_PERMISSIONS):
            return current_user
        if await people.has_live_profile(db, current_user.id):
            return current_user
        raise HTTPException(status.HTTP_403_FORBIDDEN, NO_PROFILE_DETAIL)

    return _check


def require_hr_self_service(module: str):
    """Samoobsługa („Mój czas”): wyłącznie osoba z żywą kartoteką."""

    async def _check(
        current_user: User = Depends(require_onboarded_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        await _ensure_module(db, current_user, module)
        if not await people.has_live_profile(db, current_user.id):
            raise HTTPException(status.HTTP_403_FORBIDDEN, NO_PROFILE_DETAIL)
        return current_user

    return _check


HrConfigReader = Annotated[User, Depends(require_hr_config_reader())]
HrPeopleReader = Annotated[User, Depends(require_hr_people_reader())]
HrPeopleAdmin = Annotated[User, Depends(require_permission(ProductAction.people_admin))]
