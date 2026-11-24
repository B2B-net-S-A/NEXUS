"""Sprzedaż → Leady → Przetargi: ogłoszenia z BZP i TED po bramce reguł Kingi.

Prefiks ``/api/sales/tenders``. Odczyt „Sprzedaż: podgląd”; „Przywróć” i reguły
„Sprzedaż: edycja”; ręczny bieg tylko administrator, także przy wyłączonej
fladze (próba). Wariant B (decyzja Artura 24.11.2026): szanse zakłada bramka,
ekran pokazuje, co założyła i co odsiała, z regułą i „Przywróć”.

Bez ``from __future__ import annotations`` (slowapi #579). Logi: same liczby.
→ docs/claude/sprzedaz/przetargi-z-rejestrow.md
"""

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.sales_gates import SalesEditUser, SalesViewUser, is_admin
from app.core.config import settings
from app.core.database import get_db
from app.core.rate_limit import limiter, user_or_ip_key
from app.core.scheduling import local_now
from app.core.tasks import spawn
from app.models.sales import SalesOpportunity, SalesPipelineStage, SalesTenderNotice
from app.models.user import User
from app.services.action_permissions import ProductAction, has_permission
from app.services.sales.handoff_hosts import sales_editors
from app.services.sales.tenders import flow, rules

logger = logging.getLogger(__name__)

router = APIRouter()

LIST_LIMIT = 300
ADMIN_DETAIL = "Bieg na żądanie uruchamia administrator."
RUNNING_DETAIL = "Bieg już trwa. Wynik pojawi się na tej liście."
NOT_FOUND_DETAIL = "Nie ma takiego ogłoszenia."
NOT_REJECTED_DETAIL = "To ogłoszenie ma już szansę w lejku Przetargi."
EXPIRED_DETAIL = "Termin składania ofert minął, szansy nie zakładam."
OWNER_DETAIL = "Opiekun musi być aktywnym kontem z uprawnieniem „Sprzedaż: edycja”."

Item = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=rules.MAX_ITEM_CHARS
    ),
]


class TenderRunOut(BaseModel):
    status: str
    trigger: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    error: Optional[str] = None
    counts: dict[str, int] = Field(default_factory=dict)


class TenderNoticeOut(BaseModel):
    id: int
    source: str
    number: str
    title: str
    buyer_name: str
    buyer_city: Optional[str] = None
    url: Optional[str] = None
    published_at: datetime
    deadline_date: Optional[date] = None
    deadline_at: Optional[datetime] = None
    status: str
    rule: Optional[str] = None
    rule_label: Optional[str] = None
    rule_detail: Optional[str] = None
    match_detail: Optional[str] = None
    opportunity_id: Optional[int] = None
    opportunity_status: Optional[str] = None
    opportunity_stage: Optional[str] = None
    restored_by: Optional[str] = None
    restored_at: Optional[datetime] = None


class TendersOut(BaseModel):
    enabled: bool
    can_run: bool
    can_edit: bool
    last_run: Optional[TenderRunOut] = None
    created: int
    rejected: int
    items: list[TenderNoticeOut]


class RulesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phrases: list[Item] = Field(max_length=rules.MAX_ITEMS)
    reject_subject: list[Item] = Field(max_length=rules.MAX_ITEMS)
    reject_buyer: list[Item] = Field(max_length=rules.MAX_ITEMS)
    only_services: bool
    owner_user_id: Optional[int] = None


class OwnerOut(BaseModel):
    id: int
    name: str


class RulesOut(BaseModel):
    phrases: list[str]
    reject_subject: list[str]
    reject_buyer: list[str]
    only_services: bool
    owner_user_id: Optional[int] = None
    owner_name: Optional[str] = None
    can_edit: bool
    #: Komu bramka może dawać szanse (tylko dla edytujących).
    owners: list[OwnerOut] = Field(default_factory=list)


def _can_edit(user: User) -> bool:
    return has_permission(user, ProductAction.sales_edit)


def _notice_out(
    row: SalesTenderNotice,
    opportunity_status: Optional[str],
    stage_name: Optional[str],
    restored_by: Optional[str],
) -> TenderNoticeOut:
    return TenderNoticeOut(
        id=row.id,
        source=row.source,
        number=row.number,
        title=row.title,
        buyer_name=row.buyer_name,
        buyer_city=row.buyer_city,
        url=row.url,
        published_at=row.published_at,
        deadline_date=row.deadline_date,
        deadline_at=row.deadline_at,
        status=row.status,
        rule=row.rule,
        rule_label=rules.RULE_LABELS.get(row.rule or ""),
        rule_detail=row.rule_detail,
        match_detail=row.match_detail,
        opportunity_id=row.opportunity_id,
        opportunity_status=opportunity_status,
        opportunity_stage=stage_name,
        restored_by=restored_by,
        restored_at=row.decided_at,
    )


def _with_links():
    return (
        select(
            SalesTenderNotice,
            SalesOpportunity.status,
            SalesPipelineStage.name,
            User.name,
        )
        .outerjoin(
            SalesOpportunity, SalesOpportunity.id == SalesTenderNotice.opportunity_id
        )
        .outerjoin(
            SalesPipelineStage, SalesPipelineStage.id == SalesOpportunity.stage_id
        )
        .outerjoin(User, User.id == SalesTenderNotice.decided_by_user_id)
    )


async def _one(db: AsyncSession, notice_id: int) -> TenderNoticeOut:
    row = (
        await db.execute(_with_links().where(SalesTenderNotice.id == notice_id))
    ).one()
    return _notice_out(*row)


