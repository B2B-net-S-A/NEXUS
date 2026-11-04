"""Ustawienia → Ocena prepów (0505, decyzje Artura 22.10.2026).

Odczyt: rekruter, Delivery Lead, Head of Recruitment i admin — każdy, kto
dostaje ocenę prepu, widzi, jak jest liczona. Zapis (publikacja nowej
wersji): Head of Recruitment i admin. Bramka sekcji Pipeline na routerze,
jak trasy prepów (``api/prep_meetings.py``).
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import HeadOfRecruitmentPlus, require_roles
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.models.user import User, UserRole
from app.services import prep_review_config as cfg

router = APIRouter(dependencies=PIPELINE_SECTION_DEPENDENCIES)

ConfigReader = require_roles(
    UserRole.head_of_recruitment, UserRole.delivery_lead, UserRole.recruiter
)


class PublishIn(BaseModel):
    config: cfg.PrepReviewConfig
    reason: Optional[str] = Field(default=None, max_length=500)


async def _state(db: AsyncSession, user: User) -> dict:
    config, version = await cfg.current(db)
    return {
        "config": config.model_dump(),
        "version": version,
        "defaults": cfg.defaults().model_dump(),
        "can_edit": user.has_any_role(UserRole.admin, UserRole.head_of_recruitment),
        "history": await cfg.history(db),
    }


@router.get("")
async def get_prep_review_config(
    current_user: User = Depends(ConfigReader),
    db: AsyncSession = Depends(get_db),
):
    """Obowiązujące ustawienia oceny, startowe (do „Przywróć startowe”) i historia."""
    return await _state(db, current_user)


@router.put("")
async def publish_prep_review_config(
    payload: PublishIn,
    current_user: HeadOfRecruitmentPlus,
    db: AsyncSession = Depends(get_db),
):
    """Publikuje nową wersję; działa od następnej oceny prepu."""
    _row, saved = await cfg.publish(
        db, actor=current_user, config=payload.config, reason=payload.reason
    )
    if saved:
        await db.commit()
    state = await _state(db, current_user)
    state["saved"] = saved
    return state
