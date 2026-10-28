"""„Ludzie” i „Mój czas” — katalog, kartoteka i stan modułów (krok E0).

* ``GET /api/hr/config`` — przełączniki modułów i prawa zalogowanej osoby
  (front decyduje, co pokazać w menu; serwer i tak sprawdza każdą trasę),
* ``GET /api/hr/people`` — katalog: wizytówki osób zatrudnionych z kolumną
  „Dziś” (nieobecność bez rodzaju, praca zdalna i delegacja),
* ``GET /api/hr/people/{user_id}`` — kartoteka w zakresie czytającego
  (sama osoba, przełożony, Kadry i Finanse widzą całość; reszta wizytówkę;
  formę umowy tylko osoba, przełożony, admin i Finanse — ``people.form_viewer``),
* ``GET /api/hr/people/{user_id}/history`` — zakładka kartoteki
  „Nieobecności i godziny”: nieobecności roku i raporty godzin osoby, tylko
  w pełnym zakresie (``services/hr/person_history.py``, D6 w środku),
* ``GET /api/hr/me`` — własna kartoteka (pusta, gdy osoba jej nie ma).
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.hr_gates import (
    HrConfigReader,
    HrPeopleReader,
    HrPeopleRecords,
    refuse_self_edit,
)
from app.core.database import get_db
from app.core.scheduling import business_today
from app.models.user import UserRole
from app.services.action_permissions import ProductAction, has_permission
from app.services.hr import modules as hr_modules
from app.services.admin_cases import service as admin_cases_service
from app.services.hr import (
    account_profiles,
    leave_service,
    leave_substitute,
    people,
    person_history,
)
from app.services.hr.absence import absences_on
from app.services.hr.leave_balance import balance_payload
from app.services.hr.leave_policy import actor_of, can_see_type
from app.services.hr.leave_calendar import presence_between
from app.services.hr.modules import HrModule
from app.services.hr.lifecycle_templates import is_back_office_head
from app.services.hr.program import program_enabled
from app.services.hr_foundation_schema import EmploymentStatus, EmploymentType

router = APIRouter()


@router.get("/config")
async def hr_config(
    current_user: HrConfigReader, db: AsyncSession = Depends(get_db)
) -> dict:
    loaded = await hr_modules.load_modules(db)
    if not program_enabled():
        # Program wyłączony: wszystko zamknięte, bez zapytań o kartotekę —
        # tę sondę woła każdy ekran (menu, profil klienta, kontrakt).
        return {
            "program": False,
            "modules": loaded,
            "open_modules": {key: False for key in loaded},
            "me": {
                "has_profile": False,
                "employment_status": None,
                "is_manager": False,
                "covering": [],
                "direct_reports": 0,
                "is_admin": False,
                "people_admin": False,
                "payroll": False,
                "equipment": False,
                "cases": False,
                "timesheets": False,
                "leave_approver": False,
                "has_assigned_cases": False,
                "back_office_head": False,
            },
        }
    profile = await people.profile_of(db, current_user.id)
    reports = await people.direct_report_ids(db, current_user.id)
    is_admin = current_user.has_role(UserRole.admin)
    return {
        "program": True,
        "modules": loaded,
        "open_modules": {
            key: hr_modules.module_open_for(current_user, loaded, key) for key in loaded
        },
        "me": {
            "has_profile": profile is not None
            and profile.employment_status != EmploymentStatus.exited,
            "employment_status": profile.employment_status if profile else None,
            "is_manager": bool(reports),
            # Kogo osoba zastępuje dziś (przełożony na urlopie) — „Akceptacje”.
            "covering": await leave_substitute.covering_payload(
                db, current_user.id, business_today()
            ),
            "direct_reports": len(reports),
            "is_admin": is_admin,
            "people_admin": has_permission(current_user, ProductAction.people_admin),
            "payroll": has_permission(current_user, ProductAction.payroll),
            "equipment": has_permission(current_user, ProductAction.equipment),
            "cases": has_permission(current_user, ProductAction.cases),
            "timesheets": has_permission(current_user, ProductAction.timesheets),
            # Kolejka nieobecności (bramka tras urlopów) — „Akceptacje” chowają
            # nieobecności osobie, która akceptuje same raporty godzin.
            "leave_approver": await leave_service.is_leave_approver(db, current_user),
            # Przypisany do sprawy bez uprawnienia widzi zakładkę „Sprawy”
            # (tylko swoje sprawy — pilnuje tego `/api/cases`).
            "has_assigned_cases": await admin_cases_service.has_assigned_cases(
                db, current_user.id
            ),
            # Head back office edytuje ścieżkę „Konsultant u klienta” (etap 3, O4).
            "back_office_head": await is_back_office_head(db, current_user),
        },
    }


@router.get("/people")
async def list_people(
    current_user: HrPeopleReader, db: AsyncSession = Depends(get_db)
) -> dict:
    rows = await people.directory(db)
    form = await people.form_viewer(db, current_user)
    # Kadry i Finanse widzą całe kartoteki; przełożony — swoich ludzi (ta sama
    # reguła co „Mój zespół”: kto odszedł, nie ma podwładnych).
    everyone = people.is_people_admin(current_user) or form.everyone
    items = []
    today = await _today_by_user(db, current_user, [row.user.id for row in rows])
    for row in rows:
        if everyone or form.sees(row.user.id):
            item = {**people.full_payload(row, form=form), "scope": "full"}
        else:
            item = {**people.card_payload(row), "scope": "card"}
        items.append({**item, "today": today.get(row.user.id)})
    return {"items": items, "total": len(items)}


async def _today_by_user(db: AsyncSession, viewer, user_ids: list[int]) -> dict:
    """Kolumna „Dziś” katalogu (makieta 19.10.2026).

    Nieobecność bez rodzaju (D6 — katalog widzi cała firma, jak plakietka
    ``/api/hr/leave/absence``), tylko przy module urlopów otwartym dla
    patrzącego. Praca zdalna i delegacja z ``attendance_days`` — tylko przy
    module czasu otwartym dla patrzącego, jak w kalendarzu zespołu. Osoba bez
    wpisu = ``None`` (front mówi „w pracy”, gdy działa któryś z modułów).
    """

    loaded = await hr_modules.load_modules(db)
    day = business_today()
    absent = (
        await absences_on(db, user_ids, day)
        if hr_modules.module_open_for(viewer, loaded, HrModule.leave)
        else {}
    )
    presence = (
        await presence_between(db, user_ids, day, day)
        if hr_modules.module_open_for(viewer, loaded, HrModule.time)
        else {}
    )
    out: dict[int, dict] = {}
    for user_id in user_ids:
        absence = absent.get(user_id)
        kind = next((p["kind"] for p in presence.get(user_id, [])), None)
        if absence is None and kind is None:
            continue
        out[user_id] = {
            "absent_until": absence.until.isoformat() if absence else None,
            "half_day": absence.half_day if absence else None,
            "substitute_name": absence.substitute_name if absence else None,
            "presence": None if absence else kind,
        }
    return out


class AlignIn(BaseModel):
    #: ``None`` = wszystkie rozjazdy z listy.
    user_ids: Optional[list[int]] = Field(default=None, max_length=500)


class EmploymentTypeIn(BaseModel):
    employment_type: EmploymentType
    student_contribution_exempt: Optional[bool] = None
    contribution_exempt_until: Optional[date] = None
    leave_seniority_years: Optional[int] = Field(default=None, ge=0, le=60)
    zus_certificate_received_on: Optional[date] = None


@router.get("/people/account-mismatches")
async def account_mismatches(
    _: HrPeopleRecords, db: AsyncSession = Depends(get_db)
) -> dict:
    """Rozjazdy kartoteka ↔ konto NEXUSA i liczniki „do uzupełnienia”."""

    items = [item.payload() for item in await account_profiles.mismatches(db)]
    return {
        "items": items,
        "total": len(items),
        "pending": await account_profiles.pending_counts(db),
    }


@router.post("/people/account-mismatches/align")
async def align_with_accounts(
    payload: AlignIn, current_user: HrPeopleRecords, db: AsyncSession = Depends(get_db)
) -> dict:
    """„Wyrównaj wg konta” — konto decyduje (decyzja Artura 19.10.2026).

    „Nie sobie” jak każdy zapis kartoteki (audyt 21.10.2026): własne id w liście
    = 403, a „wszystkie rozjazdy” pomijają własną kartotekę. Admin przechodzi.
    """

    if payload.user_ids is not None:
        refuse_self_edit(current_user, payload.user_ids)
    counts = await account_profiles.align(
        db,
        actor=current_user,
        user_ids=set(payload.user_ids) if payload.user_ids is not None else None,
        skip_user_ids=(
            set() if current_user.has_role(UserRole.admin) else {current_user.id}
        ),
    )
    await db.commit()
    return {"aligned": counts}


@router.patch("/people/{user_id}/employment-type")
async def set_employment_type(
    user_id: int,
    payload: EmploymentTypeIn,
    current_user: HrPeopleRecords,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Forma umowy i pola od niej zależne — admin, Finanse i Kadry."""

    refuse_self_edit(current_user, [user_id])
    try:
        await people.update_profile(
            db,
            user_id=user_id,
            values=payload.model_dump(exclude_unset=True),
            actor=current_user,
        )
    except people.HrPeopleError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Nie ma takiej kartoteki."
        ) from exc
    await db.commit()
    row = await people.person_row(db, user_id)
    return people.full_payload(row, form=await people.form_viewer(db, current_user))


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
        payload = people.full_payload(
            row, form=await people.form_viewer(db, current_user)
        )
        payload["entitlements"] = [
            {
                "year": e.year,
                "entitlement_days": e.entitlement_days,
                "carried_over_days": e.carried_over_days,
                "used_initial_days": e.used_initial_days,
            }
            for e in await people.entitlements_of(db, user_id)
        ]
        payload["leave_balance"] = await _leave_ring(db, current_user, row.profile)
    else:
        payload = people.card_payload(row)
    return {**payload, "scope": scope}


