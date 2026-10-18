"""Kadry — zakładanie i edycja kartotek, pule urlopowe, dni wolne firmy,
przełączniki modułów („Ludzie w NEXUSIE”, krok E0).

Router za uprawnieniem „Kadry” (``people_admin``); przełączniki modułów tylko
admin (przełączenie z Compassa to decyzja całej firmy, nie jednego działu).
Trasy Kadr nie czekają na przełącznik modułu — Kadry przygotowują kartoteki
przed włączeniem modułu.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminUser
from app.api.hr_gates import HrPeopleAdmin, require_hr_people_admin
from app.core.database import get_db
from app.services.hr import availability_local
from app.services.hr import modules as hr_modules
from app.services.hr import people
from app.services.hr.leave_policy import statutory_entitlement
from app.services.hr_foundation_schema import EmploymentStatus, EmploymentType

router = APIRouter(dependencies=[Depends(require_hr_people_admin())])

Location = Literal["onsite", "remote"]
Division = Literal["front_office", "back_office"]


class ProfileFields(BaseModel):
    manager_user_id: Optional[int] = None
    employment_type: Optional[EmploymentType] = None
    employment_status: Optional[EmploymentStatus] = None
    hired_on: Optional[date] = None
    work_start_date: Optional[date] = None
    last_working_day: Optional[date] = None
    default_location: Optional[Location] = None
    timesheet_required: Optional[bool] = None
    can_log_overtime: Optional[bool] = None
    job_title: Optional[str] = Field(default=None, max_length=200)
    department: Optional[str] = Field(default=None, max_length=200)
    phone: Optional[str] = Field(default=None, max_length=64)
    # Pion firmy (17.10.2026): Front office / Back office; `null` = bez pionu.
    division: Optional[Division] = None
    # Etap 2, forma współpracy: uczeń/student na zleceniu bez składek do daty
    # (D8, bez daty urodzenia) i staż do urlopu z zaświadczeniem ZUS na UoP (D9).
    student_contribution_exempt: Optional[bool] = None
    contribution_exempt_until: Optional[date] = None
    leave_seniority_years: Optional[int] = Field(default=None, ge=0, le=60)
    zus_certificate_received_on: Optional[date] = None


class ProfileCreate(ProfileFields):
    user_id: int


class EntitlementIn(BaseModel):
    entitlement_days: Optional[Decimal] = Field(default=None, ge=0, le=366)
    carried_over_days: Decimal = Field(default=Decimal("0"), ge=0, le=366)
    used_initial_days: Decimal = Field(default=Decimal("0"), ge=0, le=366)
    reason: Optional[str] = Field(default=None, max_length=500)


class DayOffIn(BaseModel):
    day: date
    name: str = Field(min_length=1, max_length=120)
    kind: Literal["company", "bridge"] = "company"


class ModulesIn(BaseModel):
    modules: dict[str, bool]


class AvailabilitySourceIn(BaseModel):
    source: Literal["compass", "local"]


def _unprocessable(exc: Exception) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))


@router.get("/users-without-profile")
async def users_without_profile(
    _: HrPeopleAdmin, db: AsyncSession = Depends(get_db)
) -> dict:
    return {"items": await people.users_without_profile(db)}


@router.post("/profiles", status_code=status.HTTP_201_CREATED)
async def create_profile(
    payload: ProfileCreate,
    current_user: HrPeopleAdmin,
    db: AsyncSession = Depends(get_db),
) -> dict:
    values = payload.model_dump(exclude={"user_id"}, exclude_none=True)
    try:
        await people.create_profile(
            db, user_id=payload.user_id, values=values, actor=current_user
        )
    except people.HrPeopleError as exc:
        raise _unprocessable(exc) from exc
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie ma takiego konta.") from exc
    await db.commit()
    row = await people.person_row(db, payload.user_id)
    return people.full_payload(row)


@router.patch("/profiles/{user_id}")
async def update_profile(
    user_id: int,
    payload: ProfileFields,
    current_user: HrPeopleAdmin,
    db: AsyncSession = Depends(get_db),
) -> dict:
    # `exclude_unset`: jawne `null` czyści pole (np. przełożonego).
    values = payload.model_dump(exclude_unset=True)
    try:
        await people.update_profile(
            db, user_id=user_id, values=values, actor=current_user
        )
    except people.HrPeopleError as exc:
        raise _unprocessable(exc) from exc
    except LookupError as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Nie ma takiej kartoteki."
        ) from exc
    await db.commit()
    row = await people.person_row(db, user_id)
    return people.full_payload(row)


@router.put("/profiles/{user_id}/entitlements/{year}")
async def put_entitlement(
    user_id: int,
    year: int,
    payload: EntitlementIn,
    current_user: HrPeopleAdmin,
    db: AsyncSession = Depends(get_db),
) -> dict:
    if not 2020 <= year <= 2100:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Nieprawidłowy rok.")
    try:
        row = await people.set_entitlement(
            db,
            user_id=user_id,
            year=year,
            entitlement_days=payload.entitlement_days,
            carried_over_days=payload.carried_over_days,
            used_initial_days=payload.used_initial_days,
            reason=payload.reason,
            actor=current_user,
        )
    except people.HrPeopleError as exc:
        raise _unprocessable(exc) from exc
    except LookupError as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Nie ma takiej kartoteki."
        ) from exc
    await db.commit()
    profile = await people.profile_of(db, user_id)
    return {
        "year": row.year,
        "entitlement_days": row.entitlement_days,
        "carried_over_days": row.carried_over_days,
        "used_initial_days": row.used_initial_days,
        # D9: podpowiedź wymiaru z kartoteki (20/26) — tylko podpowiedź.
        "suggested_entitlement_days": statutory_entitlement(
            profile.employment_type if profile else None,
            profile.leave_seniority_years if profile else None,
        ),
    }


@router.get("/days-off")
async def list_days_off(
    _: HrPeopleAdmin, year: Optional[int] = None, db: AsyncSession = Depends(get_db)
) -> dict:
    rows = await people.days_off(db, year=year)
    return {
        "items": [
            {"id": r.id, "day": r.day, "name": r.name, "kind": r.kind} for r in rows
        ]
    }


@router.post("/days-off", status_code=status.HTTP_201_CREATED)
async def add_day_off(
    payload: DayOffIn, current_user: HrPeopleAdmin, db: AsyncSession = Depends(get_db)
) -> dict:
    try:
        row = await people.add_day_off(
            db,
            day=payload.day,
            name=payload.name,
            kind=payload.kind,
            actor=current_user,
        )
    except people.HrPeopleError as exc:
        raise _unprocessable(exc) from exc
    await db.commit()
    return {"id": row.id, "day": row.day, "name": row.name, "kind": row.kind}


@router.delete("/days-off/{day_off_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_day_off(
    day_off_id: int, current_user: HrPeopleAdmin, db: AsyncSession = Depends(get_db)
) -> None:
    try:
        await people.remove_day_off(db, day_off_id=day_off_id, actor=current_user)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie ma takiego dnia.") from exc
    await db.commit()


@router.put("/modules")
async def put_modules(
    payload: ModulesIn, current_user: AdminUser, db: AsyncSession = Depends(get_db)
) -> dict:
    try:
        updated = await hr_modules.set_modules(db, payload.modules, actor=current_user)
    except hr_modules.UnknownModuleError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"Nieznany moduł: {exc}"
        ) from exc
    await db.commit()
    return {"modules": updated}


@router.get("/availability-source")
async def get_availability_source(
    current_user: AdminUser, db: AsyncSession = Depends(get_db)
) -> dict:
    """Skąd zastępstwa i dni robocze biorą urlopy: Compass albo NEXUS."""
    return {"source": await availability_local.current_source(db)}


@router.put("/availability-source")
async def put_availability_source(
    payload: AvailabilitySourceIn,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    source = await availability_local.set_source(
        db, payload.source, actor_user_id=current_user.id
    )
    await db.commit()
    return {"source": source}
