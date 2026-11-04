"""„Wypełnij miesiąc”, „Skopiuj opisy z poprzedniego”, szablony i domyślne opisy.

Wypełnianie pomija weekendy, święta, dni wolne firmy, dni urlopu (także
oczekującego) i dni, które mają już wpisy. Pół dnia urlopu dostaje 4 h.
Ręcznie wolno wpisać weekend i święto — to robi zwykły wpis, nie wypełnianie.

Okno „Wypełnij miesiąc” (jak ``quickFillMonth`` Compassa): godziny dziennie
(domyślnie 8, najwyżej 8 — nadgodziny wpisuje się dniem, z uzasadnieniem)
i „nadpisz istniejące wpisy” — kasuje wpisy szkicu poza auto-wpisami płatnej
puli (``leave_paid`` należą do wniosku urlopowego, audyt Compassa HF-10)
i wypełnia miesiąc od nowa. Pół dnia urlopu dostaje najwyżej wolne 4 h.

Opis przy wypełnianiu: podany wprost > szablon osoby > domyślny opis Kadr
(rola+projekt > rola > projekt > globalny) > słowo formy: „Realizacja usług
zgodnie z umową” (B2B, zlecenie) albo „Praca standardowa” (UoP).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hr_profile import EmployeeProfile
from app.models.hr_time import (
    Timesheet,
    TimesheetEntry,
    TimesheetRoleDefault,
    TimesheetTemplate,
)
from app.models.user import User, UserRole
from app.services.hr import audit, time_retention
from app.services.hr.employment_terms import terms
from app.services.hr.time_access import Actor
from app.services.hr.time_calendar import month_calendar, month_range
from app.services.hr.time_entries import (
    STANDARD,
    TimeConflict,
    TimeError,
    TimeNotFound,
    clean_description,
    clean_hours,
    clean_project,
    employed_on,
    entries_of,
    leave_map,
    standard_description,
    sync_leave_paid,
)

MAX_TEMPLATE_NAME = 80
MAX_LABEL = 120


# ── Domyślne opisy (Kadry) ────────────────────────────────────────────────────


def _role_values(user: User) -> list[str]:
    return sorted(role.value for role in user.get_all_roles())


async def resolve_role_default(
    db: AsyncSession, user: User, project: Optional[str]
) -> Optional[TimesheetRoleDefault]:
    """Najbardziej szczegółowy aktywny opis: rola+projekt > rola > projekt > globalny."""

    roles = _role_values(user)
    project_match = (
        TimesheetRoleDefault.project.is_(None)
        if project is None
        else or_(
            TimesheetRoleDefault.project.is_(None),
            TimesheetRoleDefault.project == project,
        )
    )
    rows = list(
        await db.scalars(
            select(TimesheetRoleDefault).where(
                TimesheetRoleDefault.is_active.is_(True),
                or_(
                    TimesheetRoleDefault.applies_to_role.is_(None),
                    TimesheetRoleDefault.applies_to_role.in_(roles),
                ),
                project_match,
            )
        )
    )
    rows.sort(
        key=lambda row: (
            row.applies_to_role is None,
            row.project is None,
            row.sort_order,
            row.created_at,
            row.id,
        )
    )
    return rows[0] if rows else None


#: Role bez własnego domyślnego opisu: ``user`` wycofana, ``sourcer`` i ``tac``
#: to aliasy rekrutera (0411) — zostają w enumie tylko na czas migracji.
_RETIRED_ROLES = frozenset({"user", "sourcer", "tac"})


def _valid_role(raw: Optional[str]) -> Optional[str]:
    value = (raw or "").strip()
    if not value:
        return None
    if value not in {role.value for role in UserRole} or value in _RETIRED_ROLES:
        raise TimeError("Nieznana rola.")
    return value


def _clean_label(raw: Optional[str]) -> str:
    label = (raw or "").strip()
    if not label or len(label) > MAX_LABEL:
        raise TimeError(f"Etykieta musi mieć od 1 do {MAX_LABEL} znaków.")
    return label


async def list_role_defaults(db: AsyncSession) -> list[TimesheetRoleDefault]:
    rows = await db.scalars(
        select(TimesheetRoleDefault).order_by(
            TimesheetRoleDefault.sort_order,
            TimesheetRoleDefault.label,
            TimesheetRoleDefault.id,
        )
    )
    return list(rows)


async def save_role_default(
    db: AsyncSession,
    *,
    actor: User,
    values: dict[str, Any],
    default_id: Optional[int] = None,
) -> TimesheetRoleDefault:
    if default_id is None:
        row = TimesheetRoleDefault(created_by=actor.id)
        db.add(row)
        values = {"is_active": True, "sort_order": 0, **values}
        required = ("label", "default_description")
        if any(key not in values for key in required):
            raise TimeError("Podaj etykietę i opis.")
    else:
        found = await db.get(TimesheetRoleDefault, default_id)
        if found is None:
            raise TimeNotFound("Nie ma takiego opisu.")
        row = found
    if "label" in values:
        row.label = _clean_label(values["label"])
    if "default_description" in values:
        row.default_description = clean_description(values["default_description"])
    if "applies_to_role" in values:
        row.applies_to_role = _valid_role(values["applies_to_role"])
    if "project" in values:
        row.project = clean_project(values["project"])
    if values.get("is_active") is not None:
        row.is_active = bool(values["is_active"])
    if "sort_order" in values:
        row.sort_order = int(values["sort_order"] or 0)
    await db.flush()
    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=None,
        entity_type="timesheet_role_default",
        entity_id=row.id,
        action="role_default_saved",
        details={"fields": sorted(values)},
    )
    return row


async def delete_role_default(
    db: AsyncSession, *, actor: User, default_id: int
) -> None:
    row = await db.get(TimesheetRoleDefault, default_id)
    if row is None:
        raise TimeNotFound("Nie ma takiego opisu.")
    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=None,
        entity_type="timesheet_role_default",
        entity_id=row.id,
        action="role_default_deleted",
    )
    await db.delete(row)


# ── Szablony osoby ────────────────────────────────────────────────────────────


async def list_templates(db: AsyncSession, user_id: int) -> list[TimesheetTemplate]:
    rows = await db.scalars(
        select(TimesheetTemplate)
        .where(TimesheetTemplate.user_id == user_id)
        .order_by(TimesheetTemplate.sort_order, TimesheetTemplate.name)
    )
    return list(rows)


async def save_template(
    db: AsyncSession,
    *,
    user_id: int,
    values: dict[str, Any],
    template_id: Optional[int] = None,
) -> TimesheetTemplate:
    if template_id is None:
        if "name" not in values or "description" not in values:
            raise TimeError("Podaj nazwę i opis szablonu.")
        row = TimesheetTemplate(user_id=user_id)
        db.add(row)
    else:
        found = await db.get(TimesheetTemplate, template_id)
        if found is None or found.user_id != user_id:
            raise TimeNotFound("Nie ma takiego szablonu.")
        row = found
    if "name" in values:
        name = (values["name"] or "").strip()
        if not name or len(name) > MAX_TEMPLATE_NAME:
            raise TimeError(
                f"Nazwa szablonu musi mieć od 1 do {MAX_TEMPLATE_NAME} znaków."
            )
        row.name = name
    if "description" in values:
        row.description = clean_description(values["description"])
    if "project" in values:
        row.project = clean_project(values["project"])
    if "sort_order" in values:
        row.sort_order = int(values["sort_order"] or 0)
    try:
        async with db.begin_nested():
            await db.flush()
    except IntegrityError:
        raise TimeError("Masz już szablon o tej nazwie.") from None
    return row


async def delete_template(db: AsyncSession, *, user_id: int, template_id: int) -> None:
    row = await db.get(TimesheetTemplate, template_id)
    if row is None or row.user_id != user_id:
        raise TimeNotFound("Nie ma takiego szablonu.")
    await db.delete(row)


# ── Wypełnianie ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class OpenDay:
    day: date
    hours: Decimal


@dataclass(frozen=True)
class FillPlan:
    open_days: list[OpenDay]
    skipped_existing: int
    skipped_leave: int
    working_days: int


async def plan_open_days(
    db: AsyncSession,
    *,
    timesheet: Timesheet,
    subject: EmployeeProfile,
    hours_per_day: Decimal = STANDARD,
) -> FillPlan:
    """Dni robocze bez wpisów i bez urlopu (połowa urlopu = 4 h wolnego miejsca).

    Dzień dostaje ``hours_per_day``, ale nie więcej, niż zostawia urlop dnia —
    wypełnianie nigdy nie robi nadgodzin. Tylko dni zatrudnienia z kartoteki
    (od ``work_start_date`` do ``last_working_day``). Połowa płatnej puli B2B
    (auto-wpis 4 h) zostawia drugie 4 h do wypełnienia; auto-wpis nie zajmuje
    dnia jak ręczny wpis.
    """

    calendar = await month_calendar(db, timesheet.year, timesheet.month)
    start, end = month_range(timesheet.year, timesheet.month)
    leaves = await leave_map(
        db,
        user_id=timesheet.user_id,
        employment_type=subject.employment_type,
        start=start,
        end=end,
    )
    taken = {
        entry.work_date
        for entry in await entries_of(db, timesheet.id)
        if entry.source != "leave_paid"
    }
    open_days: list[OpenDay] = []
    skipped_existing = skipped_leave = working = 0
    for item in calendar:
        if not item.is_working_day or not employed_on(subject, item.day):
            continue
        working += 1
        day_leave = leaves.get(item.day)
        if day_leave is not None and (
            day_leave.blocks_day or day_leave.leave.status == "pending"
        ):
            skipped_leave += 1
            continue
        if item.day in taken:
            skipped_existing += 1
            continue
        if day_leave is None:
            room = STANDARD
        elif day_leave.paid_work:
            room = STANDARD - day_leave.paid_hours
        else:
            room = STANDARD - day_leave.occupied_hours
        open_days.append(OpenDay(day=item.day, hours=min(hours_per_day, room)))
    return FillPlan(
        open_days=open_days,
        skipped_existing=skipped_existing,
        skipped_leave=skipped_leave,
        working_days=working,
    )


async def fill_month(
    db: AsyncSession,
    *,
    timesheet: Timesheet,
    subject: EmployeeProfile,
    subject_user: User,
    actor: Actor,
    project: Optional[str],
    description: Optional[str],
    template_id: Optional[int],
    hours_per_day: Optional[Decimal] = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    hours = fill_hours(hours_per_day, form=subject.employment_type)
    project = clean_project(project)
    chosen: Optional[str] = None
    if description and description.strip():
        chosen = clean_description(description)
    elif template_id is not None:
        template = await db.get(TimesheetTemplate, template_id)
        if template is None or template.user_id != timesheet.user_id:
            raise TimeNotFound("Nie ma takiego szablonu.")
        chosen = template.description
        project = project or template.project
    else:
        default = await resolve_role_default(db, subject_user, project)
        if default is not None:
            chosen = default.default_description
            project = project or default.project
    text = chosen or standard_description(subject.employment_type)

    removed = 0
    if overwrite:
        removed = await _clear_for_overwrite(db, timesheet=timesheet, subject=subject)
    plan = await plan_open_days(
        db, timesheet=timesheet, subject=subject, hours_per_day=hours
    )
    for item in plan.open_days:
        db.add(
            TimesheetEntry(
                timesheet_id=timesheet.id,
                work_date=item.day,
                hours=item.hours,
                project=project,
                description=text,
                source="template",
                created_by=actor.user_id,
            )
        )
    await db.flush()
    return {
        "inserted": len(plan.open_days),
        "skipped_existing": plan.skipped_existing,
        "skipped_leave": plan.skipped_leave,
        "working_days": plan.working_days,
        "removed": removed,
        "hours_per_day": float(hours),
        "description": text,
        "project": project,
    }


def fill_hours(raw: Optional[Decimal], *, form: Optional[str] = None) -> Decimal:
    """Godziny dziennie w „Wypełnij miesiąc”: brak = 8, poza (0, 8] = 422."""

    if raw is None:
        return STANDARD
    hours = clean_hours(raw)
    if hours > STANDARD:
        raise TimeError(
            f"Wypełnianie wpisuje najwyżej {_fmt(STANDARD)} h dziennie — "
            f"{terms(form)['overtime_fill_note']}."
        )
    return hours


def _fmt(value: Decimal) -> str:
    return format(value.normalize(), "f").replace(".", ",")


async def _clear_for_overwrite(
    db: AsyncSession, *, timesheet: Timesheet, subject: EmployeeProfile
) -> int:
    """„Nadpisz istniejące wpisy”: kasuje wpisy szkicu poza ``leave_paid``.

    Auto-wpisy płatnej puli zostają (należą do wniosku urlopowego i niosą jego
    godziny), a ich dni wypełnianie i tak pomija. Po skasowaniu ręcznych godzin
    pół dnia płatnej puli może znów dostać auto-wpis — uzgadnia go
    ``sync_leave_paid``.
    """

    refusal = time_retention.delete_refusal(
        timesheet, current_form=subject.employment_type
    )
    if refusal is not None:
        raise TimeConflict(refusal)
    ids = list(
        await db.scalars(
            select(TimesheetEntry.id).where(
                TimesheetEntry.timesheet_id == timesheet.id,
                TimesheetEntry.source != "leave_paid",
            )
        )
    )
    if not ids:
        return 0
    await db.execute(
        delete(TimesheetEntry)
        .where(TimesheetEntry.id.in_(ids))
        .execution_options(synchronize_session="fetch")
    )
    # Jak ``delete_entry``: usunięte wpisy nie zostawiają wierszy, zmianę niesie
    # nagłówek (ponowny import z Compassa nie przywróci skasowanych w NEXUSIE).
    timesheet.updated_at = func.now()
    await db.flush()
    await sync_leave_paid(
        db, timesheet=timesheet, employment_type=subject.employment_type
    )
    return len(ids)


async def copy_previous(
    db: AsyncSession, *, timesheet: Timesheet, subject: EmployeeProfile, actor: Actor
) -> dict[str, Any]:
    """Opisy i projekty z ostatniego zaakceptowanego miesiąca (ten sam dzień miesiąca)."""

    source = await db.scalar(
        select(Timesheet)
        .where(
            Timesheet.user_id == timesheet.user_id,
            Timesheet.status == "approved",
            or_(
                Timesheet.year < timesheet.year,
                and_(
                    Timesheet.year == timesheet.year, Timesheet.month < timesheet.month
                ),
            ),
        )
        .order_by(Timesheet.year.desc(), Timesheet.month.desc())
        .limit(1)
    )
    if source is None:
        return {"source": None, "inserted": 0, "skipped_no_source": 0}
    by_day: dict[int, TimesheetEntry] = {}
    for entry in await entries_of(db, source.id):
        if entry.source != "leave_paid":
            by_day.setdefault(entry.work_date.day, entry)
    plan = await plan_open_days(db, timesheet=timesheet, subject=subject)
    inserted = skipped = 0
    for item in plan.open_days:
        origin = by_day.get(item.day.day)
        if origin is None:
            skipped += 1
            continue
        db.add(
            TimesheetEntry(
                timesheet_id=timesheet.id,
                work_date=item.day,
                hours=item.hours,
                project=origin.project,
                description=origin.description,
                source="template",
                created_by=actor.user_id,
            )
        )
        inserted += 1
    await db.flush()
    return {
        "source": {"year": source.year, "month": source.month},
        "inserted": inserted,
        "skipped_no_source": skipped,
    }
