"""„Ludzie” i „Mój czas” — katalog, kartoteka i stan modułów (krok E0).

* ``GET /api/hr/config`` — przełączniki modułów i prawa zalogowanej osoby
  (front decyduje, co pokazać w menu; serwer i tak sprawdza każdą trasę),
* ``GET /api/hr/people`` — katalog: wizytówki osób zatrudnionych,
* ``GET /api/hr/people/{user_id}`` — kartoteka w zakresie czytającego
  (sama osoba, przełożony i Kadry widzą całość; reszta wizytówkę),
* ``GET /api/hr/me`` — własna kartoteka (pusta, gdy osoba jej nie ma).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.hr_gates import HrConfigReader, HrPeopleReader
from app.core.database import get_db
from app.models.user import UserRole
from app.services.action_permissions import ProductAction, has_permission
from app.services.hr import modules as hr_modules
from app.services.admin_cases import service as admin_cases_service
from app.services.hr import people

router = APIRouter()


@router.get("/config")
async def hr_config(
    current_user: HrConfigReader, db: AsyncSession = Depends(get_db)
) -> dict:
    loaded = await hr_modules.load_modules(db)
    profile = await people.profile_of(db, current_user.id)
    reports = await people.direct_report_ids(db, current_user.id)
    is_admin = current_user.has_role(UserRole.admin)
    return {
        "modules": loaded,
        "open_modules": {
            key: hr_modules.module_open_for(current_user, loaded, key) for key in loaded
        },
        "me": {
            "has_profile": profile is not None
            and profile.employment_status != "exited",
            "employment_status": profile.employment_status if profile else None,
            "is_manager": bool(reports),
            "direct_reports": len(reports),
            "is_admin": is_admin,
            "people_admin": has_permission(current_user, ProductAction.people_admin),
            "payroll": has_permission(current_user, ProductAction.payroll),
            "equipment": has_permission(current_user, ProductAction.equipment),
            "cases": has_permission(current_user, ProductAction.cases),
            # Przypisany do sprawy bez uprawnienia widzi zakładkę „Sprawy”
            # (tylko swoje sprawy — pilnuje tego `/api/cases`).
            "has_assigned_cases": await admin_cases_service.has_assigned_cases(
                db, current_user.id
            ),
        },
    }


@router.get("/people")
async def list_people(
    current_user: HrPeopleReader, db: AsyncSession = Depends(get_db)
) -> dict:
    rows = await people.directory(db)
    admin = people.is_people_admin(current_user)
    items = []
    for row in rows:
        own_report = row.profile.manager_user_id == current_user.id
        if admin or own_report or row.user.id == current_user.id:
            items.append({**people.full_payload(row), "scope": "full"})
        else:
            items.append({**people.card_payload(row), "scope": "card"})
    return {"items": items, "total": len(items)}


@router.get("/people/{user_id}")
async def get_person(
    user_id: int, current_user: HrPeopleReader, db: AsyncSession = Depends(get_db)
) -> dict:
    row = await people.person_row(db, user_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie ma takiej kartoteki.")
    scope = await people.viewer_scope(db, current_user, row.profile)
    if scope == "none" and not people.is_people_admin(current_user):
        # Konto z innym uprawnieniem z grupy „Ludzie” (np. Sprzęt) widzi wizytówkę.
        scope = "card"
    if scope == "full":
        payload = people.full_payload(row)
        payload["entitlements"] = [
            {
                "year": e.year,
                "entitlement_days": e.entitlement_days,
                "carried_over_days": e.carried_over_days,
                "used_initial_days": e.used_initial_days,
            }
            for e in await people.entitlements_of(db, user_id)
        ]
    else:
        payload = people.card_payload(row)
    return {**payload, "scope": scope}


@router.get("/me")
async def my_profile(
    current_user: HrConfigReader, db: AsyncSession = Depends(get_db)
) -> dict:
    row = await people.person_row(db, current_user.id)
    if row is None:
        return {"has_profile": False}
    payload = people.full_payload(row)
    payload["entitlements"] = [
        {
            "year": e.year,
            "entitlement_days": e.entitlement_days,
            "carried_over_days": e.carried_over_days,
            "used_initial_days": e.used_initial_days,
        }
        for e in await people.entitlements_of(db, current_user.id)
    ]
    return {"has_profile": True, **payload}
