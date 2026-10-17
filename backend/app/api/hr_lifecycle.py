"""Wejście i odejście — sprawy cyklu życia, zadania, przekazanie pracy.

Prefiks ``/api/hr/lifecycle`` (wpięty w ``app/main.py``). Każda trasa ma nazwaną bramkę
``require_hr_*`` (``app/api/hr_gates.py`` albo własną w tym module) i sprawdza
przełącznik modułu w ``app_settings['hr_modules']``.

* Kadry (``people_admin``) i admin — zakładanie i prowadzenie spraw,
  przejmujący, „Cofnij odejście”, „Wyłącz konto teraz”,
* ścieżki (O4, etap 3) — Kadry zmieniają „Zespół wewnętrzny”, head back
  office „Konsultant u klienta”, admin wszystkie; każdy z nich widzi obie,
* przełożony — sprawy swoich ludzi (odczyt, odhaczanie zadań),
* wykonawca — sprawy, w których ma zadanie (odczyt, odhaczanie swoich),
* wejście konsultanta (zakładka „Wejście” kontraktu, ``/contracts/{id}/entry``)
  — czytają ci, którzy czytają kontrakt (sekcja Delivery, podgląd Delivery,
  Delivery Lead tylko u swoich klientów); prowadzą (dopisanie pozycji,
  odhaczanie każdego zadania) opiekun kontraktu, DL klienta, head back office,
  Kadry i admin,
* pozostali — 403; wyłączony moduł — 404 (admin przechodzi zawsze).
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_onboarded_user
from app.api.hr_gates import ensure_module
from app.api.permission_access import DeliveryViewUser
from app.api.section_access import require_section_access
from app.core.database import get_db
from app.core.scheduling import business_today
from app.models.contract import Contract
from app.models.contract_onboarding import ContractOnboardingItem
from app.models.hr_lifecycle import LifecycleCase, LifecycleTask, LifecycleTemplate
from app.models.hr_profile import EmployeeProfile
from app.models.user import User, UserRole
from app.services.access_scope import (
    DL_CLIENT_OUT_OF_SCOPE_DETAIL,
    resolve_delivery_lead_client_ids,
)
from app.services.hr import lifecycle_entry, people
from app.services.hr import lifecycle_service as service
from app.services.hr.handover import WORK_KIND_BY_KEY, eligible_receivers
from app.services.hr.lifecycle_access import (
    can_toggle,
    case_scope,
    is_lifecycle_admin,
    owns_task,
)
from app.services.hr.lifecycle_templates import editable_audiences, is_back_office_head
from app.services.hr.modules import HrModule
from app.services.hr_foundation_schema import EmploymentType
from app.services.hr_lifecycle_schema import (
    DESCRIPTION_MAX,
    LIVE_CASE_STATUSES,
    MAX_OFFSET_AFTER,
    MAX_OFFSET_BEFORE,
    TRANSFER_KINDS,
)
from app.services.section_permissions import ProductSection

router = APIRouter()

MODULE = HrModule.lifecycle
ADMIN_DETAIL = "Wejście i odejście prowadzą Kadry."
TEMPLATE_EDITOR_DETAIL = (
    "Ścieżki wejścia i odejścia zmieniają Kadry (zespół wewnętrzny), head back "
    "office (konsultant u klienta) i administrator."
)
TEMPLATE_AUDIENCE_DETAIL = {
    "team": "Ścieżki zespołu wewnętrznego zmieniają Kadry i administrator.",
    "consultant": (
        "Ścieżki konsultanta u klienta zmienia head back office i administrator."
    ),
}
ENTRY_WRITER_DETAIL = (
    "Wejście konsultanta prowadzą opiekun kontraktu, Delivery Lead klienta, "
    "head back office, Kadry i administrator."
)
MIRRORED_TASK_DETAIL = (
    "To zadanie recepcja odhacza w Sprzęcie — lista wejścia pokazuje jego stan."
)
ENTRY_MISSING_DETAIL = {
    lifecycle_entry.REASON_NO_START: "Kontrakt nie ma daty startu.",
    lifecycle_entry.REASON_CLOSED: "Kontrakt jest zakończony albo unieważniony.",
    lifecycle_entry.REASON_PAST_START: "Start kontraktu już minął.",
    lifecycle_entry.REASON_NO_PATH: (
        "Nie ma aktywnej ścieżki „Konsultant u klienta” ani pakietu klienta."
    ),
    lifecycle_entry.REASON_MODULE_OFF: "Moduł „Wejście i odejście” jest wyłączony.",
}
_DELIVERY_SECTION = require_section_access(ProductSection.delivery)
NO_ACCESS_DETAIL = "Ta sprawa nie dotyczy Ciebie ani Twojego zespołu."
NOT_FOUND_DETAIL = "Nie ma takiej sprawy."

CaseKind = Literal["onboarding", "offboarding"]
Audience = Literal["team", "consultant"]
Category = Literal["accounts", "equipment", "documents", "training", "meeting", "other"]
AssigneeKind = Literal[
    "manager",
    "people_admin",
    "reception",
    "person",
    "it",
    "care_owner",
    "delivery_lead",
    "administration",
]
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
Location = Literal["onsite", "remote"]


def require_hr_lifecycle_admin():
    """Kadry albo admin (moduł włączony; admin przechodzi zawsze)."""

    async def _check(
        current_user: User = Depends(require_onboarded_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        await ensure_module(db, current_user, MODULE)
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
        await ensure_module(db, current_user, MODULE)
        return current_user

    return _check


def require_hr_lifecycle_template_editor():
    """Ścieżki: Kadry, head back office albo admin (zakres odbiorców — trasa)."""

    async def _check(
        current_user: User = Depends(require_onboarded_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        await ensure_module(db, current_user, MODULE)
        if not await editable_audiences(db, current_user):
            raise HTTPException(status.HTTP_403_FORBIDDEN, TEMPLATE_EDITOR_DETAIL)
        return current_user

    return _check


def require_hr_lifecycle_contract_reader():
    """Zakładka „Wejście” kontraktu: czytelnik kontraktu + moduł włączony.

    Sekcja Delivery i „Klienci, kontrakty i zamówienia: podgląd” jak zakładka
    „Opieka”; portfel Delivery Leada sprawdza trasa.
    """

    async def _check(
        viewer: DeliveryViewUser,
        current_user: User = Depends(_DELIVERY_SECTION),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        await ensure_module(db, current_user, MODULE)
        return current_user

    return _check


def require_hr_lifecycle_contract_writer():
    """Prowadzenie wejścia konsultanta: czytelnik kontraktu, który może je prowadzić.

    Kadry i admin; opiekunowie (DL, TCM) i head back office — to, czy prowadzą
    TEN kontrakt, sprawdza trasa (``case_scope``).
    """

    async def _check(
        viewer: DeliveryViewUser,
        current_user: User = Depends(_DELIVERY_SECTION),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        await ensure_module(db, current_user, MODULE)
        if is_lifecycle_admin(current_user) or current_user.has_any_role(
            UserRole.delivery_lead, UserRole.talent_community_manager
        ):
            return current_user
        if await is_back_office_head(db, current_user):
            return current_user
        raise HTTPException(status.HTTP_403_FORBIDDEN, ENTRY_WRITER_DETAIL)

    return _check


LifecycleAdmin = Annotated[User, Depends(require_hr_lifecycle_admin())]
LifecycleMember = Annotated[User, Depends(require_hr_lifecycle_member())]
TemplateEditor = Annotated[User, Depends(require_hr_lifecycle_template_editor())]
ContractEntryReader = Annotated[User, Depends(require_hr_lifecycle_contract_reader())]
ContractEntryWriter = Annotated[User, Depends(require_hr_lifecycle_contract_writer())]


# ── Modele żądań ─────────────────────────────────────────────────────────────


class ItemConditionsIn(BaseModel):
    """Warunki pozycji: forma współpracy, sprzęt od nas / od klienta, student."""

    employment_types: list[EmploymentType] = Field(default_factory=list, max_length=3)
    equipment: Optional[Literal["ours", "client"]] = None
    student: Optional[bool] = None


class TemplateItemIn(BaseModel):
    #: Id pozycji przy edycji szablonu — pozycja zmienia się w miejscu, więc
    #: zadania spraw z niej założone zostają przy niej.
    id: Optional[int] = None
    title: str = Field(min_length=1, max_length=200)
    category: Category = "other"
    assignee_kind: AssigneeKind = "people_admin"
    due_offset_days: int = Field(default=0, ge=-MAX_OFFSET_BEFORE, le=MAX_OFFSET_AFTER)
    description: Optional[str] = Field(default=None, max_length=DESCRIPTION_MAX)
    required: bool = True
    requires_file: bool = False
    conditions: ItemConditionsIn = Field(default_factory=ItemConditionsIn)


class TemplateIn(BaseModel):
    kind: CaseKind
    audience: Audience = "team"
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
    description: Optional[str] = Field(default=None, max_length=DESCRIPTION_MAX)


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


async def _template_out(
    db: AsyncSession, template: LifecycleTemplate, audiences: frozenset[str]
) -> dict:
    return service.template_payload(
        template,
        await service.template_items(db, template.id),
        can_edit=template.audience in audiences,
        live_cases_behind=await service.live_cases_behind(db, template),
    )


@router.get("/templates")
async def list_templates(
    current_user: TemplateEditor,
    kind: Optional[CaseKind] = None,
    audience: Optional[Audience] = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    audiences = await editable_audiences(db, current_user)
    rows = await service.templates(db, kind=kind, audience=audience)
    return {"items": [await _template_out(db, row, audiences) for row in rows]}


async def _save_template(
    db: AsyncSession, payload: TemplateIn, actor: User, template_id: Optional[int]
) -> dict:
    audiences = await editable_audiences(db, actor)
    if payload.audience not in audiences:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, TEMPLATE_AUDIENCE_DETAIL[payload.audience]
        )
    if template_id is not None:
        existing = await db.get(LifecycleTemplate, template_id)
        if existing is not None and existing.audience not in audiences:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, TEMPLATE_AUDIENCE_DETAIL[existing.audience]
            )
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
            audience=payload.audience,
            items=[
                service.ItemInput(
                    item.title,
                    item.category,
                    item.assignee_kind,
                    item.due_offset_days,
                    item.id,
                    item.description,
                    item.required,
                    item.requires_file,
                    item.conditions.model_dump(exclude_none=True),
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
    return await _template_out(db, template, audiences)


@router.post("/templates", status_code=status.HTTP_201_CREATED)
async def create_template(
    payload: TemplateIn,
    current_user: TemplateEditor,
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await _save_template(db, payload, current_user, None)


@router.put("/templates/{template_id}")
async def update_template(
    template_id: int,
    payload: TemplateIn,
    current_user: TemplateEditor,
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await _save_template(db, payload, current_user, template_id)


@router.post("/templates/{template_id}/catch-up")
async def catch_up_template(
    template_id: int,
    current_user: TemplateEditor,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """„Dociągnij do trwających” — pozycje nowej wersji w sprawach na starszej (O5)."""

    template = await db.get(LifecycleTemplate, template_id)
    if template is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie ma takiego szablonu.")
    audiences = await editable_audiences(db, current_user)
    if template.audience not in audiences:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, TEMPLATE_AUDIENCE_DETAIL[template.audience]
        )
    result = await service.catch_up(db, template, actor=current_user)
    await db.commit()
    return {**result, "template": await _template_out(db, template, audiences)}


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
    audience: Audience = Query(
        "team",
        description="Zespół wewnętrzny (Kadry) albo wejścia konsultantów przy kontraktach.",
    ),
    db: AsyncSession = Depends(get_db),
) -> dict:
    statement = (
        select(LifecycleCase)
        .where(LifecycleCase.audience == audience)
        .order_by(LifecycleCase.created_at.desc())
    )
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
    if payload.status is not None and task.id in await service.task_mirrors(
        db, case, [task]
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, MIRRORED_TASK_DETAIL)
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
    mirrors: dict[int, dict[int, dict]] = {}
    for task, case in rows:
        if not owns_task(current_user, task):
            continue
        if case.audience == "consultant":
            if case.id not in mirrors:
                mirrors[case.id] = await service.task_mirrors(
                    db, case, await service.case_tasks(db, case.id)
                )
            if task.id in mirrors[case.id]:
                continue  # zestaw sprzętu recepcja widzi w Sprzęcie
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


# ── Wejście konsultanta: zakładka „Wejście” kontraktu (etap 3, M6) ───────────


async def _entry_contract(db: AsyncSession, contract_id: int, user: User) -> Contract:
    contract = await db.get(Contract, contract_id)
    if contract is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie ma takiego kontraktu.")
    allowed = await resolve_delivery_lead_client_ids(user, db)
    if allowed is not None and contract.client_id not in allowed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, DL_CLIENT_OUT_OF_SCOPE_DETAIL)
    return contract


async def _entry_scope(db: AsyncSession, user: User, case: LifecycleCase) -> str:
    scope = await case_scope(db, user, case)
    return "viewer" if scope == "none" else scope


async def _can_lead_entry(db: AsyncSession, user: User, contract: Contract) -> bool:
    return is_lifecycle_admin(
        user
    ) or user.id in await lifecycle_entry.consultant_leads(db, contract.id)


async def _entry_view(db: AsyncSession, contract: Contract, user: User) -> dict:
    case = await lifecycle_entry.latest_contract_entry(db, contract.id)
    payload = None
    if case is not None:
        payload = await service.case_payload(
            db,
            case,
            viewer=user,
            scope=await _entry_scope(db, user, case),
            with_work=False,
        )
    legacy = int(
        await db.scalar(
            select(func.count())
            .select_from(ContractOnboardingItem)
            .where(ContractOnboardingItem.contract_id == contract.id)
        )
        or 0
    )
    reason = None
    if case is None:
        reason = lifecycle_entry.missing_reason(contract, business_today())
    can_lead = await _can_lead_entry(db, user, contract)
    from app.services.hr.modules import load_modules  # noqa: PLC0415

    module_on = bool((await load_modules(db)).get(MODULE))
    if not module_on and case is None:
        reason = lifecycle_entry.REASON_MODULE_OFF
    return {
        "contract_id": contract.id,
        # Admin widzi zakładkę i przy wyłączonym module — wtedy stara lista.
        "module_on": module_on,
        "start_date": contract.start_date,
        "case": payload,
        "composition": await lifecycle_entry.composition(db, contract),
        "missing_reason": reason,
        "can_create": case is None
        and can_lead
        and reason
        in (lifecycle_entry.REASON_PAST_START, lifecycle_entry.REASON_NO_PATH),
        "can_add_task": bool(payload and payload["can_add_task"]),
        "legacy_items": legacy,
    }


@router.get("/contracts/{contract_id}/entry")
async def contract_entry(
    contract_id: int,
    current_user: ContractEntryReader,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Lista wejścia konsultanta, karta „Z czego to powstało” i stare pozycje."""

    contract = await _entry_contract(db, contract_id, current_user)
    return await _entry_view(db, contract, current_user)


