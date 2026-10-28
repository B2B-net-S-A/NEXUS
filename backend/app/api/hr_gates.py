"""Bramki tras „Ludzi w NEXUSIE”.

Moduł kadrowy nie ma własnej sekcji produktu (sekcje opisują pracę
rekrutacyjną). O dostępie decydują:

* **kartoteka** — osoba zatrudniona w firmie (``employee_profiles``, status
  inny niż ``exited``) widzi swój czas i katalog ludzi,
* **uprawnienia z grupy „Ludzie”** — Kadry, Płace, Sprzęt, Sprawy, Raporty
  godzin (ekran Osoby i role); admin ma wszystkie,
* **przełącznik modułu** (``app_settings['hr_modules']``) — wyłączony moduł
  odpowiada 404 każdemu poza adminem.

Nazwy fabryk zaczynają się od ``require_hr_`` — test kontraktu tras
(``tests/test_route_authz_contract.py``) rozpoznaje je jako bramki.
"""

from __future__ import annotations

from collections.abc import Iterable
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
SELF_EDIT_DETAIL = (
    "Swojej kartoteki i puli urlopowej nie zmieniasz sam — poproś inną osobę "
    "z Kadr albo admina."
)
NO_PROFILE_DETAIL = "Nie masz kartoteki w NEXUSIE — poproś Kadry o jej założenie."

#: Uprawnienia, z którymi konto bez kartoteki i tak czyta katalog ludzi.
_DIRECTORY_PERMISSIONS = (
    ProductAction.people_admin,
    ProductAction.payroll,
    ProductAction.equipment,
    ProductAction.cases,
    ProductAction.timesheets,
)


def require_hr_config_reader():
    """Każde zalogowane konto po onboardingu (stan modułów i własne prawa)."""

    async def _check(current_user: User = Depends(require_onboarded_user)) -> User:
        return current_user

    return _check


async def ensure_module(db: AsyncSession, user: User, module: str) -> None:
    """Wyłączony moduł = 404 z ``MODULE_DISABLED_DETAIL``; admin przechodzi (poza
    ``hr_modules.NO_ADMIN_PREVIEW`` — „Zgody” od 21.10.2026).

    Jedno sprawdzenie dla bramek wszystkich modułów „Ludzi” (``HrModule``).
    """

    loaded = await hr_modules.load_modules(db)
    if not hr_modules.module_open_for(user, loaded, module):
        raise HTTPException(status.HTTP_404_NOT_FOUND, MODULE_DISABLED_DETAIL)


def require_hr_people_reader(module: str = "people"):
    """Katalog ludzi: osoba z kartoteką albo z uprawnieniem z grupy „Ludzie”."""

    async def _check(
        current_user: User = Depends(require_onboarded_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        await ensure_module(db, current_user, module)
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
        await ensure_module(db, current_user, module)
        if not await people.has_live_profile(db, current_user.id):
            raise HTTPException(status.HTTP_403_FORBIDDEN, NO_PROFILE_DETAIL)
        return current_user

    return _check


def require_hr_approvals():
    """Zgody na wydatki i premie poza umową (0483): każde konto po onboardingu
    przy włączonym module. Kto co widzi i o czym decyduje — serwis zgód."""

    async def _check(
        current_user: User = Depends(require_onboarded_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        await ensure_module(db, current_user, hr_modules.HrModule.approvals)
        return current_user

    return _check


def require_hr_approvals_admin():
    """Zasady zgód (progi, zatwierdzający) ustawia admin."""

    async def _check(current_user: User = Depends(require_hr_approvals())) -> User:
        if not current_user.has_role(UserRole.admin):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Zasady zgód ustawia admin.")
        return current_user

    return _check


HrConfigReader = Annotated[User, Depends(require_hr_config_reader())]
HrPeopleReader = Annotated[User, Depends(require_hr_people_reader())]


def require_hr_people_admin():
    """Kadry (uprawnienie „Kadry”; admin ma je zawsze) — nazwana bramka modułu."""

    gate = require_permission(ProductAction.people_admin)

    async def _check(user: User = Depends(gate)) -> User:
        return user

    return _check


HrPeopleAdmin = Annotated[User, Depends(require_hr_people_admin())]


def require_hr_people_records():
    """Kadry albo Finanse (Płace); admin ma oba (19.10.2026).

    Lista rozjazdów konto ↔ kartoteka z „Wyrównaj wg konta” i zapis formy
    umowy — formę zmieniają admin, Finanse i Kadry (Kadry bez Płac jej nie
    widzą). Bez czekania na przełącznik modułu, jak trasy Kadr.
    """

    async def _check(current_user: User = Depends(require_onboarded_user)) -> User:
        if current_user.has_role(UserRole.admin) or any(
            has_permission(current_user, permission)
            for permission in (ProductAction.people_admin, ProductAction.payroll)
        ):
            return current_user
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Kartoteki zmieniają Kadry i Finanse.",
        )

    return _check


HrPeopleRecords = Annotated[User, Depends(require_hr_people_records())]


def refuse_self_edit(actor: User, user_ids: Iterable[int]) -> None:
    """„Nie sobie” dla kartoteki i puli urlopowej (decyzja Artura 19.10.2026).

    Ten sam guard co przy premiach, umowach i rozliczeniach: Kadry (i Finanse
    przy formie umowy) nie zmieniają własnej kartoteki — przełożonego, formy,
    statusu, puli, „składa raport godzin”. Admin przechodzi (zarząd prowadzi
    też własną kartotekę); ślad i tak zostaje w ``hr_audit_events``.
    """

    if actor.has_role(UserRole.admin):
        return
    if actor.id in set(user_ids):
        raise HTTPException(status.HTTP_403_FORBIDDEN, SELF_EDIT_DETAIL)
