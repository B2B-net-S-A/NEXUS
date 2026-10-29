"""Insights → „Rytm dnia” (decyzje Artura 28–29.10.2026).

Na razie całą zakładkę — rytm, intensywność, CV do klienta i podpowiedź dla
lidera — widzą tylko Head of Recruitment i admin (29.10.2026; wcześniej
„widzi cały zespół”). Oni też zmieniają reguły (wagi, progi, normy).
"""

import hashlib
import json
import logging
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_roles
from app.api.section_access import INSIGHTS_SECTION_DEPENDENCIES
from app.core.cache import cache_get, cache_set, cache_single_flight
from app.core.database import get_db
from app.core.scheduling import business_today
from app.models.user import User
from app.services.work_rhythm import (
    DEFAULT_RULES,
    KINDS,
    RULES_EDITOR_ROLES,
    VIEWER_ROLES,
    RHYTHM_START,
    build_day,
    build_rhythm,
    clamp_window,
    load_rules,
    rules_from_json,
    save_rules,
)

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=INSIGHTS_SECTION_DEPENDENCIES)

CACHE_TTL_SECONDS = 120

Viewer = Annotated[User, Depends(require_roles(*VIEWER_ROLES))]
RulesEditor = Annotated[User, Depends(require_roles(*RULES_EDITOR_ROLES))]


def can_edit_rules(user: User) -> bool:
    return user.has_any_role(*RULES_EDITOR_ROLES)


class WorkRhythmRulesIn(BaseModel):
    weights: dict[str, float]
    hour_levels: list[float] = Field(min_length=3, max_length=3)
    work_hour_min_points: float = Field(gt=0, le=100)
    norm_work_hours: float = Field(ge=1, le=10)
    norm_day_points: float = Field(ge=10, le=1000)
    level_high: int = Field(ge=1, le=100)
    level_mid: int = Field(ge=1, le=100)
    diag_intensity: int = Field(ge=1, le=100)
    diag_results_pct: int = Field(ge=1, le=300)
    # Ochrona przed nabijaniem (29.10.2026); limit 0 = bez limitu.
    auto_cv_points: float = Field(DEFAULT_RULES["auto_cv_points"], ge=0, le=20)
    screening_per_candidate_day: int = Field(
        DEFAULT_RULES["screening_per_candidate_day"], ge=0, le=50
    )
    repeats_per_hour: int = Field(DEFAULT_RULES["repeats_per_hour"], ge=0, le=50)
    views_per_hour: int = Field(DEFAULT_RULES["views_per_hour"], ge=0, le=200)
    bulk_per_minute: int = Field(DEFAULT_RULES["bulk_per_minute"], ge=0, le=200)
    stage_return_points: float = Field(
        DEFAULT_RULES["stage_return_points"], ge=0, le=20
    )
    contacts_per_day: int = Field(DEFAULT_RULES["contacts_per_day"], ge=0, le=500)
    thin_hour_candidates: int = Field(
        DEFAULT_RULES["thin_hour_candidates"], ge=0, le=10
    )

    @model_validator(mode="after")
    def _consistent(self) -> "WorkRhythmRulesIn":
        if set(self.weights) != set(KINDS):
            raise ValueError("Podaj wagę dla każdego rodzaju akcji.")
        if any(not 0 <= w <= 20 for w in self.weights.values()):
            raise ValueError("Waga akcji musi być między 0 a 20 pkt.")
        low, mid, high = self.hour_levels
        if not 0 < low < mid < high <= 200:
            raise ValueError(
                "Progi godziny muszą rosnąć: robocza < intensywna < bardzo intensywna."
            )
        if self.level_mid >= self.level_high:
            raise ValueError("Próg „średnia” musi być niższy niż „wysoka”.")
        return self


@router.get("/work-rhythm")
async def insights_work_rhythm(
    current_user: Viewer,
    db: AsyncSession = Depends(get_db),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
):
    """Rytm dnia rekruterów: punkty pracy godzina po godzinie, urlopy, spotkania,
    intensywność, CV do klienta i podpowiedź dla lidera."""
    today = business_today()
    start, end = clamp_window(date_from, date_to, today)
    rules = await load_rules(db)
    rules_hash = hashlib.sha1(
        json.dumps(rules.as_json(), sort_keys=True).encode()
    ).hexdigest()[:10]
    cache_key = f"insights:work-rhythm:v2:{start}:{end}:{today}:{rules_hash}"
    async with cache_single_flight(cache_key, db=db):
        cached = await cache_get(cache_key)
        if cached is None:
            cached = await build_rhythm(
                db, start=start, end=end, with_results=True, today=today
            )
            await cache_set(cache_key, cached, ttl_seconds=CACHE_TTL_SECONDS)
    return {
        **cached,
        "can_edit_rules": can_edit_rules(current_user),
        "with_results": True,
    }


@router.get("/work-rhythm/day")
async def insights_work_rhythm_day(
    current_user: Viewer,
    user_id: int = Query(...),
    day: date = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Rozkład dnia osoby: każda akcja, ile dała punktów, a jeśli nic — dlaczego."""
    if day < RHYTHM_START or day > business_today():
        raise HTTPException(status_code=422, detail="Ten dzień jest poza Rytmem dnia.")
    out = await build_day(db, user_id, day)
    if out is None:
        raise HTTPException(status_code=404, detail="Tej osoby nie ma w Rytmie dnia.")
    return out


@router.get("/work-rhythm/rules")
async def insights_work_rhythm_rules(
    current_user: Viewer,
    db: AsyncSession = Depends(get_db),
):
    rules = await load_rules(db)
    return {"rules": rules.as_json(), "can_edit": can_edit_rules(current_user)}


@router.put("/work-rhythm/rules")
async def update_work_rhythm_rules(
    payload: WorkRhythmRulesIn,
    current_user: RulesEditor,
    db: AsyncSession = Depends(get_db),
):
    """Zapis wag, progów i norm (Head of Recruitment, admin)."""
    rules = rules_from_json(payload.model_dump())
    await save_rules(db, rules, current_user.id)
    logger.info("work rhythm rules updated by user_id=%s", current_user.id)
    return {"rules": rules.as_json(), "can_edit": True}
