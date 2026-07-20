"""DynaReporter Admin — Hall of Fame Manager.

Port `HallOfFameManager.tsx` z artur-t-96/InfraReporter.
CRUD na `dr_competition_winners` table.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminUser
from app.core.database import get_db

logger = logging.getLogger("dynareporter.admin_hof")

router = APIRouter()


class HoFWinnerCreate(BaseModel):
    """Payload do dodania zwycięzcy."""

    model_config = ConfigDict(from_attributes=True)

    competition_type: str = Field(
        description="'quarterly' | 'monthly_recommendations' | 'monthly_placements'",
        pattern=r"^(quarterly|monthly_recommendations|monthly_placements)$",
    )
    # Period — albo "Q1 2026" / "Q4 2026" (quarterly) albo "2026-04" (monthly).
    # max_length=20 = DB constraint character varying(20).
    period: str = Field(
        description="np. 'Q1 2026' lub '2026-04'",
        pattern=r"^(Q[1-4] \d{4}|\d{4}-(0[1-9]|1[0-2]))$",
        max_length=20,
    )
    user_id: int = Field(ge=1)
    rank: int = Field(ge=1, le=3)
    points: int = Field(default=0, ge=0)
    metric_value: int = Field(default=0, ge=0)
    # max_length=100 = DB constraint character varying(100).
    prize: str | None = Field(default=None, max_length=100)


@router.post(
    "/winner",
    summary="Dodaj wpis Hall of Fame (admin only)",
)
async def add_winner(
    payload: HoFWinnerCreate,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Insert/replace winner — ON CONFLICT (competition_type, period, rank)."""
    sql = text(
        """
        INSERT INTO dr_competition_winners (
            competition_type, period, user_id, rank, points, metric_value, prize
        ) VALUES (:ct, :pd, :uid, :rk, :pts, :mv, :pz)
        ON CONFLICT (competition_type, period, rank) DO UPDATE SET
            user_id = EXCLUDED.user_id,
            points = EXCLUDED.points,
            metric_value = EXCLUDED.metric_value,
            prize = EXCLUDED.prize
        RETURNING id
        """
    )
    result = await db.execute(
        sql,
        {
            "ct": payload.competition_type,
            "pd": payload.period,
            "uid": payload.user_id,
            "rk": payload.rank,
            "pts": payload.points,
            "mv": payload.metric_value,
            "pz": payload.prize,
        },
    )
    await db.commit()
    row = result.first()
    winner_id = row.id if row else None
    logger.info(
        "HoF winner upserted: id=%s competition=%s period=%s rank=%s user=%s by admin=%s",
        winner_id,
        payload.competition_type,
        payload.period,
        payload.rank,
        payload.user_id,
        current_user.id,
    )
    return {"id": winner_id, "ok": True}


@router.delete(
    "/winner/{winner_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,  # FastAPI 0.115 strict — 204 must not have body
    summary="Usuń wpis Hall of Fame (admin only)",
)
async def delete_winner(
    winner_id: int,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> None:
    await db.execute(
        text("DELETE FROM dr_competition_winners WHERE id = :id"),
        {"id": winner_id},
    )
    await db.commit()
    logger.info(
        "HoF winner deleted: id=%s by admin=%s",
        winner_id,
        current_user.id,
    )
