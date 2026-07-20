"""DynaReporter B.2.4 — Placements endpoints.

2026-07-20: usunięte trasy zapisu (POST "", POST /with-delivery-lead, DELETE) —
ręczne wprowadzanie statystyk wygaszone, NEXUS liczy te liczby sam
(patrz /insights). GET-y zostają dla widoków historycznych.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, RecruiterPlus
from app.core.database import get_db
from app.models.client import Client
from app.models.dr_placement_details import DrPlacementDetail
from app.models.user import User, UserRole

router = APIRouter()


class PlacementResponse(BaseModel):
    id: int
    user_id: int
    user_name: Optional[str] = None
    client_id: int
    placement_date: date
    week_number: Optional[int] = None
    notes: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)


class PlacementStatsByUser(BaseModel):
    user_id: int
    user_name: str
    total_placements: int


class PlacementStatsByClient(BaseModel):
    client_id: int
    # Name of the client, joined from clients table. Pre-2026-05-27 the
    # endpoint returned only client_id which surfaced as "Klient #13" in
    # DR Placements Top 10 UI (QA session bug #28) — useless for managers
    # who need to know WHICH client converted, not the id. Optional because
    # legacy placements created before clients was wired could have orphan
    # client_id (the LEFT JOIN below tolerates that).
    client_name: Optional[str] = None
    total_placements: int


@router.get("/my", response_model=list[PlacementResponse])
async def list_my_placements(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    from_date: Optional[date] = Query(default=None),
    to_date: Optional[date] = Query(default=None),
) -> list[PlacementResponse]:
    stmt = select(DrPlacementDetail).where(DrPlacementDetail.user_id == current_user.id)
    if from_date:
        stmt = stmt.where(DrPlacementDetail.placement_date >= from_date)
    if to_date:
        stmt = stmt.where(DrPlacementDetail.placement_date <= to_date)
    rows = (
        (await db.execute(stmt.order_by(DrPlacementDetail.placement_date.desc())))
        .scalars()
        .all()
    )
    return [
        PlacementResponse.model_validate({**r.__dict__, "user_name": current_user.name})
        for r in rows
    ]


@router.get("/all", response_model=list[PlacementResponse])
async def list_all_placements(
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
    user_id: Optional[int] = Query(default=None),
    client_id: Optional[int] = Query(default=None),
    from_date: Optional[date] = Query(default=None),
    to_date: Optional[date] = Query(default=None),
) -> list[PlacementResponse]:
    is_priv = current_user.has_any_role(
        UserRole.admin,
        UserRole.delivery_lead,
        UserRole.head_of_recruitment,
    )
    stmt = select(DrPlacementDetail, User.name).join(
        User, User.id == DrPlacementDetail.user_id
    )
    if user_id:
        if not is_priv and user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Brak dostępu")
        stmt = stmt.where(DrPlacementDetail.user_id == user_id)
    elif not is_priv:
        stmt = stmt.where(DrPlacementDetail.user_id == current_user.id)
    if client_id:
        stmt = stmt.where(DrPlacementDetail.client_id == client_id)
    if from_date:
        stmt = stmt.where(DrPlacementDetail.placement_date >= from_date)
    if to_date:
        stmt = stmt.where(DrPlacementDetail.placement_date <= to_date)
    rows = (
        await db.execute(stmt.order_by(DrPlacementDetail.placement_date.desc()))
    ).all()
    return [
        PlacementResponse.model_validate({**r.__dict__, "user_name": n})
        for r, n in rows
    ]


@router.get("/stats/by-user", response_model=list[PlacementStatsByUser])
async def stats_by_user(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    days: int = Query(default=90, ge=1, le=3650),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[PlacementStatsByUser]:
    from_d = date.today() - timedelta(days=days)
    stmt = (
        select(User.id, User.name, func.count(DrPlacementDetail.id).label("cnt"))
        .join(DrPlacementDetail, DrPlacementDetail.user_id == User.id)
        .where(DrPlacementDetail.placement_date >= from_d)
        .group_by(User.id, User.name)
        .order_by(func.count(DrPlacementDetail.id).desc())
        .limit(limit)
    )
    rows = (await db.execute(stmt)).all()
    return [
        PlacementStatsByUser(user_id=uid, user_name=n or "", total_placements=cnt)
        for uid, n, cnt in rows
    ]


@router.get("/stats/by-client", response_model=list[PlacementStatsByClient])
async def stats_by_client(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    days: int = Query(default=90, ge=1, le=3650),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[PlacementStatsByClient]:
    from_d = date.today() - timedelta(days=days)
    # LEFT JOIN clients so orphan placements (legacy data with stale
    # client_id) still appear in the leaderboard rather than being silently
    # dropped — surface them with `client_name=None` so admins can spot
    # the data quality issue and clean up.
    stmt = (
        select(
            DrPlacementDetail.client_id,
            Client.name.label("client_name"),
            func.count(DrPlacementDetail.id).label("cnt"),
        )
        .outerjoin(Client, Client.id == DrPlacementDetail.client_id)
        .where(DrPlacementDetail.placement_date >= from_d)
        .group_by(DrPlacementDetail.client_id, Client.name)
        .order_by(func.count(DrPlacementDetail.id).desc())
        .limit(limit)
    )
    rows = (await db.execute(stmt)).all()
    return [
        PlacementStatsByClient(client_id=cid, client_name=name, total_placements=cnt)
        for cid, name, cnt in rows
    ]
