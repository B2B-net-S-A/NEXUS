"""Sprzedaż → Aktywności i zadania: telefony, maile, spotkania, zadania, notatki.

Prefiks ``/api/sales/activities`` (wpięty w ``app/main.py``). Jedna tabela
zamiast dwóch z Atlasa (aktywności szansy i firmy). Aktywność przy szansie
należy też do jej firmy. Zrobiona aktywność odświeża „ostatnią aktywność”
szansy — z niej liczymy szanse zaniedbane. Usuwa autor albo admin.

„Dziś” i „po terminie” liczymy w kalendarzu firmy (``app/core/scheduling``).
Lista zadań obejmuje też telefony z terminem (``TASK_KINDS``) — w Atlasie
Task Center pokazywał każdy otwarty rodzaj. Na osi szansy można dołożyć maile
i spotkania jej firmy z Outlooka (``with_company_mail``), jak karta szansy
w Atlasie: synchronizacja przypina je do firmy, nie do szansy.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select, update
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
EDIT_AUTHOR_ONLY_DETAIL = "Aktywność poprawia jej autor albo administrator."
#: Maile i spotkania z Outlooka (Microsoft Graph) — ``external_source`` z Atlasa.
COMPANY_MAIL_SOURCE_PATTERN = "msgraph-%"

Kind = Literal[schema.ACTIVITY_KINDS]  # type: ignore[valid-type]
Priority = Literal[schema.PRIORITIES]  # type: ignore[valid-type]
TaskKind = Literal[schema.TASK_KINDS]  # type: ignore[valid-type]


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
    kind: Optional[Kind] = None


class CompleteTasksRequest(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=500)


class CompleteTasksOut(BaseModel):
    updated: int


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
    external_source: Optional[str] = None
    web_link: Optional[str] = None
    direction: Optional[str] = None
    duration_minutes: Optional[int] = None
    #: Mail albo spotkanie firmy dołożone do osi szansy (``with_company_mail``).
    from_company: bool = False


class TaskList(BaseModel):
    items: list[ActivityOut]
    total: int


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


def _is_open_item(kind: str, due_at: Optional[datetime]) -> bool:
    """Zadanie albo telefon z terminem — pozycja listy zadań, nie wpis historii."""

    return kind == "task" or (kind in schema.TASK_KINDS and due_at is not None)


def _task_items():
    return or_(
        SalesActivity.kind == "task",
        and_(
            SalesActivity.kind.in_(schema.TASK_KINDS),
            SalesActivity.due_at.is_not(None),
        ),
    )


def _out(row, now: datetime, *, from_company: bool = False) -> ActivityOut:
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
        external_source=activity.external_source,
        web_link=activity.web_link,
        direction=activity.direction,
        duration_minutes=activity.duration_minutes,
        from_company=from_company,
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
    if activity.kind in schema.TASK_KINDS and activity.done_at is None:
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
    with_company_mail: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
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
        scope = SalesActivity.opportunity_id == opportunity_id
        mail_company_id = (
            await db.scalar(
                select(SalesOpportunity.company_id).where(
                    SalesOpportunity.id == opportunity_id
                )
            )
            if with_company_mail
            else None
        )
        if mail_company_id is not None:
            scope = or_(
                scope,
                and_(
                    SalesActivity.company_id == mail_company_id,
                    SalesActivity.opportunity_id.is_(None),
                    SalesActivity.external_source.like(COMPANY_MAIL_SOURCE_PATTERN),
                ),
            )
        query = query.where(scope)
    if kind:
        query = query.where(SalesActivity.kind == kind)
    rows = (
        await db.execute(
            query.order_by(
                SalesActivity.is_pinned.desc(),
                func.coalesce(
                    SalesActivity.occurred_at, SalesActivity.created_at
                ).desc(),
                SalesActivity.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
    ).all()
    now = datetime.now(timezone.utc)
    return [
        _out(
            row,
            now,
            from_company=(
                opportunity_id is not None
                and row.SalesActivity.opportunity_id != opportunity_id
            ),
        )
        for row in rows
    ]


@router.get("/tasks", response_model=TaskList)
async def list_tasks(
    current_user: SalesViewUser,
    db: AsyncSession = Depends(get_db),
    scope: Literal["mine", "team"] = "mine",
    bucket: Literal["open", "overdue", "today", "done"] = "open",
    kind: Optional[TaskKind] = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> TaskList:
    """Zadania i telefony z terminem (Task Center z Atlasa)."""

    query = _base_query().where(_task_items())
    if kind:
        query = query.where(SalesActivity.kind == kind)
    if scope == "mine":
        query = query.where(SalesActivity.assignee_user_id == current_user.id)
    now = datetime.now(timezone.utc)
    day = local_day_bounds(local_now())
    if bucket == "done":
        query = query.where(SalesActivity.done_at.is_not(None))
        order = (SalesActivity.done_at.desc(), SalesActivity.id.desc())
    else:
        query = query.where(SalesActivity.done_at.is_(None))
        if bucket == "overdue":
            query = query.where(SalesActivity.due_at < now)
        elif bucket == "today":
            query = query.where(
                SalesActivity.due_at >= day.start_utc,
                SalesActivity.due_at <= day.end_utc,
            )
        order = (SalesActivity.due_at.asc().nulls_last(), SalesActivity.id)
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    rows = (await db.execute(query.order_by(*order).limit(limit).offset(offset))).all()
    return TaskList(items=[_out(row, now) for row in rows], total=int(total or 0))


@router.post("/tasks/complete", response_model=CompleteTasksOut)
async def complete_tasks(
    payload: CompleteTasksRequest,
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> CompleteTasksOut:
    """Odhacz kilka zadań naraz; zrobione wcześniej zostają bez zmian."""

    now = datetime.now(timezone.utc)
    done = (
        await db.execute(
            update(SalesActivity)
            .where(
                SalesActivity.id.in_(set(payload.ids)),
                SalesActivity.done_at.is_(None),
                _task_items(),
            )
            .values(done_at=now)
            .returning(SalesActivity.opportunity_id)
        )
    ).all()
    opportunity_ids = {row[0] for row in done if row[0] is not None}
    if opportunity_ids:
        await db.execute(
            update(SalesOpportunity)
            .where(
                SalesOpportunity.id.in_(opportunity_ids),
                or_(
                    SalesOpportunity.last_activity_at.is_(None),
                    SalesOpportunity.last_activity_at < now,
                ),
            )
            .values(last_activity_at=now)
        )
    await db.commit()
    return CompleteTasksOut(updated=len(done))


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
    open_item = _is_open_item(payload.kind, payload.due_at)
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
    if open_item:
        # Zadanie albo telefon z terminem: trafia na listę zadań autora,
        # jeśli nikt inny nie jest wskazany.
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
    if activity.created_by_user_id != current_user.id and not is_admin(current_user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=EDIT_AUTHOR_ONLY_DETAIL)
    fields = payload.model_dump(exclude_unset=True)
    if fields.get("kind", "") is None:
        fields.pop("kind")
    await _check_links(db, fields)
    for key, value in fields.items():
        if key == "is_pinned" and value is None:
            continue
        setattr(activity, key, value.strip() if isinstance(value, str) else value)
    if activity.kind == "task" and not (activity.subject or "").strip():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Wpisz, co jest do zrobienia."
        )
    if (
        _is_open_item(activity.kind, activity.due_at)
        and activity.done_at is None
        and activity.assignee_user_id is None
    ):
        activity.assignee_user_id = current_user.id
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
    if _is_open_item(activity.kind, activity.due_at) and activity.done_at is not None:
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
