"""„Mój miesiąc” — obecność, timesheety, akceptacje, PDF.

Prefiks ``/api/hr/time`` (wpięty w ``app/main.py``). Każda trasa ma nazwaną bramkę
``require_hr_*`` (``app/api/hr_gates.py`` albo własną w tym module) i sprawdza
przełącznik modułu w ``app_settings['hr_modules']``.

* ``/me/…`` — samoobsługa osoby z kartoteką (siatka miesiąca, wyjątki
  obecności, wpisy, wypełnianie, kopiowanie, podpowiedź, wysyłka, PDF),
* ``/team/…`` i ``/timesheets/{id}/…`` — akceptujący (przełożony dla swoich
  ludzi, Kadry i admin dla wszystkich, nikt siebie),
* ``/export/{rok}/{miesiąc}/zip`` i ``…/csv`` — Płace, Kadry, admin,
* ``/me/export.csv`` i ``/people/{id}/export.csv`` — godziny w CSV za zakres
  miesięcy: własne i osoby w zakresie czytającego (jak PDF),
* ``/role-defaults`` — domyślne opisy (Kadry, admin),
* ``/remind/{osoba}/{rok}/{miesiąc}`` — „Przypomnij” o timesheecie (Płace,
  Kadry, admin, akceptujący tej osoby; raz dziennie na adresata).
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_onboarded_user
from app.api.hr_gates import (
    NO_PROFILE_DETAIL,
    ensure_module,
    require_hr_self_service,
)
from app.core.database import get_db
from app.core.scheduling import business_today
from app.models.hr_profile import EmployeeProfile
from app.models.hr_time import Timesheet, TimesheetEntry
from app.models.user import User, UserRole
from app.services.action_permissions import ProductAction, has_permission
from app.services.hr import audit, people
from app.services.hr import (
    time_entries,
    time_fill,
    time_flow,
    time_month,
    time_export,
    time_pdf,
    time_reminders,
    time_retention,
    time_suggest,
)
from app.services.hr.modules import HrModule
from app.services.hr.time_access import Actor, is_time_approver, load_actor
from app.services.hr.time_entries import (
    EntryInput,
    TimeConflict,
    TimeError,
    TimeForbidden,
    TimeNotFound,
    assert_editable,
    clean_description,
    clean_hours,
    clean_project,
    entries_of,
    entry_payload,
    entry_with_timesheet,
    find_timesheet,
    hash_of,
    open_draft,
    validate_period,
)

router = APIRouter()

MODULE = HrModule.time
NOT_APPROVER_DETAIL = (
    "Godziny potwierdza koordynator, Kadry, osoba z uprawnieniem „Raporty godzin” "
    "albo administrator."
)
NOT_PAYROLL_DETAIL = "Godziny całego miesiąca (paczkę i CSV) pobierają Płace i Kadry."
NOT_ADMIN_DETAIL = "Domyślne opisy ustawiają Kadry."
NOT_REMINDER_DETAIL = (
    "O raporcie godzin przypominają Płace, Kadry, administrator "
    "albo osoba, która go akceptuje."
)


# ── Bramki ────────────────────────────────────────────────────────────────────


def require_hr_time_approver():
    """Kolejka akceptacji: przełożony z ludźmi w kartotece, Kadry, „Raporty
    godzin”, admin."""

    async def _check(
        current_user: User = Depends(require_onboarded_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        await ensure_module(db, current_user, MODULE)
        if await is_time_approver(db, current_user):
            return current_user
        raise HTTPException(status.HTTP_403_FORBIDDEN, NOT_APPROVER_DETAIL)

    return _check


def require_hr_time_reader():
    """PDF timesheetu: osoba z kartoteką albo Płace/Kadry/„Raporty godzin”/admin
    (zakres w handlerze)."""

    async def _check(
        current_user: User = Depends(require_onboarded_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        await ensure_module(db, current_user, MODULE)
        if current_user.has_role(UserRole.admin) or any(
            has_permission(current_user, p)
            for p in (
                ProductAction.people_admin,
                ProductAction.payroll,
                ProductAction.timesheets,
            )
        ):
            return current_user
        if await people.has_live_profile(db, current_user.id):
            return current_user
        raise HTTPException(status.HTTP_403_FORBIDDEN, NO_PROFILE_DETAIL)

    return _check


def require_hr_time_payroll():
    async def _check(
        current_user: User = Depends(require_onboarded_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        await ensure_module(db, current_user, MODULE)
        if current_user.has_role(UserRole.admin) or any(
            has_permission(current_user, p)
            for p in (ProductAction.people_admin, ProductAction.payroll)
        ):
            return current_user
        raise HTTPException(status.HTTP_403_FORBIDDEN, NOT_PAYROLL_DETAIL)

    return _check


def require_hr_time_admin():
    async def _check(
        current_user: User = Depends(require_onboarded_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        await ensure_module(db, current_user, MODULE)
        if current_user.has_role(UserRole.admin) or has_permission(
            current_user, ProductAction.people_admin
        ):
            return current_user
        raise HTTPException(status.HTTP_403_FORBIDDEN, NOT_ADMIN_DETAIL)

    return _check


def require_hr_time_reminder():
    """„Przypomnij”: Płace, Kadry, admin albo akceptujący (zakres w serwisie)."""

    async def _check(
        current_user: User = Depends(require_onboarded_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        await ensure_module(db, current_user, MODULE)
        if current_user.has_role(UserRole.admin) or any(
            has_permission(current_user, p)
            for p in (ProductAction.people_admin, ProductAction.payroll)
        ):
            return current_user
        if await is_time_approver(db, current_user):
            return current_user
        raise HTTPException(status.HTTP_403_FORBIDDEN, NOT_REMINDER_DETAIL)

    return _check


SelfUser = Annotated[User, Depends(require_hr_self_service(MODULE))]
ApproverUser = Annotated[User, Depends(require_hr_time_approver())]
ReaderUser = Annotated[User, Depends(require_hr_time_reader())]
PayrollUser = Annotated[User, Depends(require_hr_time_payroll())]
TimeAdminUser = Annotated[User, Depends(require_hr_time_admin())]
ReminderUser = Annotated[User, Depends(require_hr_time_reminder())]


@contextmanager
def _http_errors() -> Iterator[None]:
    try:
        yield
    except TimeError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc


# ── Ciała żądań ───────────────────────────────────────────────────────────────


class EntryIn(BaseModel):
    work_date: date
    hours: Decimal
    project: Optional[str] = Field(default=None, max_length=200)
    description: str = Field(max_length=2000)
    overtime_reason: Optional[str] = Field(default=None, max_length=1000)


class EntryPatch(BaseModel):
    work_date: Optional[date] = None
    hours: Optional[Decimal] = None
    project: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str] = Field(default=None, max_length=2000)
    overtime_reason: Optional[str] = Field(default=None, max_length=1000)


class AttendanceIn(BaseModel):
    status: Literal["active", "business_trip"] = "active"
    location: Optional[Literal["onsite", "remote"]] = None
    note: Optional[str] = Field(default=None, max_length=500)


class FillIn(BaseModel):
    project: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str] = Field(default=None, max_length=2000)
    template_id: Optional[int] = None
    # Okno „Wypełnij miesiąc” (jak Compass): brak = 8 h, najwyżej 8 h.
    hours_per_day: Optional[Decimal] = None
    # Kasuje wpisy szkicu (poza auto-wpisami płatnej puli) przed wypełnieniem.
    overwrite: bool = False


class ReturnIn(BaseModel):
    note: str = Field(max_length=2000)


class TemplateIn(BaseModel):
    name: Optional[str] = Field(default=None, max_length=80)
    description: Optional[str] = Field(default=None, max_length=2000)
    project: Optional[str] = Field(default=None, max_length=200)
    sort_order: Optional[int] = Field(default=None, ge=0, le=10_000)


class RoleDefaultIn(BaseModel):
    label: Optional[str] = Field(default=None, max_length=120)
    applies_to_role: Optional[str] = Field(default=None, max_length=40)
    project: Optional[str] = Field(default=None, max_length=200)
    default_description: Optional[str] = Field(default=None, max_length=2000)
    is_active: Optional[bool] = None
    sort_order: Optional[int] = Field(default=None, ge=0, le=10_000)


def _entry_input(payload: EntryIn) -> EntryInput:
    return EntryInput(
        work_date=payload.work_date,
        hours=clean_hours(payload.hours),
        project=clean_project(payload.project),
        description=clean_description(payload.description),
        overtime_reason=payload.overtime_reason,
    )


def _entry_changes(payload: EntryPatch) -> dict[str, Any]:
    raw = payload.model_dump(exclude_unset=True)
    changes: dict[str, Any] = {}
    if raw.get("work_date") is not None:
        changes["work_date"] = raw["work_date"]
    if raw.get("hours") is not None:
        changes["hours"] = clean_hours(raw["hours"])
    if "project" in raw:
        changes["project"] = clean_project(raw["project"])
    if raw.get("description") is not None:
        changes["description"] = clean_description(raw["description"])
    if "overtime_reason" in raw:
        changes["overtime_reason"] = raw["overtime_reason"]
    return changes


async def _own_profile(db: AsyncSession, user: User) -> EmployeeProfile:
    profile = await people.profile_of(db, user.id)
    if profile is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, NO_PROFILE_DETAIL)
    return profile


# ── Mój miesiąc ───────────────────────────────────────────────────────────────


@router.get("/me/history")
async def my_history(
    current_user: SelfUser, db: AsyncSession = Depends(get_db)
) -> dict:
    return {"items": await time_month.history(db, user_id=current_user.id)}


def _csv_response(file: time_export.CsvFile) -> Response:
    return Response(
        content=file.content,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{file.filename}"',
            "X-Export-Rows": str(file.rows),
        },
    )


def _audit_csv(
    db: AsyncSession,
    *,
    actor: User,
    subject_user_id: Optional[int],
    details: dict[str, Any],
) -> None:
    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=subject_user_id,
        entity_type="timesheet",
        entity_id=None,
        action="timesheet_csv_exported",
        details=details,
    )


@router.get("/me/export.csv")
async def my_csv(
    current_user: SelfUser,
    start: str = Query(alias="from", max_length=7),
    end: str = Query(alias="to", max_length=7),
    db: AsyncSession = Depends(get_db),
) -> Response:
    with _http_errors():
        first, last = time_export.parse_range(start, end)
    file = await time_export.person_csv(db, user=current_user, first=first, last=last)
    return _csv_response(file)


@router.get("/me/suggestion")
async def my_suggestion(
    current_user: SelfUser,
    day: date = Query(...),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await time_suggest.day_activity(db, user_id=current_user.id, day=day)


@router.get("/me/templates")
async def my_templates(
    current_user: SelfUser,
    project: Optional[str] = Query(default=None, max_length=200),
    db: AsyncSession = Depends(get_db),
) -> dict:
    templates = await time_fill.list_templates(db, current_user.id)
    default = await time_fill.resolve_role_default(
        db, current_user, (project or "").strip() or None
    )
    return {
        "items": [_template_payload(row) for row in templates],
        "role_default": None
        if default is None
        else {
            "label": default.label,
            "description": default.default_description,
            "project": default.project,
        },
    }


def _template_payload(row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "description": row.description,
        "project": row.project,
        "sort_order": row.sort_order,
    }


@router.post("/me/templates", status_code=status.HTTP_201_CREATED)
async def create_template(
    payload: TemplateIn, current_user: SelfUser, db: AsyncSession = Depends(get_db)
) -> dict:
    with _http_errors():
        row = await time_fill.save_template(
            db, user_id=current_user.id, values=payload.model_dump(exclude_unset=True)
        )
    return _template_payload(row)


@router.patch("/me/templates/{template_id}")
async def update_template(
    template_id: int,
    payload: TemplateIn,
    current_user: SelfUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    with _http_errors():
        row = await time_fill.save_template(
            db,
            user_id=current_user.id,
            values=payload.model_dump(exclude_unset=True),
            template_id=template_id,
        )
    return _template_payload(row)


@router.delete("/me/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(
    template_id: int, current_user: SelfUser, db: AsyncSession = Depends(get_db)
) -> Response:
    with _http_errors():
        await time_fill.delete_template(
            db, user_id=current_user.id, template_id=template_id
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/me/attendance/{day}")
async def set_my_attendance(
    day: date,
    payload: AttendanceIn,
    current_user: SelfUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    profile = await _own_profile(db, current_user)
    with _http_errors():
        validate_period(day.year, day.month)
        return await time_month.set_attendance(
            db,
            subject=profile,
            actor_user_id=current_user.id,
            day=day,
            status=payload.status,
            location=payload.location,
            note=payload.note,
        )


@router.get("/me/{year}/{month}")
async def my_month(
    year: int, month: int, current_user: SelfUser, db: AsyncSession = Depends(get_db)
) -> dict:
    profile = await _own_profile(db, current_user)
    with _http_errors():
        validate_period(year, month)
        return await time_month.month_view(
            db,
            subject_user=current_user,
            subject=profile,
            year=year,
            month=month,
            show_leave_type=True,
        )


async def _own_draft(
    db: AsyncSession, user: User, year: int, month: int
) -> tuple[Timesheet, EmployeeProfile]:
    profile = await _own_profile(db, user)
    timesheet = await open_draft(
        db, user.id, year, month, employment_type=profile.employment_type
    )
    assert_editable(timesheet, as_approver=False)
    return timesheet, profile


@router.post("/me/{year}/{month}/entries", status_code=status.HTTP_201_CREATED)
async def add_my_entry(
    year: int,
    month: int,
    payload: EntryIn,
    current_user: SelfUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    with _http_errors():
        data = _entry_input(payload)
        timesheet, profile = await _own_draft(db, current_user, year, month)
        actor = await load_actor(db, current_user)
        entry = await time_entries.add_entry(
            db, timesheet=timesheet, subject=profile, actor=actor, data=data
        )
    return entry_payload(entry)


async def _own_entry(
    db: AsyncSession, user: User, entry_id: int
) -> tuple[TimesheetEntry, Timesheet, EmployeeProfile]:
    entry, timesheet = await entry_with_timesheet(db, entry_id)
    if timesheet.user_id != user.id:
        raise TimeNotFound("Nie ma takiego wpisu.")
    assert_editable(timesheet, as_approver=False)
    profile = await _own_profile(db, user)
    return entry, timesheet, profile


@router.patch("/me/entries/{entry_id}")
async def update_my_entry(
    entry_id: int,
    payload: EntryPatch,
    current_user: SelfUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    with _http_errors():
        changes = _entry_changes(payload)
        entry, timesheet, profile = await _own_entry(db, current_user, entry_id)
        actor = await load_actor(db, current_user)
        entry = await time_entries.update_entry(
            db,
            timesheet=timesheet,
            subject=profile,
            actor=actor,
            entry=entry,
            changes=changes,
        )
    return entry_payload(entry)


@router.delete("/me/entries/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_entry(
    entry_id: int, current_user: SelfUser, db: AsyncSession = Depends(get_db)
) -> Response:
    with _http_errors():
        entry, timesheet, profile = await _own_entry(db, current_user, entry_id)
        await time_entries.delete_entry(
            db, timesheet=timesheet, subject=profile, entry=entry
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/me/{year}/{month}/fill")
async def fill_my_month(
    year: int,
    month: int,
    payload: FillIn,
    current_user: SelfUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    with _http_errors():
        timesheet, profile = await _own_draft(db, current_user, year, month)
        actor = await load_actor(db, current_user)
        result = await time_fill.fill_month(
            db,
            timesheet=timesheet,
            subject=profile,
            subject_user=current_user,
            actor=actor,
            project=payload.project,
            description=payload.description,
            template_id=payload.template_id,
            hours_per_day=payload.hours_per_day,
            overwrite=payload.overwrite,
        )
    return result


@router.post("/me/{year}/{month}/copy-previous")
async def copy_my_previous(
    year: int, month: int, current_user: SelfUser, db: AsyncSession = Depends(get_db)
) -> dict:
    with _http_errors():
        timesheet, profile = await _own_draft(db, current_user, year, month)
        actor = await load_actor(db, current_user)
        return await time_fill.copy_previous(
            db, timesheet=timesheet, subject=profile, actor=actor
        )


@router.post("/me/{year}/{month}/submit")
async def submit_my_month(
    year: int, month: int, current_user: SelfUser, db: AsyncSession = Depends(get_db)
) -> dict:
    with _http_errors():
        validate_period(year, month)
        found = await find_timesheet(db, current_user.id, year, month)
        if found is None:
            # Pierwszy zapis miesiąca: szkic z auto-wpisami płatnej puli (miesiąc
            # samego płatnego urlopu kontraktora wysyła się bez ręcznych wpisów).
            profile = await _own_profile(db, current_user)
            found = await open_draft(
                db,
                current_user.id,
                year,
                month,
                employment_type=profile.employment_type,
            )
        actor = await load_actor(db, current_user)
        timesheet = await time_flow.submit(db, timesheet_id=found.id, actor=actor)
    return time_month.timesheet_payload(timesheet)


@router.get("/me/{year}/{month}/pdf")
async def my_pdf(
    year: int, month: int, current_user: SelfUser, db: AsyncSession = Depends(get_db)
) -> Response:
    with _http_errors():
        validate_period(year, month)
        found = await find_timesheet(db, current_user.id, year, month)
        if found is None:
            raise TimeNotFound("Nie ma timesheetu za ten miesiąc.")
        return await _pdf_response(db, found, viewer=current_user)


# ── PDF i ZIP ─────────────────────────────────────────────────────────────────


async def _pdf_sheet(
    db: AsyncSession, timesheet: Timesheet
) -> tuple[Optional[time_pdf.PdfTimesheet], bool]:
    """Dane PDF i to, czy suma bieżących wpisów zgadza się z zapisaną."""

    user, profile = await time_month.subject_for(db, timesheet.user_id)
    entries = await entries_of(db, timesheet.id)
    if user is None or not timesheet.pdf_hash:
        return None, False
    matches = hash_of(entries) == timesheet.pdf_hash
    approver = (
        await db.scalar(select(User.name).where(User.id == timesheet.approved_by))
        if timesheet.approved_by
        else None
    )
    sheet = time_pdf.PdfTimesheet(
        person_name=user.name,
        person_email=user.email,
        # Forma z chwili przyjęcia: potwierdzenie godzin zlecenia zostaje nim
        # także po zmianie formy osoby (art. 8b/8c).
        employment_type=time_retention.document_form(
            timesheet, profile.employment_type if profile else None
        ),
        year=timesheet.year,
        month=timesheet.month,
        pdf_hash=timesheet.pdf_hash,
        approved_at=timesheet.approved_at,
        approved_by_name=approver,
        entries=[
            time_pdf.PdfEntry(
                work_date=entry.work_date.isoformat(),
                hours=Decimal(entry.hours),
                project=entry.project,
                description=entry.description,
                is_overtime=entry.is_overtime,
            )
            for entry in entries
        ],
    )
    return sheet, matches


async def _record_mismatch(
    db: AsyncSession, timesheet: Timesheet, viewer: User
) -> None:
    audit.record(
        db,
        actor_user_id=viewer.id,
        subject_user_id=timesheet.user_id,
        entity_type="timesheet",
        entity_id=timesheet.id,
        action="hash_mismatch",
        details={"year": timesheet.year, "month": timesheet.month},
    )
    await db.commit()


async def _pdf_response(
    db: AsyncSession, timesheet: Timesheet, *, viewer: User
) -> Response:
    if timesheet.status != "approved":
        raise TimeConflict("PDF jest dostępny po akceptacji timesheetu.")
    sheet, matches = await _pdf_sheet(db, timesheet)
    if sheet is None:
        raise TimeConflict(
            "Ten timesheet nie ma sumy kontrolnej — poproś o ponowną akceptację."
        )
    if not matches:
        await _record_mismatch(db, timesheet, viewer)
        raise TimeConflict(
            "Wpisy timesheetu nie zgadzają się z sumą kontrolną zapisaną przy "
            "akceptacji. Zgłoś to Kadrom — PDF nie zostanie wydany."
        )
    content = await asyncio.to_thread(time_pdf.render_pdf, sheet)
    filename = time_pdf.pdf_filename(sheet.person_name, sheet.year, sheet.month)
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/timesheets/{timesheet_id}/pdf")
async def timesheet_pdf(
    timesheet_id: int, current_user: ReaderUser, db: AsyncSession = Depends(get_db)
) -> Response:
    with _http_errors():
        timesheet = await db.get(Timesheet, timesheet_id)
        subject = await people.profile_of(db, timesheet.user_id) if timesheet else None
        if timesheet is None or subject is None:
            raise TimeNotFound("Nie ma takiego timesheetu.")
        actor = await load_actor(db, current_user)
        if not actor.can_read(subject):
            raise TimeNotFound("Nie ma takiego timesheetu.")
        return await _pdf_response(db, timesheet, viewer=current_user)


@router.get("/people/{user_id}/export.csv")
async def person_csv(
    user_id: int,
    current_user: ReaderUser,
    start: str = Query(alias="from", max_length=7),
    end: str = Query(alias="to", max_length=7),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Godziny osoby za zakres miesięcy — zakres czytającego jak przy PDF."""

    with _http_errors():
        first, last = time_export.parse_range(start, end)
        user, subject = await time_month.subject_for(db, user_id)
        actor = await load_actor(db, current_user)
        if user is None or subject is None or not actor.can_read(subject):
            raise TimeNotFound("Nie ma takiej osoby.")
    file = await time_export.person_csv(
        db,
        user=user,
        first=first,
        last=last,
        show_leave_source=actor.sees_leave_type(subject),
    )
    if user_id != current_user.id:
        _audit_csv(
            db,
            actor=current_user,
            subject_user_id=user_id,
            details={"from": first.label(), "to": last.label(), "rows": file.rows},
        )
    return _csv_response(file)