HISTORY_DETAIL = (
    "Nieobecności i godziny widzą ta osoba, jej koordynator, Kadry i Finanse."
)


@router.get("/people/{user_id}/history")
async def get_person_history(
    user_id: int,
    current_user: HrPeopleReader,
    db: AsyncSession = Depends(get_db),
    year: Optional[int] = Query(default=None, ge=2020, le=2100),
) -> dict:
    """Zakładka „Nieobecności i godziny” — ten sam krąg co pełna kartoteka.

    Część modułu zamkniętego dla patrzącego to ``None`` (ekran jej nie
    pokazuje), nie pusta lista.
    """

    row = await people.person_row(db, user_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie ma takiej kartoteki.")
    if await people.viewer_scope(db, current_user, row.profile) != "full":
        raise HTTPException(status.HTTP_403_FORBIDDEN, HISTORY_DETAIL)
    today = business_today()
    loaded = await hr_modules.load_modules(db)
    profile = row.profile
    viewer = person_history.Viewer(
        type_visible=can_see_type(
            actor_of(current_user),
            subject_user_id=profile.user_id,
            subject_manager_id=profile.manager_user_id,
        ),
        form_visible=(await people.form_viewer(db, current_user)).sees(profile.user_id),
    )
    absences = None
    if hr_modules.module_open_for(current_user, loaded, HrModule.leave):
        absences = {
            "type_visible": viewer.type_visible,
            "items": await person_history.absences(
                db, profile, year=year or today.year, today=today, viewer=viewer
            ),
        }
    timesheets = None
    if hr_modules.module_open_for(current_user, loaded, HrModule.time):
        timesheets = {
            "timesheet_required": profile.timesheet_required,
            "items": await person_history.timesheets(db, profile, today=today),
        }
    return {
        "year": year or today.year,
        "today": today.isoformat(),
        "absences": absences,
        "timesheets": timesheets,
    }


#: Pola salda do pierścienia w kartotece (makieta 19.10.2026). Bez liczników
#: rodzajów (na żądanie, opieka nad dzieckiem, bezpłatne) i bez listy typów —
#: kartotekę czytają też Finanse spoza kręgu D6, a typy zdradzają formę.
LEAVE_RING_FIELDS = (
    "year",
    "has_paid_pool",
    "entitlement_days",
    "carried_over_days",
    "used_days",
    "planned_days",
    "remaining_days",
)


async def _leave_ring(db: AsyncSession, viewer, profile) -> Optional[dict]:
    """Saldo płatnych dni do kartoteki — tylko przy module urlopów otwartym dla
    patrzącego i puli w umowie (zlecenie bez puli = ``None``)."""

    loaded = await hr_modules.load_modules(db)
    if not hr_modules.module_open_for(viewer, loaded, HrModule.leave):
        return None
    today = business_today()
    balance = await balance_payload(
        db,
        user_id=profile.user_id,
        year=today.year,
        employment_type=profile.employment_type,
        today=today,
    )
    if not balance.get("has_paid_pool"):
        return None
    return {key: balance.get(key) for key in LEAVE_RING_FIELDS}


@router.get("/me")
async def my_profile(
    current_user: HrConfigReader, db: AsyncSession = Depends(get_db)
) -> dict:
    row = await people.person_row(db, current_user.id)
    if row is None:
        return {"has_profile": False}
    payload = people.full_payload(row, form=await people.form_viewer(db, current_user))
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