@router.post("/contracts/{contract_id}/entry", status_code=status.HTTP_201_CREATED)
async def create_contract_entry(
    contract_id: int,
    current_user: ContractEntryWriter,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """„Załóż listę wejścia” — także dla kontraktu ze startem w przeszłości."""

    contract = await _entry_contract(db, contract_id, current_user)
    if not await _can_lead_entry(db, current_user, contract):
        raise HTTPException(status.HTTP_403_FORBIDDEN, ENTRY_WRITER_DETAIL)
    case = await lifecycle_entry.ensure_contract_entry(
        db, contract, force=True, actor_id=current_user.id
    )
    if case is None:
        reason = lifecycle_entry.missing_reason(contract, business_today())
        raise HTTPException(status.HTTP_409_CONFLICT, ENTRY_MISSING_DETAIL[reason])
    from app.services.admin_cases.hooks import sync_entry_checklist  # noqa: PLC0415

    await sync_entry_checklist(db, case)
    await db.commit()
    return await _entry_view(db, contract, current_user)


@router.post(
    "/contracts/{contract_id}/entry/tasks", status_code=status.HTTP_201_CREATED
)
async def add_contract_entry_task(
    contract_id: int,
    payload: TaskIn,
    current_user: ContractEntryWriter,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """„Dodaj pozycję” do wejścia konsultanta (opiekun, DL, head back office)."""

    contract = await _entry_contract(db, contract_id, current_user)
    case = await lifecycle_entry.contract_entry_case(db, contract.id, lock=True)
    if case is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Ten kontrakt nie ma listy wejścia w toku."
        )
    if await case_scope(db, current_user, case) not in ("admin", "manager"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, ENTRY_WRITER_DETAIL)
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
            description=payload.description,
        )
    except service.LifecycleError as exc:
        raise _unprocessable(exc) from exc
    except service.LifecycleConflict as exc:
        raise _conflict(exc) from exc
    await db.commit()
    return await _entry_view(db, contract, current_user)