def _run_out(state: dict, now: datetime) -> Optional[TenderRunOut]:
    view = flow.last_run_view(state, now=now)
    if view is None:
        return None
    counts = view.get("counts") if isinstance(view.get("counts"), dict) else {}
    return TenderRunOut(
        status=str(view.get("status") or "failed"),
        trigger=view.get("trigger"),
        started_at=view.get("started_at"),
        finished_at=view.get("finished_at"),
        error=view.get("error"),
        counts={
            key: int(value) for key, value in counts.items() if isinstance(value, int)
        },
    )


@router.get("", response_model=TendersOut)
@limiter.limit("120/minute", key_func=user_or_ip_key)
async def list_tenders(
    request: Request,
    current_user: SalesViewUser,
    status_filter: Literal["created", "rejected"] = Query("created", alias="status"),
    days: int = Query(14, ge=1, le=60),
    db: AsyncSession = Depends(get_db),
) -> TendersOut:
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    counts = dict(
        (
            await db.execute(
                select(SalesTenderNotice.status, func.count())
                .where(SalesTenderNotice.created_at >= since)
                .group_by(SalesTenderNotice.status)
            )
        ).all()
    )
    query = _with_links().where(
        SalesTenderNotice.created_at >= since, SalesTenderNotice.status == status_filter
    )
    if status_filter == "created":
        query = query.order_by(
            SalesTenderNotice.deadline_date.asc().nulls_last(),
            SalesTenderNotice.published_at.desc(),
        )
    else:
        query = query.order_by(SalesTenderNotice.published_at.desc())
    rows = (await db.execute(query.limit(LIST_LIMIT))).all()
    state = await flow.load_state(db)
    return TendersOut(
        enabled=settings.SALES_TENDERS_ENABLED,
        can_run=is_admin(current_user),
        can_edit=_can_edit(current_user),
        last_run=_run_out(state, now),
        created=int(counts.get("created", 0)),
        rejected=int(counts.get("rejected", 0)),
        items=[_notice_out(*row) for row in rows],
    )


@router.post("/{notice_id}/restore", response_model=TenderNoticeOut)
@limiter.limit("30/minute", key_func=user_or_ip_key)
async def restore_tender(
    notice_id: int,
    request: Request,
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> TenderNoticeOut:
    row = await db.get(SalesTenderNotice, notice_id, with_for_update=True)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=NOT_FOUND_DETAIL)
    if row.status != "rejected":
        raise HTTPException(status.HTTP_409_CONFLICT, detail=NOT_REJECTED_DETAIL)
    now = datetime.now(timezone.utc)
    if rules.is_expired(flow.row_notice(row), today=local_now().date(), now=now):
        raise HTTPException(status.HTTP_409_CONFLICT, detail=EXPIRED_DETAIL)
    try:
        await flow.restore(db, row, user_id=current_user.id, now=now)
    except flow.TendersNotReady as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await db.commit()
    logger.info("sales_tenders restore notice=%d", notice_id)
    return await _one(db, notice_id)


async def _rules_out(db: AsyncSession, user: User) -> RulesOut:
    current = await rules.load(db)
    can_edit = _can_edit(user)
    owner_name = None
    if current.owner_user_id is not None:
        owner = await db.get(User, current.owner_user_id)
        owner_name = owner.name if owner is not None else None
    owners = (
        [OwnerOut(id=editor.id, name=editor.name) for editor in await sales_editors(db)]
        if can_edit
        else []
    )
    return RulesOut(
        phrases=list(current.phrases),
        reject_subject=list(current.reject_subject),
        reject_buyer=list(current.reject_buyer),
        only_services=current.only_services,
        owner_user_id=current.owner_user_id,
        owner_name=owner_name,
        can_edit=can_edit,
        owners=owners,
    )


@router.get("/rules", response_model=RulesOut)
@limiter.limit("120/minute", key_func=user_or_ip_key)
async def get_rules(
    request: Request,
    current_user: SalesViewUser,
    db: AsyncSession = Depends(get_db),
) -> RulesOut:
    return await _rules_out(db, current_user)


@router.put("/rules", response_model=RulesOut)
@limiter.limit("30/minute", key_func=user_or_ip_key)
async def put_rules(
    payload: RulesIn,
    request: Request,
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> RulesOut:
    if payload.owner_user_id is not None and payload.owner_user_id not in {
        editor.id for editor in await sales_editors(db)
    }:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=OWNER_DETAIL)
    await rules.save(
        db,
        rules.TenderRules(
            phrases=tuple(payload.phrases),
            reject_subject=tuple(payload.reject_subject),
            reject_buyer=tuple(payload.reject_buyer),
            only_services=payload.only_services,
            owner_user_id=payload.owner_user_id,
        ),
        user_id=current_user.id,
    )
    await db.commit()
    logger.info(
        "sales_tenders rules saved phrases=%d subject=%d buyer=%d",
        len(payload.phrases),
        len(payload.reject_subject),
        len(payload.reject_buyer),
    )
    return await _rules_out(db, current_user)


@router.post("/run", response_model=TenderRunOut, status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("6/minute", key_func=user_or_ip_key)
async def run_tenders(
    request: Request,
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> TenderRunOut:
    if not is_admin(current_user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=ADMIN_DETAIL)
    now = datetime.now(timezone.utc)
    current = _run_out(await flow.load_state(db), now)
    if current is not None and current.status == "running":
        raise HTTPException(status.HTTP_409_CONFLICT, detail=RUNNING_DETAIL)
    spawn(flow.run(trigger="manual"), "sales_tenders manual run")
    logger.info("sales_tenders manual run requested")
    return TenderRunOut(status="running", trigger="manual", started_at=now)
