"""DynaReporter Admin Config endpoint.

Port `ScoringConfig.tsx` + `routes/config.ts` z artur-t-96/InfraReporter.

Pozwala adminowi czytać i modyfikować klucze w `dr_system_config`:
- `champions_league_scoring` — JSONB z punktacją (placement/interview/recommendation)
- inne klucze konfiguracyjne (do dodawania w przyszłości)
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    CurrentUser,
    DynaReporterSection,
    require_dynareporter_section,
)
from app.core.database import get_db
from app.models.user import UserRole

logger = logging.getLogger("dynareporter.admin_config")

router = APIRouter(
    dependencies=[
        Depends(require_dynareporter_section(DynaReporterSection.admin))
    ]
)


class ChampionsLeagueScoring(BaseModel):
    """Punktacja Ligi Mistrzów + prizes + thresholds (admin editable).

    Punkty: placement / interview / recommendation / verification.
    Prizes: per-rank PLN amounts displayed na podium (1st = `prize_1`, etc).
    Thresholds: power_calling_min_per_day + linkedin_cv_per_md_target —
    konfigurowalne business thresholds (DR `system_config`).
    """

    model_config = ConfigDict(from_attributes=True)

    placement: int = Field(default=150, ge=0)
    interview: int = Field(default=15, ge=0)
    recommendation: int = Field(default=5, ge=0)
    verification: int = Field(default=0, ge=0)
    # Prize amounts in PLN — were hardcoded in frontend (Finding 30),
    # now configurable via Admin → Ustawienia.
    prize_1: int = Field(default=5000, ge=0, description="Nagroda za 1. miejsce (PLN)")
    prize_2: int = Field(default=3000, ge=0, description="Nagroda za 2. miejsce (PLN)")
    prize_3: int = Field(default=2000, ge=0, description="Nagroda za 3. miejsce (PLN)")
    # Business thresholds — hardcoded w Rekrutacja page.tsx (Finding 11),
    # teraz konfigurowalne. DR ma osobny `/config/power-calling-threshold` ale
    # u nas pakujemy razem ze scoringiem żeby uniknąć kolejnego endpointu.
    power_calling_min_per_day: int = Field(
        default=3,
        ge=0,
        le=10,
        description="Min. weryfikacji/dzień roboczy dla Power Calling badge",
    )
    linkedin_cv_per_md_target: int = Field(
        default=5,
        ge=0,
        le=20,
        description="Target CV/MD dla LinkedIn Performance badge",
    )


def _require_admin(current_user) -> None:  # type: ignore[no-untyped-def]
    # has_role() — primary + secondary roles (multi-role schema, PR #207).
    if not current_user.has_role(UserRole.admin):
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
    """Admin upsert do `dr_system_config.champions_league_scoring`.

    SQL note: asyncpg parses `:value::jsonb` as conflict with named-parameter
    syntax (`:value` followed by `::` triggers `syntax error at or near ":"`).
    Solution: use ANSI `CAST(:value AS jsonb)` instead of postgres shorthand.
    """
    import json

    _require_admin(current_user)
    value_json = payload.model_dump()
    await db.execute(
        text(
            """
            INSERT INTO dr_system_config (key, value, updated_at)
            VALUES (
                'champions_league_scoring',
                CAST(:value AS jsonb),
                CURRENT_TIMESTAMP
            )
            ON CONFLICT (key) DO UPDATE SET
                value = EXCLUDED.value,
                updated_at = CURRENT_TIMESTAMP
            """
        ),
        {"value": json.dumps(value_json)},
    )
    await db.commit()
    logger.info(
        "Champions League scoring updated by admin=%s: placement=%s interview=%s "
        "recommendation=%s verification=%s prize_1=%s prize_2=%s prize_3=%s "
        "pc_threshold=%s linkedin_target=%s",
        current_user.id,
        payload.placement,
        payload.interview,
        payload.recommendation,
        payload.verification,
        payload.prize_1,
        payload.prize_2,
        payload.prize_3,
        payload.power_calling_min_per_day,
        payload.linkedin_cv_per_md_target,
    )
    return payload
