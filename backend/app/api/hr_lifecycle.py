"""Wejście i odejście — sprawy cyklu życia, zadania, przekazanie pracy.

Prefiks ``/api/hr/lifecycle`` (wpięty w ``app/main.py``). Każda trasa ma nazwaną bramkę
``require_hr_*`` (``app/api/hr_gates.py`` albo własną w tym module) i sprawdza
przełącznik modułu w ``app_settings['hr_modules']``.

* Kadry (``people_admin``) i admin — szablony, zakładanie i prowadzenie spraw,
  przejmujący, „Cofnij odejście”, „Wyłącz konto teraz”,
* przełożony — sprawy swoich ludzi (odczyt, odhaczanie zadań),
* wykonawca — sprawy, w których ma zadanie (odczyt, odhaczanie swoich),
* pozostali — 403; wyłączony moduł — 404 (admin przechodzi zawsze).
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_onboarded_user
from app.api.hr_gates import MODULE_DISABLED_DETAIL
from app.core.database import get_db
from app.core.scheduling import business_today
from app.models.hr_lifecycle import LifecycleCase, LifecycleTask, LifecycleTemplate
from app.models.hr_profile import EmployeeProfile
from app.models.user import User
from app.services.hr import modules as hr_modules
from app.services.hr import people
from app.services.hr import lifecycle_service as service
from app.services.hr.handover import WORK_KIND_BY_KEY, eligible_receivers
from app.services.hr.lifecycle_access import (
    can_toggle,
    case_scope,
    is_lifecycle_admin,
    owns_task,
)
from app.services.hr_lifecycle_schema import (
    LIVE_CASE_STATUSES,
    MAX_OFFSET_AFTER,
    MAX_OFFSET_BEFORE,
    TRANSFER_KINDS,
)

router = APIRouter()

MODULE = "lifecycle"
ADMIN_DETAIL = "Wejście i odejście prowadzą Kadry."
NO_ACCESS_DETAIL = "Ta sprawa nie dotyczy Ciebie ani Twojego zespołu."
NOT_FOUND_DETAIL = "Nie ma takiej sprawy."

CaseKind = Literal["onboarding", "offboarding"]
Category = Literal["accounts", "equipment", "documents", "training", "meeting", "other"]
AssigneeKind = Literal["manager", "people_admin", "reception", "person", "it"]
ExitInitiator = Literal["employee", "company", "mutual"]
ExitReason = Literal[
    "new_opportunity",
    "compensation",
    "role_fit",
    "management",
    "work_life_balance",
    "career_growth",
    "relocation",
    "contract_end",
    "other",
]
EmploymentType = Literal["uop", "b2b", "zlecenie"]
Location = Literal["onsite", "remote"]


async def _module_open(db: AsyncSession, user: User) -> None:
    loaded = await hr_modules.load_modules(db)
    if not hr_modules.module_open_for(user, loaded, MODULE):
        raise HTTPException(status.HTTP_404_NOT_FOUND, MODULE_DISABLED_DETAIL)


def require_hr_lifecycle_admin():
    """Kadry albo admin (moduł włączony; admin przechodzi zawsze)."""

    async def _check(
        current_user: User = Depends(require_onboarded_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        await _module_open(db, current_user)
        if not is_lifecycle_admin(current_user):
            raise HTTPException(status.HTTP_403_FORBIDDEN, ADMIN_DETAIL)
        return current_user

    return _check


def require_hr_lifecycle_member():
    """Zalogowane konto przy włączonym module; zakres sprawdza trasa."""

    async def _check(
        current_user: User = Depends(require_onboarded_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        await _module_open(db, current_user)
        return current_user

    return _check


LifecycleAdmin = Annotated[User, Depends(require_hr_lifecycle_admin())]
LifecycleMember = Annotated[User, Depends(require_hr_lifecycle_member())]


# ── Modele żądań ─────────────────────────────────────────────────────────────


class TemplateItemIn(BaseModel):
    #: Id pozycji przy edycji szablonu — pozycja zmienia się w miejscu, więc
    #: zadania spraw z niej założone zostają przy niej.
    id: Optional[int] = None
    title: str = Field(min_length=1, max_length=200)
    category: Category = "other"
    assignee_kind: AssigneeKind = "people_admin"
    due_offset_days: int = Field(default=0, ge=-MAX_OFFSET_BEFORE, le=MAX_OFFSET_AFTER)


class TemplateIn(BaseModel):
    kind: CaseKind
    name: str = Field(min_length=1, max_length=160)
    is_active: bool = True
    employment_type: Optional[EmploymentType] = None
    department: Optional[str] = Field(default=None, max_length=200)
    items: list[TemplateItemIn] = Field(default_factory=list, max_length=60)


class PreviewIn(BaseModel):
    kind: CaseKind
    anchor: date
    template_id: Optional[int] = None
    employment_type: Optional[EmploymentType] = None
    department: Optional[str] = Field(default=None, max_length=200)


class OnboardingProfileIn(BaseModel):
    employment_type: Optional[EmploymentType] = None
    hired_on: Optional[date] = None
    default_location: Optional[Location] = None
    timesheet_required: Optional[bool] = None
    can_log_overtime: Optional[bool] = None
    job_title: Optional[str] = Field(default=None, max_length=200)
    department: Optional[str] = Field(default=None, max_length=200)
    phone: Optional[str] = Field(default=None, max_length=64)


class OnboardingIn(BaseModel):
    user_id: Optional[int] = None
    email: Optional[EmailStr] = None
    name: Optional[str] = Field(default=None, max_length=255)
    start_date: date
    template_id: Optional[int] = None
    manager_user_id: Optional[int] = None
    profile: OnboardingProfileIn = Field(default_factory=OnboardingProfileIn)
    start: bool = False


class OffboardingIn(BaseModel):
    user_id: int
    last_working_day: date
    exit_initiator: Optional[ExitInitiator] = None
    exit_reason: Optional[ExitReason] = None
    exit_note: Optional[str] = Field(default=None, max_length=500)
    manager_user_id: Optional[int] = None
    template_id: Optional[int] = None
    start: bool = False


class CaseUpdateIn(BaseModel):
    start_date: Optional[date] = None
    last_working_day: Optional[date] = None
    manager_user_id: Optional[int] = None
    template_id: Optional[int] = None
    exit_initiator: Optional[ExitInitiator] = None
    exit_reason: Optional[ExitReason] = None
    exit_note: Optional[str] = Field(default=None, max_length=500)
    pending_name: Optional[str] = Field(default=None, max_length=255)
    profile: Optional[OnboardingProfileIn] = None


class HandoversIn(BaseModel):
    receivers: dict[str, Optional[int]]


class TaskIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    category: Category = "other"
    assignee_kind: AssigneeKind = "people_admin"
    assignee_user_id: Optional[int] = None
    due_date: Optional[date] = None


class TaskUpdateIn(BaseModel):
    status: Optional[Literal["open", "done", "skipped"]] = None
    note: Optional[str] = Field(default=None, max_length=500)


# ── Pomocnicze ───────────────────────────────────────────────────────────────


def _unprocessable(exc: Exception) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))


def _conflict(exc: Exception) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, str(exc))


async def _case_or_404(
    db: AsyncSession, case_id: int, *, lock: bool = False
) -> LifecycleCase:
    statement = select(LifecycleCase).where(LifecycleCase.id == case_id)
    if lock:
        statement = statement.with_for_update()
    case = await db.scalar(statement)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND_DETAIL)
    return case


async def _scoped_case(
    db: AsyncSession, case_id: int, user: User
) -> tuple[LifecycleCase, str]:
    case = await _case_or_404(db, case_id)
    scope = await case_scope(db, user, case)
    if scope == "none":
        raise HTTPException(status.HTTP_403_FORBIDDEN, NO_ACCESS_DETAIL)
    return case, scope


async def _detail(db: AsyncSession, case: LifecycleCase, user: User) -> dict:
    scope = await case_scope(db, user, case)
    return await service.case_payload(db, case, viewer=user, scope=scope)


# ── Szablony ─────────────────────────────────────────────────────────────────


@router.get("/templates")
async def list_templates(
    _: LifecycleAdmin,
    kind: Optional[CaseKind] = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    rows = await service.templates(db, kind=kind)
    return {
        "items": [
            service.template_payload(row, await service.template_items(db, row.id))
            for row in rows
        ]
    }


async def _save_template(
    db: AsyncSession, payload: TemplateIn, actor: User, template_id: Optional[int]
) -> dict:
    try:
        template = await service.save_template(
            db,
            actor=actor,
            template_id=template_id,
            kind=payload.kind,
            name=payload.name,
            is_active=payload.is_active,
            employment_type=payload.employment_type,
            department=payload.department,
            items=[
                service.ItemInput(
                    item.title,
                    item.category,
                    item.assignee_kind,
                    item.due_offset_days,
                    item.id,
                )
                for item in payload.items
            ],
        )
    except service.LifecycleError as exc:
        raise _unprocessable(exc) from exc
    except LookupError as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Nie ma takiego szablonu."
        ) from exc
    await db.commit()
    return service.template_payload(
        template, await service.template_items(db, template.id)
    )


@router.post("/templates", status_code=status.HTTP_201_CREATED)
async def create_template(
    payload: TemplateIn,
    current_user: LifecycleAdmin,
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await _save_template(db, payload, current_user, None)


@router.put("/templates/{template_id}")
async def update_template(
    template_id: int,
    payload: TemplateIn,
    current_user: LifecycleAdmin,
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await _save_template(db, payload, current_user, template_id)


@router.post("/preview")
async def preview_tasks(
    payload: PreviewIn, _: LifecycleAdmin, db: AsyncSession = Depends(get_db)
) -> dict:
    """Zadania z terminami dla daty startu albo ostatniego dnia — bez zapisu."""

    if payload.template_id is not None:
        template = await db.get(LifecycleTemplate, payload.template_id)
        if template is None or template.kind != payload.kind:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Wybrany szablon nie pasuje do tej sprawy.",
            )
    else:
        template = await service.pick_template(
            db,
            payload.kind,
            employment_type=payload.employment_type,
            department=payload.department,
        )
    if template is None:
        return {"template_id": None, "template_name": None, "tasks": []}
    planned = await service.plan_tasks(
        db, await service.template_items(db, template.id), payload.anchor
    )
    return {
        "template_id": template.id,
        "template_name": template.name,
        "tasks": [
            {
                "title": task.title,
                "category": task.category,
                "assignee_kind": task.assignee_kind,
                "due_date": task.due_date,
            }
            for task in planned
        ],
    }


# ── Sprawy ───────────────────────────────────────────────────────────────────


@router.get("/cases")
async def list_cases(
    current_user: LifecycleMember,
    kind: Optional[CaseKind] = None,
    live: bool = Query(True, description="Tylko szkice i sprawy w toku."),
    db: AsyncSession = Depends(get_db),
) -> dict:
    statement = select(LifecycleCase).order_by(LifecycleCase.created_at.desc())
    if kind is not None:
        statement = statement.where(LifecycleCase.kind == kind)
    if live:
        statement = statement.where(LifecycleCase.status.in_(LIVE_CASE_STATUSES))
    if not is_lifecycle_admin(current_user):
        reports = select(EmployeeProfile.user_id).where(
            EmployeeProfile.manager_user_id == current_user.id
        )
        if not await db.scalar(reports.limit(1)) and not await db.scalar(
            select(LifecycleCase.id)
            .where(LifecycleCase.manager_user_id == current_user.id)
            .limit(1)
        ):
            raise HTTPException(status.HTTP_403_FORBIDDEN, ADMIN_DETAIL)
        statement = statement.where(
            or_(
                LifecycleCase.manager_user_id == current_user.id,
                LifecycleCase.user_id.in_(reports),
            )
        )
    rows = list(await db.scalars(statement.limit(200)))
    items = []
    for case in rows:
        scope = await case_scope(db, current_user, case)
        payload = await service.case_payload(
            db, case, viewer=current_user, scope=scope, with_work=False
        )
        payload.pop("tasks", None)
        items.append(payload)
    return {"items": items, "total": len(items)}


@router.get("/cases/{case_id}")
async def get_case(
    case_id: int, current_user: LifecycleMember, db: AsyncSession = Depends(get_db)
) -> dict:
    case, scope = await _scoped_case(db, case_id, current_user)
    return await service.case_payload(db, case, viewer=current_user, scope=scope)


@router.post("/cases/onboarding", status_code=status.HTTP_201_CREATED)
async def create_onboarding(
    payload: OnboardingIn,
    current_user: LifecycleAdmin,
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        case = await service.create_onboarding(
            db,
            actor=current_user,
            user_id=payload.user_id,
            email=payload.email,
            name=payload.name,
            start_date=payload.start_date,
            template_id=payload.template_id,
            manager_user_id=payload.manager_user_id,
            profile_values=payload.profile.model_dump(exclude_none=True),
        )
        if payload.start:
            await service.start_case(db, case, actor=current_user)
    except service.LifecycleError as exc:
        raise _unprocessable(exc) from exc
    except service.LifecycleConflict as exc:
        raise _conflict(exc) from exc
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie ma takiego konta.") from exc
    await db.commit()
    return await _detail(db, case, current_user)


@router.post("/cases/offboarding", status_code=status.HTTP_201_CREATED)
async def create_offboarding(
    payload: OffboardingIn,
    current_user: LifecycleAdmin,
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        case = await service.create_offboarding(
            db,
            actor=current_user,
            user_id=payload.user_id,
            last_working_day=payload.last_working_day,
            exit_initiator=payload.exit_initiator,
            exit_reason=payload.exit_reason,
            exit_note=payload.exit_note,
            manager_user_id=payload.manager_user_id,
            manager_given="manager_user_id" in payload.model_fields_set,
            template_id=payload.template_id,
        )
        if payload.start:
            await service.start_case(db, case, actor=current_user)
    except service.LifecycleError as exc:
        raise _unprocessable(exc) from exc
    except service.LifecycleConflict as exc:
        raise _conflict(exc) from exc
    except LookupError as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Ta osoba nie ma kartoteki w NEXUSIE."
        ) from exc
    await db.commit()
    return await _detail(db, case, current_user)


@router.patch("/cases/{case_id}")
async def update_case(
    case_id: int,
    payload: CaseUpdateIn,
    current_user: LifecycleAdmin,
    db: AsyncSession = Depends(get_db),
) -> dict:
    case = await _case_or_404(db, case_id, lock=True)
    values = payload.model_dump(exclude_unset=True)
    if "profile" in values:
        values["profile_values"] = (
            payload.profile.model_dump(exclude_none=True) if payload.profile else None
        )
        values.pop("profile")
    try:
        await service.update_case(db, case, actor=current_user, values=values)
    except service.LifecycleError as exc:
        raise _unprocessable(exc) from exc
    except service.LifecycleConflict as exc:
        raise _conflict(exc) from exc
    await db.commit()
    return await _detail(db, case, current_user)


async def _transition(db: AsyncSession, case_id: int, user: User, action: str) -> dict:
    case = await _case_or_404(db, case_id, lock=True)
    try:
        if action == "start":
            await service.start_case(db, case, actor=user)
        elif action == "cancel":
            await service.cancel_case(db, case, actor=user)
        else:
            await service.complete_case(db, case, actor=user)
    except service.LifecycleError as exc:
        raise _unprocessable(exc) from exc
    except service.LifecycleConflict as exc:
        raise _conflict(exc) from exc
    except LookupError as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Ta osoba nie ma kartoteki w NEXUSIE."
        ) from exc
    await db.commit()
    return await _detail(db, case, user)


@router.post("/cases/{case_id}/start")
async def start_case(
    case_id: int, current_user: LifecycleAdmin, db: AsyncSession = Depends(get_db)
) -> dict:
    return await _transition(db, case_id, current_user, "start")


@router.post("/cases/{case_id}/cancel")
async def cancel_case(
    case_id: int, current_user: LifecycleAdmin, db: AsyncSession = Depends(get_db)
) -> dict:
    return await _transition(db, case_id, current_user, "cancel")


@router.post("/cases/{case_id}/complete")
async def complete_case(
    case_id: int, current_user: LifecycleAdmin, db: AsyncSession = Depends(get_db)
) -> dict:
    return await _transition(db, case_id, current_user, "complete")


@router.post("/cases/{case_id}/deactivate-now")
async def deactivate_now(
    case_id: int,
    current_user: LifecycleAdmin,
    despite_handover: bool = Query(
        False,
        description="Wyłącz konto, choć część pracy nie została przekazana.",
    ),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """„Wyłącz konto teraz” — jedno konto, decyzja człowieka, w dniu wyłączenia.

    Droga dla przebiegu zatrzymanego bezpiecznikiem masowego odejścia albo
    czekającego na przekazanie pracy; przed ``deactivate_on`` odmawia (konto
    osoby, która jeszcze pracuje). Nieprzekazana praca = 409, chyba że Kadry
    wyłączają „mimo to” (``despite_handover``).
    """

    case = await _case_or_404(db, case_id, lock=True)
    try:
        await service.deactivate_now(
            db, case, actor=current_user, despite_handover=despite_handover
        )
    except service.LifecycleConflict as exc:
        raise _conflict(exc) from exc
    await db.commit()
    return await _detail(db, case, current_user)


@router.put("/cases/{case_id}/handovers")
async def set_handovers(
    case_id: int,
    payload: HandoversIn,
    current_user: LifecycleAdmin,
    db: AsyncSession = Depends(get_db),
) -> dict:
    case = await _case_or_404(db, case_id, lock=True)
    try:
        await service.set_receivers(
            db, case, actor=current_user, receivers=payload.receivers
        )
    except service.LifecycleError as exc:
        raise _unprocessable(exc) from exc
    except service.LifecycleConflict as exc:
        raise _conflict(exc) from exc
    await db.commit()
    return await _detail(db, case, current_user)


@router.get("/cases/{case_id}/receivers")
async def list_receivers(
    case_id: int,
    current_user: LifecycleAdmin,
    kind: str = Query(...),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if kind not in TRANSFER_KINDS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Nieznany rodzaj pracy."
        )
    case = await _case_or_404(db, case_id)
    return {
        "kind": kind,
        "label": WORK_KIND_BY_KEY[kind].label,
        "items": await eligible_receivers(
            db,
            kind,
            leaver_id=case.user_id,
            handover_day=case.last_working_day,
        ),
    }


@router.post("/cases/{case_id}/tasks", status_code=status.HTTP_201_CREATED)
async def add_task(
    case_id: int,
    payload: TaskIn,
    current_user: LifecycleAdmin,
    db: AsyncSession = Depends(get_db),
) -> dict:
    case = await _case_or_404(db, case_id, lock=True)
    try:
        await service.add_task(
            db,
            case,
            actor=current_user,
            title=payload.title,
            category=payload.category,
            assignee_kind=payload.assignee_kind,
            assignee_user_id=payload.assignee_user_id,
            due_date=payload.due_date,
        )
    except service.LifecycleError as exc:
        raise _unprocessable(exc) from exc
    except service.LifecycleConflict as exc:
        raise _conflict(exc) from exc
    await db.commit()
    return await _detail(db, case, current_user)


@router.patch("/tasks/{task_id}")
async def update_task(
    task_id: int,
    payload: TaskUpdateIn,
    current_user: LifecycleMember,
    db: AsyncSession = Depends(get_db),
) -> dict:
    task = await db.scalar(
        select(LifecycleTask).where(LifecycleTask.id == task_id).with_for_update()
    )
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie ma takiego zadania.")
    case, scope = await _scoped_case(db, task.case_id, current_user)
    if not can_toggle(scope, current_user, task):  # type: ignore[arg-type]
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "To zadanie odhacza jego wykonawca albo Kadry."
        )
    try:
        await service.update_task(
            db,
            task,
            case,
            actor=current_user,
            status=payload.status,
            note=payload.note,
            note_given="note" in payload.model_fields_set,
        )
    except service.LifecycleConflict as exc:
        raise _conflict(exc) from exc
    await db.commit()
    return await service.case_payload(
        db, case, viewer=current_user, scope=scope, with_work=False
    )


@router.get("/my-tasks")
async def my_tasks(
    current_user: LifecycleMember, db: AsyncSession = Depends(get_db)
) -> dict:
    """Otwarte zadania, które wykonuję (osobiście albo z puli), w sprawach w toku."""

    rows = (
        await db.execute(
            select(LifecycleTask, LifecycleCase)
            .join(LifecycleCase, LifecycleCase.id == LifecycleTask.case_id)
            .where(
                LifecycleCase.status == "active",
                LifecycleTask.status == "open",
            )
            .order_by(LifecycleTask.due_date.asc().nulls_last(), LifecycleTask.id)
        )
    ).all()
    today = business_today()
    items = []
    for task, case in rows:
        if not owns_task(current_user, task):
            continue
        items.append(
            {
                "task_id": task.id,
                "case_id": case.id,
                "kind": case.kind,
                "person_name": await service.person_name(db, case),
                "title": task.title,
                "due_date": task.due_date,
                "overdue": task.due_date is not None and task.due_date < today,
                "link": service.case_link(case),
            }
        )
    return {"items": items, "total": len(items)}


@router.get("/people/{user_id}/summary")
async def person_summary(
    user_id: int, current_user: LifecycleMember, db: AsyncSession = Depends(get_db)
) -> dict:
    """Sekcja „Wejście / odejście” w kartotece: ostatnia sprawa osoby."""

    case = await service.latest_case_for(db, user_id)
    if case is None:
        if is_lifecycle_admin(current_user) or current_user.id == user_id:
            return {"case": None, "can_manage": is_lifecycle_admin(current_user)}
        profile = await people.profile_of(db, user_id)
        if profile is not None and profile.manager_user_id == current_user.id:
            return {"case": None, "can_manage": False}
        raise HTTPException(status.HTTP_403_FORBIDDEN, NO_ACCESS_DETAIL)
    scope = await case_scope(db, current_user, case)
    if scope == "none" and current_user.id != user_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, NO_ACCESS_DETAIL)
    payload = await service.case_payload(
        db,
        case,
        viewer=current_user,
        scope=scope if scope != "none" else "assignee",
        with_work=False,
    )
    return {
        "case": {
            "id": payload["id"],
            "kind": payload["kind"],
            "status": payload["status"],
            "start_date": payload["start_date"],
            "last_working_day": payload["last_working_day"],
            "deactivate_on": payload["deactivate_on"],
            "handover_executed_at": payload["handover_executed_at"],
            "account_closed_at": payload["account_closed_at"],
            "account_close_result": payload["account_close_result"],
            "progress": payload["progress"],
            "link": service.case_link(case),
        },
        "can_manage": is_lifecycle_admin(current_user),
    }
