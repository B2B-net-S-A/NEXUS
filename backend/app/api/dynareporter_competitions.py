"""DynaReporter B.2.6 — Liga Mistrzów endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.core.database import get_db
from app.models.dr_competition import DrCompetitionNotification, DrCompetitionWinner
from app.models.user import User

router = APIRouter()


class WinnerResponse(BaseModel):
    id: int
    competition_type: str
    period: str
    user_id: int
    user_name: Optional[str] = None
    rank: int
    points: int
    metric_value: int
    prize: Optional[str] = None


class NotificationResponse(BaseModel):
    id: int
    notification_type: str
    competition_type: str
    title: str
    message: str
    is_read: bool
    created_at: datetime


@router.get("/winners", response_model=list[WinnerResponse])
async def list_winners(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    competition_type: Optional[str] = Query(default=None),
    period: Optional[str] = Query(default=None),
    limit: int = Query(default=30, ge=1, le=200),
) -> list[WinnerResponse]:
    stmt = (
        select(DrCompetitionWinner, User.name)
        .outerjoin(User, User.id == DrCompetitionWinner.user_id)
    )
    if competition_type:
        stmt = stmt.where(DrCompetitionWinner.competition_type == competition_type)
    if period:
        stmt = stmt.where(DrCompetitionWinner.period == period)
    stmt = stmt.order_by(
        DrCompetitionWinner.period.desc(),
        DrCompetitionWinner.competition_type,
        DrCompetitionWinner.rank,
    ).limit(limit)
    rows = (await db.execute(stmt)).all()
    return [
        WinnerResponse.model_validate({**r.__dict__, "user_name": n})
        for r, n in rows
    ]


@router.get("/podium", response_model=list[WinnerResponse])
async def current_podium(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    competition_type: str = Query(default="quarterly"),
) -> list[WinnerResponse]:
    """Top 3 dla ostatniego ogłoszonego period danego competition_type."""
    period_stmt = (
        select(DrCompetitionWinner.period)
        .where(DrCompetitionWinner.competition_type == competition_type)
        .order_by(DrCompetitionWinner.period.desc())
        .limit(1)
    )
    period_row = (await db.execute(period_stmt)).first()
    if not period_row:
        return []
    period = period_row[0]
    stmt = (
        select(DrCompetitionWinner, User.name)
        .outerjoin(User, User.id == DrCompetitionWinner.user_id)
        .where(
            DrCompetitionWinner.competition_type == competition_type,
            DrCompetitionWinner.period == period,
        )
        .order_by(DrCompetitionWinner.rank)
    )
    rows = (await db.execute(stmt)).all()
    return [
        WinnerResponse.model_validate({**r.__dict__, "user_name": n})
        for r, n in rows
    ]


@router.get("/my-notifications", response_model=list[NotificationResponse])
async def my_notifications(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    unread_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[NotificationResponse]:
    stmt = select(DrCompetitionNotification).where(
        DrCompetitionNotification.user_id == current_user.id
    )
    if unread_only:
        stmt = stmt.where(DrCompetitionNotification.is_read.is_(False))
    stmt = stmt.order_by(DrCompetitionNotification.created_at.desc()).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return [NotificationResponse.model_validate(r.__dict__) for r in rows]


@router.patch("/notifications/{notif_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_read(
    notif_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> None:
    result = await db.execute(
        update(DrCompetitionNotification)
        .where(
            DrCompetitionNotification.id == notif_id,
            DrCompetitionNotification.user_id == current_user.id,
        )
        .values(is_read=True)
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Powiadomienie nie znalezione")
    await db.commit()