@router.get("/export/{year}/{month}/csv")
async def export_month_csv(
    year: int, month: int, current_user: PayrollUser, db: AsyncSession = Depends(get_db)
) -> Response:
    with _http_errors():
        file = await time_export.month_csv(db, year=year, month=month)
    _audit_csv(
        db,
        actor=current_user,
        subject_user_id=None,
        details={"year": year, "month": month, "rows": file.rows},
    )
    return _csv_response(file)


@router.get("/export/{year}/{month}/zip")
async def export_month_zip(
    year: int, month: int, current_user: PayrollUser, db: AsyncSession = Depends(get_db)
) -> Response:
    with _http_errors():
        validate_period(year, month)
    rows = list(
        await db.scalars(
            select(Timesheet)
            .where(
                Timesheet.year == year,
                Timesheet.month == month,
                Timesheet.status == "approved",
            )
            .order_by(Timesheet.user_id)
        )
    )
    sheets: list[time_pdf.PdfTimesheet] = []
    skipped: list[str] = []
    for timesheet in rows:
        sheet, matches = await _pdf_sheet(db, timesheet)
        if sheet is None or not matches:
            name = await db.scalar(
                select(User.name).where(User.id == timesheet.user_id)
            )
            skipped.append(name or f"osoba {timesheet.user_id}")
            audit.record(
                db,
                actor_user_id=current_user.id,
                subject_user_id=timesheet.user_id,
                entity_type="timesheet",
                entity_id=timesheet.id,
                action="hash_mismatch",
                details={"year": year, "month": month, "export": True},
            )
            continue
        sheets.append(sheet)
    content = await asyncio.to_thread(time_pdf.render_zip, sheets, skipped)
    return Response(
        content=content,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="timesheety-{year}-{month:02d}.zip"',
            "X-Timesheets-Included": str(len(sheets)),
            "X-Timesheets-Skipped": str(len(skipped)),
        },
    )


