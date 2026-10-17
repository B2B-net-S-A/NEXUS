"""Bramki tras opieki (``/api/care``): ``contract_care``, ``care_skills``, ``care_atlas``.

Dostęp (decyzja D7 i zadanie E5, 16.10.2026):

* **odczyt** — sekcja Delivery i „Klienci, kontrakty i zamówienia: podgląd”
  (``DeliveryViewUser``); Delivery Lead tylko u swoich klientów (cudzy → 403),
* **zapis** (opiekun, rozmowy, karty, przepięcia, notatki o stacku) — dodatkowo
  rola Delivery Lead, Talent Community Manager albo admin: opieka to praca
  z ludźmi, a nie uprawnienie z ekranu kontraktów,
* **kolejka technologii** — czytają ją też osoby od słownika umiejętności
  (Head of Recruitment); decyzje: admin, Head of Recruitment, TCM,
* **ATLAS** — klucz konta serwisowego (``X-API-Key``) z ``clients:read``
  i ``contracts:read`` (najbliższe istniejące zakresy; własnego zakresu
  sygnałów nie ma), zwrot statusów — na razie tylko admin.
* **Rytm kontaktu i przydział opiekunów** (etap 3, O8 i O10, 17.10.2026) —
  rytm czytają czytelnicy opieki, a zmienia go opiekun kontraktu, DL klienta,
  head back office i admin (sprawdza serwis ``care/cadence`` per kontrakt);
  przydział wielu konsultantów naraz i próg obciążenia — head back office
  (``app_settings['hr_divisions']``) i admin (``require_hr_care_assigner``).
  DL zmienia opiekuna pojedynczo u swoich klientów jak dotąd. Head back
  office to dowolne konto (``hr/structure.py``), więc „Konsultanci”, rytm
  i „Przydział” (``require_hr_care_rhythm_reader``, ``CareAssigner``)
  przepuszczają go także bez sekcji i podglądu Delivery — z zakresem
  wszystkich klientów (``care_access.rhythm_scope``); reszta jak odczyt.
* **Struktura u klienta i opinie klienta** (etap 2, D8–D11, 17.10.2026) —
  czytają opiekun (DL, TCM, admin) i Head of Recruitment; Finanse i Kadry
  z samego uprawnienia nie (D11). Opinię zapisują piszący opiekę, a „Podlega
  pod” i dział kontaktu — ci, którzy edytują kontakty klienta
  (``ClientAccess.can_edit_contacts``, ta sama reguła co ``api/contacts.py``).

Nazwy fabryk zaczynają się od ``require_hr_`` — test kontraktu tras
(``tests/test_route_authz_contract.py``) rozpoznaje je jako bramki.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    Caller,
    require_onboarded_user,
    require_permission_or_roles,
    require_roles,
    require_service_scope,
)
from app.api.hr_gates import MODULE_DISABLED_DETAIL, ensure_module
from app.api.permission_access import ClientsEditUser, DeliveryViewUser
from app.api.section_access import (
    require_section_access,
    require_section_access_any,
    require_section_access_any_read,
)
from app.core.database import get_db
from app.models.service_account import ServiceScope
from app.models.user import User, UserRole
from app.services.action_permissions import ProductAction
from app.services.care import access as care_access
from app.services.care import cadence as care_cadence
from app.services.hr import modules as hr_modules
from app.services.hr.modules import HrModule
from app.services.permission_denial import ensure_permission
from app.services.section_permissions import ProductSection

WRITER_DENIED = (
    "Opiekę nad konsultantami prowadzą Delivery Lead, Talent Community Manager "
    "i administrator."
)

_DELIVERY_SECTION = require_section_access(ProductSection.delivery)
_REVIEW_SECTION_READ = require_section_access_any_read(
    ProductSection.delivery, ProductSection.sourcing
)
_REVIEW_SECTION = require_section_access_any(
    ProductSection.delivery, ProductSection.sourcing
)
_REVIEW_READER = require_permission_or_roles(
    ProductAction.delivery_view, UserRole.head_of_recruitment
)
_CURATOR_ROLES = require_roles(
    UserRole.admin, UserRole.head_of_recruitment, UserRole.talent_community_manager
)
#: D11: kto widzi strukturę u klienta i opinie klienta (Finanse i Kadry nie).
_PEOPLE_READER_ROLES: tuple[UserRole, ...] = (
    UserRole.admin,
    UserRole.delivery_lead,
    UserRole.talent_community_manager,
    UserRole.head_of_recruitment,
)
ASSIGN_DENIED = (
    "Przydział wielu konsultantów naraz i próg obciążenia ustawia head back "
    "office albo administrator."
)
PEOPLE_DENIED = (
    "Strukturę u klienta i opinie klienta widzą opiekun kontraktu, Delivery Lead "
    "klienta, Head of Recruitment i administrator."
)
_ATLAS_SCOPE = require_service_scope(ServiceScope.sales_signals_read)
_ATLAS_WRITE_SCOPE = require_service_scope(ServiceScope.sales_signals_write)


def require_hr_care_reader():
    """Odczyt opieki i mapy: sekcja Delivery + podgląd Delivery + moduł włączony."""

    async def _check(
        viewer: DeliveryViewUser,
        current_user: User = Depends(_DELIVERY_SECTION),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        await ensure_module(db, current_user, HrModule.care)
        return current_user

    return _check


def require_hr_care_writer():
    """Zapis opieki: jak odczyt + rola DL, TCM albo admin."""

    async def _check(
        viewer: DeliveryViewUser,
        current_user: User = Depends(_DELIVERY_SECTION),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        if not care_access.is_care_worker(current_user):
            raise HTTPException(status.HTTP_403_FORBIDDEN, WRITER_DENIED)
        await ensure_module(db, current_user, HrModule.care)
        return current_user

    return _check


async def _delivery_or_back_office_head(
    request: Request, user: User, db: AsyncSession
) -> None:
    """Wejście ``CareReader`` (podgląd i sekcja Delivery) albo head back office.

    Kolejność i treść odmowy jak w ``CareReader``: najpierw uprawnienie, potem
    sekcja. Head back office przechodzi mimo odmowy (O8, O10).
    """

    try:
        ensure_permission(user, ProductAction.delivery_view)
        await _DELIVERY_SECTION(request, user)
    except HTTPException:
        if not await care_cadence.is_back_office_head(db, user):
            raise


def require_hr_care_rhythm_reader():
    """„Konsultanci”, rytm kontaktu i „Przydział”: czytelnicy opieki i head back office."""

    async def _check(
        request: Request,
        current_user: User = Depends(require_onboarded_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        await _delivery_or_back_office_head(request, current_user, db)
        await ensure_module(db, current_user, HrModule.care)
        return current_user

    return _check


def require_hr_care_assigner():
    """Przydział wielu konsultantów naraz i próg obciążenia: head back office, admin."""

    async def _check(
        request: Request,
        current_user: User = Depends(require_onboarded_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        await _delivery_or_back_office_head(request, current_user, db)
        await ensure_module(db, current_user, HrModule.care)
        if not current_user.has_role(
            UserRole.admin
        ) and not await care_cadence.is_back_office_head(db, current_user):
            raise HTTPException(status.HTTP_403_FORBIDDEN, ASSIGN_DENIED)
        return current_user

    return _check


def require_hr_care_review_reader():
    """Kolejka technologii: czytelnicy opieki i osoby od słownika umiejętności."""

    async def _check(
        reader: User = Depends(_REVIEW_READER),
        current_user: User = Depends(_REVIEW_SECTION_READ),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        await ensure_module(db, current_user, HrModule.care)
        return current_user

    return _check


def require_hr_care_skill_curator():
    """Decyzje w kolejce technologii (zmieniają słownik całej aplikacji)."""

    async def _check(
        curator: User = Depends(_CURATOR_ROLES),
        current_user: User = Depends(_REVIEW_SECTION),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        await ensure_module(db, current_user, HrModule.care)
        return current_user

    return _check


def require_hr_care_atlas_reader():
    """ATLAS: klucz z ``sales_signals:read`` albo admin z JWT.

    Klucz konta serwisowego nie ma osoby, więc przełącznik modułu czyta się
    wprost (admin z JWT przechodzi jak w ``ensure_module``).
    """

    async def _check(
        caller: Caller = Depends(_ATLAS_SCOPE),
        db: AsyncSession = Depends(get_db),
    ) -> Caller:
        if caller.user is not None:
            return caller
        loaded = await hr_modules.load_modules(db)
        if not loaded.get(HrModule.care):
            raise HTTPException(status.HTTP_404_NOT_FOUND, MODULE_DISABLED_DETAIL)
        return caller

    return _check


def require_hr_care_atlas_admin():
    """Zwrot statusów sygnałów: klucz z ``sales_signals:write`` albo admin z JWT."""

    async def _check(caller: Caller = Depends(_ATLAS_WRITE_SCOPE)) -> Caller:
        return caller

    return _check


def require_hr_client_people_reader():
    """Struktura u klienta i opinie (D11): opiekun, DL klienta, HoR, admin.

    Head of Recruitment nie ma sekcji Delivery, więc wejście jak w kolejce
    technologii (Delivery albo Pozyskiwanie, podgląd Delivery albo rola HoR),
    a potem rola z listy D11 — Finanse i Kadry z samego uprawnienia odpadają.
    Zakres klientów Delivery Leada sprawdza trasa (``care_access``).
    """

    async def _check(
        reader: User = Depends(_REVIEW_READER),
        current_user: User = Depends(_REVIEW_SECTION_READ),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        if not reads_client_people(current_user):
            raise HTTPException(status.HTTP_403_FORBIDDEN, PEOPLE_DENIED)
        await ensure_module(db, current_user, HrModule.care)
        return current_user

    return _check


def require_hr_client_org_editor():
    """„Podlega pod” i dział kontaktu: edycja klientów + zapis w Delivery.

    Portfel Delivery Leada (``can_edit_contacts``) sprawdza trasa.
    """

    async def _check(
        editor: ClientsEditUser,
        current_user: User = Depends(_DELIVERY_SECTION),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        await ensure_module(db, current_user, HrModule.care)
        return current_user

    return _check


def reads_client_people(user: User) -> bool:
    """D11: opinie klienta widzą opiekun, DL, Head of Recruitment i admin."""

    return user.has_any_role(*_PEOPLE_READER_ROLES)


def can_curate(user: User) -> bool:
    """Decyzje w kolejce technologii (te same role co ``require_hr_care_skill_curator``)."""

    return user.has_any_role(
        UserRole.admin, UserRole.head_of_recruitment, UserRole.talent_community_manager
    )


CareReader = require_hr_care_reader()
CareWriter = require_hr_care_writer()
CareAssigner = require_hr_care_assigner()
RhythmReader = require_hr_care_rhythm_reader()
ReviewReader = require_hr_care_review_reader()
SkillCurator = require_hr_care_skill_curator()
AtlasReader = require_hr_care_atlas_reader()
AtlasAdmin = require_hr_care_atlas_admin()
PeopleReader = require_hr_client_people_reader()
OrgEditor = require_hr_client_org_editor()
