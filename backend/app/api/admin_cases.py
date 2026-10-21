"""Sprawy administracja@ — kanban, wiadomości, komentarze.

Prefiks ``/api/cases`` (wpięty w ``app/main.py``). Każda trasa ma nazwaną bramkę
``require_hr_*`` (``app/api/hr_gates.py`` albo własną w tym module) i sprawdza
przełącznik modułu w ``app_settings['hr_modules']``.

* obsługa skrzynki — uprawnienie „Sprawy” (``cases``) albo admin: wszystko,
* osoba przypisana do sprawy bez uprawnienia — lista i szczegół tylko swoich
  spraw oraz komentarz; bez zmian w sprawie,
* reszta — 403; wyłączony moduł — 404 (admin przechodzi zawsze).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_onboarded_user
from app.api.hr_gates import ensure_module
from app.core.database import get_db
from app.models.user import User
from app.services.action_permissions import ProductAction
from app.services.admin_cases import queries, service
from app.services.hr.modules import HrModule
from app.services.permission_denial import permission_denied

router = APIRouter()

NO_ACCESS_DETAIL = (
    "Sprawy administracja@ widzą osoby z uprawnieniem „Sprawy” "
    "i osoby przypisane do sprawy."
)
CASE_FORBIDDEN_DETAIL = "Ta sprawa nie jest przypisana do Ciebie."
CASE_NOT_FOUND_DETAIL = "Nie ma takiej sprawy."

Area = Literal[
    "onboarding", "offboarding", "negotiation", "administration", "marketing", "other"
]
Priority = Literal["P1", "P2", "P3"]
Status = Literal["new", "in_progress", "waiting", "done", "closed"]


def require_hr_cases_handler():
    """Obsługa skrzynki: uprawnienie „Sprawy” (admin zawsze) i włączony moduł."""

    async def _check(
        current_user: User = Depends(require_onboarded_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        if not service.is_handler(current_user):
            raise permission_denied(ProductAction.cases)
        await ensure_module(db, current_user, HrModule.cases)
        return current_user

    _check.required_permissions = (ProductAction.cases,)
    return _check


def require_hr_cases_reader():
    """Obsługa skrzynki albo osoba przypisana do co najmniej jednej sprawy."""

    async def _check(
        current_user: User = Depends(require_onboarded_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        await ensure_module(db, current_user, HrModule.cases)
        if service.is_handler(current_user):
            return current_user
        if await service.has_assigned_cases(db, current_user.id):
            return current_user
        raise HTTPException(status.HTTP_403_FORBIDDEN, NO_ACCESS_DETAIL)

    return _check


CasesHandler = Annotated[User, Depends(require_hr_cases_handler())]
CasesReader = Annotated[User, Depends(require_hr_cases_reader())]


class ChecklistItem(BaseModel):
    text: str = Field(max_length=300)
    done: bool = False


class CaseCreate(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    area: Area = "administration"
    priority: Priority = "P2"
    due_on: Optional[date] = None
    follow_up_on: Optional[date] = None
    assignee_user_id: Optional[int] = None
    description: Optional[str] = Field(default=None, max_length=20_000)
    checklist: list[ChecklistItem] = Field(default_factory=list, max_length=50)
    contract_id: Optional[int] = None
    subject_user_id: Optional[int] = None


class CaseUpdate(BaseModel):
    title: Optional[str] = Field(default=None, max_length=200)
    area: Optional[Area] = None
    priority: Optional[Priority] = None
    status: Optional[Status] = None
    due_on: Optional[date] = None
    follow_up_on: Optional[date] = None
    assignee_user_id: Optional[int] = None
    description: Optional[str] = Field(default=None, max_length=20_000)
    checklist: Optional[list[ChecklistItem]] = Field(default=None, max_length=50)
    contract_id: Optional[int] = None
    subject_user_id: Optional[int] = None
    #: Wersja widziana przez edytującego; inna w bazie = 409 (dwie osoby naraz).
    expected_updated_at: Optional[datetime] = None


class CommentIn(BaseModel):
    body: str = Field(min_length=1, max_length=10_000)


def _unprocessable(exc: Exception) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))


async def _readable_case(db: AsyncSession, case_id: int, user: User):
    case = await service.get_case(db, case_id)
    if case is None:
        # Osoba bez uprawnienia nie dowiaduje się, czy cudza sprawa istnieje.
        if not service.is_handler(user):
            raise HTTPException(status.HTTP_403_FORBIDDEN, CASE_FORBIDDEN_DETAIL)
        raise HTTPException(status.HTTP_404_NOT_FOUND, CASE_NOT_FOUND_DETAIL)
    if not service.may_read(user, case):
        raise HTTPException(status.HTTP_403_FORBIDDEN, CASE_FORBIDDEN_DETAIL)
    return case


async def _managed_case(db: AsyncSession, case_id: int):
    case = await service.get_case(db, case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, CASE_NOT_FOUND_DETAIL)
    return case


@router.get("")
async def list_cases(
    current_user: CasesReader,
    db: AsyncSession = Depends(get_db),
    mine: bool = False,
    area: Optional[Area] = None,
    status_filter: Optional[Status] = Query(default=None, alias="status"),
    priority: Optional[Priority] = None,
    q: Optional[str] = Query(default=None, max_length=200),
    include_closed: bool = False,
    week: bool = False,
    unassigned: bool = False,
    mine_care: bool = False,
) -> dict:
    return await queries.list_cases(
        db,
        current_user,
        queries.ListFilters(
            mine=mine,
            area=area,
            status=status_filter,
            priority=priority,
            q=q,
            include_closed=include_closed,
            week=week,
            unassigned=unassigned,
            mine_care=mine_care,
        ),
    )


@router.get("/assignees")
async def list_assignees(_: CasesHandler, db: AsyncSession = Depends(get_db)) -> dict:
    return {"items": await queries.assignee_options(db)}


@router.get("/contract-options")
async def list_contract_options(
    _: CasesHandler,
    db: AsyncSession = Depends(get_db),
    q: str = Query(default="", max_length=120),
) -> dict:
    return {"items": await queries.contract_options(db, q)}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_case(
    payload: CaseCreate,
    current_user: CasesHandler,
    db: AsyncSession = Depends(get_db),
) -> dict:
    values = payload.model_dump()
    values["checklist"] = [item.model_dump() for item in payload.checklist]
    try:
        case = await service.create_case(db, actor=current_user, values=values)
    except service.CaseError as exc:
        raise _unprocessable(exc) from exc
    await db.commit()
    return await queries.case_detail(db, case, current_user)


@router.get("/{case_id}")
async def get_case(
    case_id: int, current_user: CasesReader, db: AsyncSession = Depends(get_db)
) -> dict:
    case = await _readable_case(db, case_id, current_user)
    return await queries.case_detail(db, case, current_user)


@router.patch("/{case_id}")
async def update_case(
    case_id: int,
    payload: CaseUpdate,
    current_user: CasesHandler,
    db: AsyncSession = Depends(get_db),
) -> dict:
    case = await _managed_case(db, case_id)
    changes = payload.model_dump(exclude_unset=True)
    expected = changes.pop("expected_updated_at", None)
    if "checklist" in changes and payload.checklist is not None:
        changes["checklist"] = [item.model_dump() for item in payload.checklist]
    try:
        await service.update_case(
            db,
            case,
            actor=current_user,
            changes=changes,
            expected_updated_at=expected,
        )
    except service.CaseConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except service.CaseError as exc:
        raise _unprocessable(exc) from exc
    await db.commit()
    return await queries.case_detail(db, case, current_user)


@router.post("/{case_id}/comments", status_code=status.HTTP_201_CREATED)
async def add_comment(
    case_id: int,
    payload: CommentIn,
    current_user: CasesReader,
    db: AsyncSession = Depends(get_db),
) -> dict:
    case = await _readable_case(db, case_id, current_user)
    try:
        comment = await service.add_comment(
            db, case, actor=current_user, body=payload.body
        )
    except service.CaseError as exc:
        raise _unprocessable(exc) from exc
    await db.commit()
    return {
        "id": comment.id,
        "author": {"id": current_user.id, "name": current_user.name},
        "body": comment.body,
        "created_at": comment.created_at,
    }


@router.post("/{case_id}/close")
async def close_case(
    case_id: int, current_user: CasesHandler, db: AsyncSession = Depends(get_db)
) -> dict:
    case = await _managed_case(db, case_id)
    await service.close_case(db, case, actor=current_user)
    await db.commit()
    return await queries.case_detail(db, case, current_user)
