"""Sprzedaż: wyniki zadań bota do decyzji handlowca (0684).

Prefiks ``/api/sales/bot-results``. Odczyt: „Sprzedaż: podgląd”, decyzje:
„Sprzedaż: edycja”. Odrzucenie jest wspólne dla wszystkich rodzajów; przyjęcie
robi rodzaj (``BotTask.accept``), a rodzaj bez niego odpowiada 409. Z wyłączoną
flagą ``SALES_BOT_TASKS_ENABLED`` lista mówi ``enabled: false`` i nic nie pokazuje.
→ docs/claude/sprzedaz/sygnaly-grok-bot.md („Zadania bota”)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.sales_gates import SalesEditUser, SalesViewUser
from app.core.database import get_db
from app.models.sales import SalesBotResult, SalesCompany
from app.models.user import User
from app.services import sales_schema as schema
from app.services.effective_access import resolve_effective_access
from app.services.sales import bot_tasks
from app.services.sales.bot_tasks.base import NO_ACCEPT_DETAIL
from app.services.sales.bot_tasks.people import KIND as PEOPLE_KIND
from app.services.sales.offers import works_in_sales

router = APIRouter()

NOT_FOUND_DETAIL = "Nie ma takiego wyniku."
DECIDED_DETAIL = "O tym wyniku już zdecydowano."
#: Wyniki, o których można jeszcze zdecydować.
OPEN_STATUSES: tuple[str, ...] = ("new", "partial")

Status = Literal[schema.BOT_RESULT_STATUSES]  # type: ignore[valid-type]
Kind = Literal[schema.BOT_RUN_KINDS]  # type: ignore[valid-type]


class CompanyRef(BaseModel):
    id: int
    name: str


class BotResultOut(BaseModel):
    id: int
    kind: str
    company: Optional[CompanyRef]
    status: str
    payload: dict[str, Any]
    created_at: datetime
    run_id: int
    #: Opiekun karty firmy i czy pracuje w Sprzedaży (panel „W NEXUSIE”).
    owner: Optional[CompanyRef] = None
    owner_in_sales: bool = False


class BotResultsOut(BaseModel):
    enabled: bool
    items: list[BotResultOut]


class RejectIn(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=300)


class AcceptIn(BaseModel):
    """Wybór handlowca dla rodzaju z polami (``enrich``): które przyjąć, które odrzucić.

    Bez ``fields`` rodzaj sam decyduje, co znaczy „przyjmij wszystko”.
    """

    fields: Optional[list[str]] = Field(default=None, max_length=20)
    reject: list[str] = Field(default_factory=list, max_length=20)


def _out(
    row: SalesBotResult,
    company: Optional[SalesCompany],
    owners: Optional[dict[int, User]] = None,
) -> BotResultOut:
    owner = (owners or {}).get(company.owner_user_id or 0) if company else None
    return BotResultOut(
        id=row.id,
        kind=row.kind,
        company=None
        if company is None
        else CompanyRef(id=company.id, name=company.name),
        status=row.status,
        # Wyniki osób są dostępne w dedykowanym przeglądzie z „Sprzedaż: edycja”.
        payload={} if row.kind == PEOPLE_KIND else dict(row.payload or {}),
        created_at=row.created_at,
        run_id=row.run_id,
        owner=None
        if owner is None
        else CompanyRef(id=owner.id, name=owner.name or owner.email),
        owner_in_sales=owner is not None and works_in_sales(owner),
    )


async def _owners(
    db: AsyncSession, companies: list[Optional[SalesCompany]]
) -> dict[int, User]:
    ids = sorted({c.owner_user_id for c in companies if c and c.owner_user_id})
    if not ids:
        return {}
    users = list((await db.scalars(select(User).where(User.id.in_(ids)))).all())
    await resolve_effective_access(db, users)
    return {user.id: user for user in users}


@router.get("", response_model=BotResultsOut)
async def list_results(
    current_user: SalesViewUser,
    db: AsyncSession = Depends(get_db),
    kind: Optional[Kind] = Query(default=None),
    result_status: Optional[Status] = Query(default=None, alias="status"),
    company_id: Optional[int] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> BotResultsOut:
    if not bot_tasks.enabled():
        return BotResultsOut(enabled=False, items=[])
    statement = (
        select(SalesBotResult, SalesCompany)
        .outerjoin(SalesCompany, SalesCompany.id == SalesBotResult.company_id)
        .order_by(SalesBotResult.created_at.desc(), SalesBotResult.id.desc())
        .limit(limit)
    )
    if kind is not None:
        statement = statement.where(SalesBotResult.kind == kind)
    if result_status is not None:
        statement = statement.where(SalesBotResult.status == result_status)
    if company_id is not None:
        statement = statement.where(SalesBotResult.company_id == company_id)
    rows = (await db.execute(statement)).all()
    owners = await _owners(db, [company for _row, company in rows])
    return BotResultsOut(
        enabled=True, items=[_out(row, company, owners) for row, company in rows]
    )


async def _company(
    db: AsyncSession, company_id: Optional[int]
) -> Optional[SalesCompany]:
    return None if company_id is None else await db.get(SalesCompany, company_id)


@router.post("/{result_id}/reject", response_model=BotResultOut)
async def reject_result(
    result_id: int,
    current_user: SalesEditUser,
    payload: Optional[RejectIn] = None,
    db: AsyncSession = Depends(get_db),
) -> BotResultOut:
    now = datetime.now(timezone.utc)
    reason = ((payload.reason if payload else None) or "").strip() or None
    # Warunkowo: przyjęty w międzyczasie wynik nie zmienia się na odrzucony.
    decided = (
        await db.execute(
            update(SalesBotResult)
            .where(
                SalesBotResult.id == result_id,
                SalesBotResult.status.in_(OPEN_STATUSES),
            )
            .values(
                status="rejected",
                decided_by_user_id=current_user.id,
                decided_at=now,
                decision_reason=reason,
                updated_at=now,
            )
            .returning(SalesBotResult.id)
        )
    ).scalar_one_or_none()
    if decided is None:
        exists = await db.get(SalesBotResult, result_id)
        if exists is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=NOT_FOUND_DETAIL)
        if exists.status != "rejected":
            raise HTTPException(status.HTTP_409_CONFLICT, detail=DECIDED_DETAIL)
    await db.commit()
    row = await db.get(SalesBotResult, result_id, populate_existing=True)
    company = await _company(db, row.company_id)
    return _out(row, company, await _owners(db, [company]))


@router.post("/{result_id}/accept")
async def accept_result(
    result_id: int,
    current_user: SalesEditUser,
    payload: Optional[AcceptIn] = None,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    user_id = current_user.id
    row = await db.get(SalesBotResult, result_id, with_for_update=True)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=NOT_FOUND_DETAIL)
    if row.status not in OPEN_STATUSES:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=DECIDED_DETAIL)
    task = bot_tasks.get(row.kind)
    if task is None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=NO_ACCEPT_DETAIL)
    try:
        outcome = await task.accept(
            db,
            row,
            user_id,
            datetime.now(timezone.utc),
            payload.model_dump() if payload else None,
        )
    except bot_tasks.AcceptRefused as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from None
    await db.commit()
    return outcome
