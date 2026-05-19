"""DynaReporter Admin Config endpoint.

Port `ScoringConfig.tsx` + `routes/config.ts` z artur-t-96/InfraReporter.

Pozwala adminowi czytać i modyfikować klucze w `dr_system_config`:
- `champions_league_scoring` — JSONB z punktacją (placement/interview/recommendation)
- inne klucze konfiguracyjne (do dodawania w przyszłości)
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


class ChampionsLeagueScoring(BaseModel):
    """Punktacja Ligi Mistrzów (placement/interview/recommendation)."""

    model_config = ConfigDict(from_attributes=True)

    placement: int = Field(default=150, ge=0)
    interview: int = Field(default=15, ge=0)
    recommendation: int = Field(default=5, ge=0)
    verification: int = Field(default=0, ge=0)


def _require_admin(current_user) -> None:  # type: ignore[no-untyped-def]
    if current_user.role != UserRole.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Wymagana rola admin",
        )


@router.get(
    "/scoring",
    response_model=ChampionsLeagueScoring,
    summary="Aktualna punktacja Ligi Mistrzów",
)
async def get_scoring(
    current_user: CurrentUser,  # noqa: ARG001
    db: AsyncSession = Depends(get_db),
) -> ChampionsLeagueScoring:
    """Każdy zalogowany user może czytać scoring (jest też w dashboard response)."""
    row = (
        await db.execute(
            text(
                "SELECT value FROM dr_system_config "
                "WHERE key = 'champions_league_scoring' LIMIT 1"
            )
        )
    ).first()
    if row and row[0]:
        return ChampionsLeagueScoring(**row[0])
    return ChampionsLeagueScoring()


@router.post(
    "/scoring",
    response_model=ChampionsLeagueScoring,
    summary="Update Champions League scoring (admin only)",
)
async def update_scoring(
    payload: ChampionsLeagueScoring,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> ChampionsLeagueScoring:
    """Admin upsert do `dr_system_config.champions_league_scoring`."""
    _require_admin(current_user)
    value_json = payload.model_dump()
    await db.execute(
        text(
            """
            INSERT INTO dr_system_config (key, value, updated_at)
            VALUES ('champions_league_scoring', :value::jsonb, CURRENT_TIMESTAMP)
            ON CONFLICT (key) DO UPDATE SET
                value = EXCLUDED.value,
                updated_at = CURRENT_TIMESTAMP
            """
        ),
        {"value": __import__("json").dumps(value_json)},
    )
    await db.commit()
    return payload
