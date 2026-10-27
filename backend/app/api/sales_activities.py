"""Sprzedaż → Aktywności i zadania: telefony, maile, spotkania, zadania, notatki.

Prefiks ``/api/sales/activities`` (wpięty w ``app/main.py``). Jedna tabela
zamiast dwóch z Atlasa (aktywności szansy i firmy). Aktywność przy szansie
należy też do jej firmy. Zrobiona aktywność odświeża „ostatnią aktywność”
szansy — z niej liczymy szanse zaniedbane. Usuwa autor albo admin.

„Dziś” i „po terminie” liczymy w kalendarzu firmy (``app/core/scheduling``).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.api.sales_gates import SalesEditUser, SalesViewUser, is_admin
from app.core.database import get_db
from app.core.scheduling import local_day_bounds, local_now
from app.models.sales import (
    SalesActivity,
    SalesCompany,
    SalesContact,
    SalesOpportunity,
)
from app.models.user import User
from app.services import sales_schema as schema

router = APIRouter()

NOT_FOUND_DETAIL = "Nie ma takiej aktywności."
AUTHOR_ONLY_DETAIL = "Aktywność usuwa jej autor albo administrator."

Kind = Literal[schema.ACTIVITY_KINDS]  # type: ignore[valid-type]
Priority = Literal[schema.PRIORITIES]  # type: ignore[valid-type]


class ActivityFields(BaseModel):
    subject: Optional[str] = Field(default=None, max_length=500)
    body: Optional[str] = Field(default=None, max_length=50_000)
    priority: Optional[Priority] = None
    due_at: Optional[datetime] = None
    occurred_at: Optional[datetime] = None
    contact_id: Optional[int] = None
    assignee_user_id: Optional[int] = None
    is_pinned: Optional[bool] = None


class ActivityCreate(ActivityFields):
    kind: Kind
    company_id: Optional[int] = None
    opportunity_id: Optional[int] = None
    done: bool = False


class ActivityUpdate(ActivityFields):
    pass


class Ref(BaseModel):
    id: int
    name: str


class ActivityOut(BaseModel):
    id: int
    kind: str
    subject: Optional[str]
    body: Optional[str]
    priority: Optional[str]
    due_at: Optional[datetime]
    occurred_at: Optional[datetime]
    done_at: Optional[datetime]
    is_pinned: bool
    company: Optional[Ref]
    opportunity: Optional[Ref]
    contact: Optional[Ref]
    assignee: Optional[Ref]
    author: Optional[Ref]
    overdue: bool
    created_at: datetime


def _ref(id_: Optional[int], name: Optional[str]) -> Optional[Ref]:
    return Ref(id=id_, name=name or "") if id_ is not None else None


def _base_query():
    assignee = aliased(User)
    author = aliased(User)
    return (
        select(
            SalesActivity,
            SalesCompany.name.label("company_name"),
            SalesOpportunity.title.label("opportunity_title"),
            SalesContact.full_name.label("contact_name"),
            assignee.name.label("assignee_name"),
            author.name.label("author_name"),
        )
        .outerjoin(SalesCompany, SalesCompany.id == SalesActivity.company_id)
        .outerjoin(
            SalesOpportunity, SalesOpportunity.id == SalesActivity.opportunity_id
        )
        .outerjoin(SalesContact, SalesContact.id == SalesActivity.contact_id)
        .outerjoin(assignee, assignee.id == SalesActivity.assignee_user_id)
        .outerjoin(author, author.id == SalesActivity.created_by_user_id)
    )


def _out(row, now: datetime) -> ActivityOut:
    activity: SalesActivity = row.SalesActivity
    return ActivityOut(
        id=activity.id,
        kind=activity.kind,
        subject=activity.subject,
        body=activity.body,
        priority=activity.priority,
        due_at=activity.due_at,
        occurred_at=activity.occurred_at,
        done_at=activity.done_at,
        is_pinned=activity.is_pinned,
        company=_ref(activity.company_id, row.company_name),
        opportunity=_ref(activity.opportunity_id, row.opportunity_title),
        contact=_ref(activity.contact_id, row.contact_name),
        assignee=_ref(activity.assignee_user_id, row.assignee_name),
        author=_ref(activity.created_by_user_id, row.author_name),
        overdue=(
            activity.done_at is None
            and activity.due_at is not None
            and activity.due_at < now
        ),
        created_at=activity.created_at,
    )


async def _load(db: AsyncSession, activity_id: int) -> ActivityOut:
    row = (
        await db.execute(_base_query().where(SalesActivity.id == activity_id))
    ).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=NOT_FOUND_DETAIL)
    return _out(row, datetime.now(timezone.utc))


async def _touch_opportunity(
    db: AsyncSession, activity: SalesActivity, when: datetime
) -> None:
    """Zrobiona aktywność (nie zaplanowane zadanie) to ślad pracy przy szansie."""

    if activity.opportunity_id is None:
        return
    if activity.kind == "task" and activity.done_at is None:
        return
    opp = await db.get(SalesOpportunity, activity.opportunity_id)
    if opp is not None and (
        opp.last_activity_at is None or opp.last_activity_at < when
    ):
        opp.last_activity_at = when


async def _check_links(db: AsyncSession, fields: dict) -> None:
    contact_id = fields.get("contact_id")
    if contact_id is not None and await db.get(SalesContact, contact_id) is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Nie ma takiego kontaktu."
        )
    assignee_id = fields.get("assignee_user_id")
    if assignee_id is not None:
        user = await db.get(User, assignee_id)
        if user is None or not user.is_active:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Zadanie przypisz aktywnemu kontu w NEXUSIE.",
            )


@router.get("", response_model=list[ActivityOut])
async def list_activities(
    current_user: SalesViewUser,
    db: AsyncSession = Depends(get_db),
    company_id: Optional[int] = None,
    opportunity_id: Optional[int] = None,
    kind: Optional[Kind] = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[ActivityOut]:
    """Oś czasu firmy albo szansy: najpierw przypięte, potem od najnowszych."""

    if company_id is None and opportunity_id is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Podaj firmę albo szansę, której historię chcesz zobaczyć.",
        )
    query = _base_query()
    if company_id is not None:
        query = query.where(SalesActivity.company_id == company_id)
    if opportunity_id is not None:
        query = query.where(SalesActivity.opportunity_id == opportunity_id)
    if kind:
        query = query.where(SalesActivity.kind == kind)
    rows = (
        await db.execute(
            query.order_by(
                SalesActivity.is_pinned.desc(),
                func.coalesce(
                    SalesActivity.occurred_at,
                    SalesActivity.done_at,
                    SalesActivity.created_at,
                ).desc(),
                SalesActivity.id.desc(),
            ).limit(limit)
        )
    ).all()
    now = datetime.now(timezone.utc)
    return [_out(row, now) for row in rows]


@router.get("/tasks", response_model=list[ActivityOut])
async def list_tasks(
    current_user: SalesViewUser,
    db: AsyncSession = Depends(get_db),
    scope: Literal["mine", "team"] = "mine",
    bucket: Literal["open", "overdue", "today", "done"] = "open",
    limit: int = Query(default=200, ge=1, le=500),
) -> list[ActivityOut]:
    query = _base_query().where(SalesActivity.kind == "task")
    if scope == "mine":
        query = query.where(SalesActivity.assignee_user_id == current_user.id)
    now = datetime.now(timezone.utc)
    day = local_day_bounds(local_now())
    if bucket == "done":
        query = query.where(SalesActivity.done_at.is_not(None)).order_by(
            SalesActivity.done_at.desc()
        )
    else:
        query = query.where(SalesActivity.done_at.is_(None))
        if bucket == "overdue":
            query = query.where(SalesActivity.due_at < now)
        elif bucket == "today":
            query = query.where(
                SalesActivity.due_at >= day.start_utc,
                SalesActivity.due_at <= day.end_utc,
            )
        query = query.order_by(
            SalesActivity.due_at.asc().nulls_last(), SalesActivity.id
        )
    rows = (await db.execute(query.limit(limit))).all()
    return [_out(row, now) for row in rows]


@router.post("", response_model=ActivityOut, status_code=status.HTTP_201_CREATED)
async def create_activity(
    payload: ActivityCreate,
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> ActivityOut:
    fields = payload.model_dump(
        exclude={"kind", "company_id", "opportunity_id", "done"}, exclude_none=True
    )
    company_id = payload.company_id
    if payload.opportunity_id is not None:
        opp = await db.get(SalesOpportunity, payload.opportunity_id)
        if opp is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Nie ma takiej szansy."
            )
        if company_id is not None and company_id != opp.company_id:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Szansa należy do innej firmy.",
            )
        company_id = opp.company_id
    if company_id is not None and await db.get(SalesCompany, company_id) is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Nie ma takiej firmy w kartotece sprzedaży.",
        )
    if (
        payload.kind != "task"
        and not ((payload.subject or "") + (payload.body or "")).strip()
    ):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Wpisz temat albo treść.",
        )
    if payload.kind == "task" and not (payload.subject or "").strip():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Wpisz, co jest do zrobienia."
        )
    await _check_links(db, fields)
    now = datetime.now(timezone.utc)
    activity = SalesActivity(
        kind=payload.kind,
        company_id=company_id,
        opportunity_id=payload.opportunity_id,
        created_by_user_id=current_user.id,
    )
    for key, value in fields.items():
        setattr(activity, key, value.strip() if isinstance(value, str) else value)
    if payload.kind == "task":
        activity.assignee_user_id = activity.assignee_user_id or current_user.id
        if payload.done:
            activity.done_at = now
    else:
        activity.occurred_at = activity.occurred_at or now
        activity.done_at = activity.done_at or activity.occurred_at
    db.add(activity)
    await _touch_opportunity(db, activity, activity.done_at or now)
    await db.commit()
    return await _load(db, activity.id)


@router.patch("/{activity_id}", response_model=ActivityOut)
async def update_activity(
    activity_id: int,
    payload: ActivityUpdate,
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> ActivityOut:
    activity = await db.get(SalesActivity, activity_id)
    if activity is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=NOT_FOUND_DETAIL)
    fields = payload.model_dump(exclude_unset=True)
    await _check_links(db, fields)
    for key, value in fields.items():
        if key == "is_pinned" and value is None:
            continue
        setattr(activity, key, value.strip() if isinstance(value, str) else value)
    await db.commit()
    return await _load(db, activity_id)


@router.post("/{activity_id}/done", response_model=ActivityOut)
async def complete_activity(
    activity_id: int,
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> ActivityOut:
    activity = await db.get(SalesActivity, activity_id)
    if activity is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=NOT_FOUND_DETAIL)
    if activity.done_at is None:
        activity.done_at = datetime.now(timezone.utc)
        await _touch_opportunity(db, activity, activity.done_at)
        await db.commit()
    return await _load(db, activity_id)


@router.post("/{activity_id}/reopen", response_model=ActivityOut)
async def reopen_activity(
    activity_id: int,
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> ActivityOut:
    activity = await db.get(SalesActivity, activity_id)
    if activity is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=NOT_FOUND_DETAIL)
    if activity.kind == "task" and activity.done_at is not None:
        activity.done_at = None
        await db.commit()
    return await _load(db, activity_id)


@router.delete("/{activity_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_activity(
    activity_id: int,
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> None:
    activity = await db.get(SalesActivity, activity_id)
    if activity is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=NOT_FOUND_DETAIL)
    if activity.created_by_user_id != current_user.id and not is_admin(current_user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=AUTHOR_ONLY_DETAIL)
    await db.delete(activity)
    await db.commit()