# ── Akceptacje ────────────────────────────────────────────────────────────────


async def _approver(db: AsyncSession, user: User) -> Actor:
    return await load_actor(db, user)


async def _decidable_subject(
    db: AsyncSession, actor: Actor, user_id: int
) -> tuple[User, EmployeeProfile]:
    user, profile = await time_month.subject_for(db, user_id)
    if user is None or profile is None:
        raise TimeNotFound("Nie ma takiej kartoteki.")
    if user_id == actor.user_id:
        raise TimeForbidden("Własny timesheet prowadzisz w „Moim czasie”.")
    if not actor.can_approve(profile):
        raise TimeNotFound("Nie ma takiej osoby w Twoim zespole.")
    return user, profile


@router.get("/team/{year}/{month}")
async def team_month(
    year: int,
    month: int,
    current_user: ApproverUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    with _http_errors():
        validate_period(year, month)
    actor = await _approver(db, current_user)
    items = await time_month.team_queue(db, actor=actor, year=year, month=month)
    norm_hours = await time_month.month_norm_hours(db, year, month)
    return {"year": year, "month": month, "norm_hours": norm_hours, "items": items}


@router.get("/team/{user_id}/{year}/{month}")
async def team_member_month(
    user_id: int,
    year: int,
    month: int,
    current_user: ApproverUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    with _http_errors():
        validate_period(year, month)
        actor = await _approver(db, current_user)
        user, profile = await _decidable_subject(db, actor, user_id)
        return await time_month.month_view(
            db,
            subject_user=user,
            subject=profile,
            year=year,
            month=month,
            show_leave_type=actor.sees_leave_type(profile),
        )


@router.post(
    "/team/{user_id}/{year}/{month}/entries", status_code=status.HTTP_201_CREATED
)
async def add_team_entry(
    user_id: int,
    year: int,
    month: int,
    payload: EntryIn,
    current_user: ApproverUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    with _http_errors():
        data = _entry_input(payload)
        actor = await _approver(db, current_user)
        _, profile = await _decidable_subject(db, actor, user_id)
        timesheet = await open_draft(
            db, user_id, year, month, employment_type=profile.employment_type
        )
        assert_editable(timesheet, as_approver=True)
        entry = await time_entries.add_entry(
            db, timesheet=timesheet, subject=profile, actor=actor, data=data
        )
        _audit_team_entry(
            db, actor, timesheet, "entry_added_by_approver", entry.work_date
        )
    return entry_payload(entry)


def _audit_team_entry(
    db: AsyncSession, actor: Actor, timesheet: Timesheet, action: str, day: date
) -> None:
    audit.record(
        db,
        actor_user_id=actor.user_id,
        subject_user_id=timesheet.user_id,
        entity_type="timesheet",
        entity_id=timesheet.id,
        action=action,
        details={"day": day.isoformat()},
    )


async def _team_entry(
    db: AsyncSession, actor: Actor, entry_id: int
) -> tuple[TimesheetEntry, Timesheet, EmployeeProfile]:
    entry, timesheet = await entry_with_timesheet(db, entry_id)
    _, profile = await _decidable_subject(db, actor, timesheet.user_id)
    assert_editable(timesheet, as_approver=True)
    return entry, timesheet, profile


@router.patch("/team/entries/{entry_id}")
async def update_team_entry(
    entry_id: int,
    payload: EntryPatch,
    current_user: ApproverUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    with _http_errors():
        changes = _entry_changes(payload)
        actor = await _approver(db, current_user)
        entry, timesheet, profile = await _team_entry(db, actor, entry_id)
        entry = await time_entries.update_entry(
            db,
            timesheet=timesheet,
            subject=profile,
            actor=actor,
            entry=entry,
            changes=changes,
        )
        _audit_team_entry(
            db, actor, timesheet, "entry_edited_by_approver", entry.work_date
        )
    return entry_payload(entry)


@router.delete("/team/entries/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_team_entry(
    entry_id: int, current_user: ApproverUser, db: AsyncSession = Depends(get_db)
) -> Response:
    with _http_errors():
        actor = await _approver(db, current_user)
        entry, timesheet, profile = await _team_entry(db, actor, entry_id)
        day = entry.work_date
        await time_entries.delete_entry(
            db, timesheet=timesheet, subject=profile, entry=entry
        )
        _audit_team_entry(db, actor, timesheet, "entry_deleted_by_approver", day)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _visible_timesheet(db: AsyncSession, actor: Actor, timesheet_id: int) -> None:
    """404 dla timesheetu spoza zakresu (bez zdradzania, że istnieje)."""

    timesheet = await db.get(Timesheet, timesheet_id)
    if timesheet is None:
        raise TimeNotFound("Nie ma takiego timesheetu.")
    if timesheet.user_id == actor.user_id:
        raise TimeForbidden("Własnego timesheetu nie akceptuje się samemu.")
    subject = await people.profile_of(db, timesheet.user_id)
    if subject is None or not actor.can_approve(subject):
        raise TimeNotFound("Nie ma takiego timesheetu.")


@router.post("/timesheets/{timesheet_id}/approve")
async def approve_timesheet(
    timesheet_id: int, current_user: ApproverUser, db: AsyncSession = Depends(get_db)
) -> dict:
    with _http_errors():
        actor = await _approver(db, current_user)
        await _visible_timesheet(db, actor, timesheet_id)
        timesheet = await time_flow.approve(db, timesheet_id=timesheet_id, actor=actor)
    return time_month.timesheet_payload(timesheet, approver_name=current_user.name)


@router.post("/timesheets/{timesheet_id}/return")
async def return_timesheet(
    timesheet_id: int,
    payload: ReturnIn,
    current_user: ApproverUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    with _http_errors():
        actor = await _approver(db, current_user)
        await _visible_timesheet(db, actor, timesheet_id)
        timesheet = await time_flow.return_for_fix(
            db, timesheet_id=timesheet_id, actor=actor, note=payload.note
        )
    return time_month.timesheet_payload(timesheet)


@router.post("/timesheets/{timesheet_id}/revoke")
async def revoke_timesheet(
    timesheet_id: int, current_user: ApproverUser, db: AsyncSession = Depends(get_db)
) -> dict:
    with _http_errors():
        actor = await _approver(db, current_user)
        await _visible_timesheet(db, actor, timesheet_id)
        timesheet = await time_flow.revoke(db, timesheet_id=timesheet_id, actor=actor)
    return time_month.timesheet_payload(timesheet)


@router.post("/remind/{user_id}/{year}/{month}")
async def remind_timesheet(
    user_id: int,
    year: int,
    month: int,
    current_user: ReminderUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """„Przypomnij” o timesheecie osoby za miesiąc.

    Szkic albo brak raportu → powiadomienie do osoby; wysłany → do
    akceptujących (przełożony według ``supervisor_of`` i jego zastępca).
    Drugi klik tego samego dnia nic nie wysyła (``already_today: true``).
    Przyjęty, zamknięty w płacach, bez obowiązku raportu = 409; osoba spoza
    zakresu = 404; sobie = 403.
    """

    with _http_errors():
        actor = await _approver(db, current_user)
        return await time_reminders.remind_one(
            db,
            actor=actor,
            user_id=user_id,
            year=year,
            month=month,
            today=business_today(),
        )


# ── Domyślne opisy (Kadry) ────────────────────────────────────────────────────


def _role_default_payload(row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "label": row.label,
        "applies_to_role": row.applies_to_role,
        "project": row.project,
        "default_description": row.default_description,
        "is_active": row.is_active,
        "sort_order": row.sort_order,
    }


@router.get("/role-defaults")
async def list_role_defaults(
    _: TimeAdminUser, db: AsyncSession = Depends(get_db)
) -> dict:
    rows = await time_fill.list_role_defaults(db)
    return {"items": [_role_default_payload(row) for row in rows]}


@router.post("/role-defaults", status_code=status.HTTP_201_CREATED)
async def create_role_default(
    payload: RoleDefaultIn,
    current_user: TimeAdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    with _http_errors():
        row = await time_fill.save_role_default(
            db, actor=current_user, values=payload.model_dump(exclude_unset=True)
        )
    return _role_default_payload(row)


@router.patch("/role-defaults/{default_id}")
async def update_role_default(
    default_id: int,
    payload: RoleDefaultIn,
    current_user: TimeAdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    with _http_errors():
        row = await time_fill.save_role_default(
            db,
            actor=current_user,
            values=payload.model_dump(exclude_unset=True),
            default_id=default_id,
        )
    return _role_default_payload(row)


@router.delete("/role-defaults/{default_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_role_default(
    default_id: int, current_user: TimeAdminUser, db: AsyncSession = Depends(get_db)
) -> Response:
    with _http_errors():
        await time_fill.delete_role_default(
            db, actor=current_user, default_id=default_id
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
