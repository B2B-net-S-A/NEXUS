"""DynaReporter Admin — Hall of Fame Manager.

Port `HallOfFameManager.tsx` z artur-t-96/InfraReporter.
CRUD na `dr_competition_winners` table.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.core.database import get_db
from app.models.user import UserRole

router = APIRouter()


class HoFWinnerCreate(BaseModel):
    """Payload do dodania zwycięzcy."""

    model_config = ConfigDict(from_attributes=True)

    competition_type: str = Field(
        description="'quarterly' | 'monthly_recommendations' | 'monthly_placements'",
        pattern=r"^(quarterly|monthly_recommendations|monthly_placements)$",
    )
    period: str = Field(description="np. 'Q1 2026' lub '2026-04'")
    user_id: int
    rank: int = Field(ge=1, le=3)
    points: int = Field(default=0, ge=0)
    metric_value: int = Field(default=0, ge=0)
    prize: str | None = None


def _require_admin(current_user) -> None:  # type: ignore[no-untyped-def]
    if current_user.role != UserRole.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Wymagana rola admin"
        )


@router.post(
    "/winner",
    summary="Dodaj wpis Hall of Fame (admin only)",
)
async def add_winner(
    payload: HoFWinnerCreate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Insert/replace winner — ON CONFLICT (competition_type, period, rank)."""
    _require_admin(current_user)
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
    return {"id": row.id if row else None, "ok": True}


@router.delete(
    "/winner/{winner_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,  # FastAPI 0.115 strict — 204 must not have body
    summary="Usuń wpis Hall of Fame (admin only)",
)
async def delete_winner(
    winner_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> None:
    _require_admin(current_user)
    await db.execute(
        text("DELETE FROM dr_competition_winners WHERE id = :id"),
        {"id": winner_id},
    )
    await db.commit()
