"""CompetenceCategory API — list + per-CC recruiters lookup.

Publiczny dla zalogowanych userów. Lista jest tania (5 rows) i stabilna,
więc frontend może ją cache'ować z React Query przez cały session.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, OperationalUser
from app.core.database import get_db
from app.models.competence_category import (
    CompetenceCategory,
    UserCompetenceCategory,
)
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter()


class CompetenceCategoryOut(BaseModel):
    id: int
    slug: str
    name_pl: str
    name_en: str
    description: str
    keywords: list[str] = []
    display_order: int

    model_config = {"from_attributes": True}


class CcRecruiterOut(BaseModel):
    user_id: int
    name: str
    email: str
    role: Optional[str] = None
    is_primary: bool
    priority: Optional[int] = None  # 1 = 1st priority sourcer, 2 = 2nd priority


@router.get("", response_model=list[CompetenceCategoryOut])
async def list_competence_categories(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    active_only: bool = Query(True),
):
    """Return all CompetenceCategories (5 seed rows) ordered by display_order."""
    stmt = select(CompetenceCategory).order_by(CompetenceCategory.display_order)
    if active_only:
        stmt = stmt.where(CompetenceCategory.is_active.is_(True))
    result = await db.execute(stmt)
    return [CompetenceCategoryOut.model_validate(cc) for cc in result.scalars().all()]


@router.get("/{cc_id}/recruiters", response_model=list[CcRecruiterOut])
async def list_cc_recruiters(
    cc_id: int,
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
    priority: Optional[int] = Query(None, ge=1, le=2),
):
    """Return users assigned to the given Competence Category.

    Filter `priority` narrows to sourcer tier (1 = 1st priority, 2 = 2nd).
    When unset, returns everyone — primary DL + all sourcers for the CC.
    """
    cc = await db.scalar(
        select(CompetenceCategory).where(CompetenceCategory.id == cc_id)
    )
    if not cc:
        raise HTTPException(status_code=404, detail="Competence Category not found")

    stmt = (
        select(UserCompetenceCategory, User)
        .join(User, UserCompetenceCategory.user_id == User.id)
        .where(UserCompetenceCategory.competence_category_id == cc_id)
    )
    if priority is not None:
        stmt = stmt.where(UserCompetenceCategory.priority == priority)
    rows = (await db.execute(stmt)).all()

    out: list[CcRecruiterOut] = []
    for ucc, user in rows:
        out.append(
            CcRecruiterOut(
                user_id=user.id,
                name=(user.name or "").strip() or user.email,
                email=user.email,
                role=getattr(getattr(user, "role", None), "value", None),
                is_primary=ucc.is_primary,
                priority=ucc.priority,
            )
        )
    # Sort: is_primary first, then by priority (1 before 2), then by name
    out.sort(
        key=lambda r: (
            not r.is_primary,
            r.priority if r.priority is not None else 99,
            r.name.lower(),
        )
    )
    return out
