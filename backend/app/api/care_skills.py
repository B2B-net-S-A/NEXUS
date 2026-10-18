"""Opieka · „Technologie do przejrzenia” — kolejka nieznanych technologii z kart.

Prefiks ``/api/care`` (wpięty w ``app/main.py`` obok ``contract_care``).
Czytają czytelnicy opieki i osoby od słownika umiejętności
(``ReviewReader``); decyzje zmieniają słownik całej aplikacji, więc podejmują
je admin, Head of Recruitment i TCM (``SkillCurator``). Bramki:
``app/api/care_gates.py``.
"""

from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.care_gates import ReviewReader, SkillCurator, can_curate
from app.core.database import get_db
from app.core.scheduling import local_now
from app.models.contract_care import SkillReviewItem
from app.models.skill import Skill
from app.models.user import User
from app.services.care import access as care_access
from app.services.care import skills as care_skills
from app.services.care import tech_map
from app.services.care.overview import person
from app.services.contract_care_schema import NAME_MAX

router = APIRouter()


@router.get("/skill-review")
async def skill_review(
    state: Literal["open", "closed"] = "open",
    current_user: User = Depends(ReviewReader),
    db: AsyncSession = Depends(get_db),
) -> dict:
    statuses = ("open",) if state == "open" else ("mapped", "created", "dismissed")
    items = (
        await db.scalars(
            select(SkillReviewItem)
            .where(SkillReviewItem.status.in_(statuses))
            .order_by(SkillReviewItem.occurrences.desc(), SkillReviewItem.name_key)
            .limit(300)
        )
    ).all()
    skill_ids = sorted({i.skill_id for i in items if i.skill_id})
    skill_names = (
        dict(
            (
                await db.execute(
                    select(Skill.id, Skill.canonical_name).where(
                        Skill.id.in_(skill_ids)
                    )
                )
            ).all()
        )
        if skill_ids
        else {}
    )
    names = await care_access.user_names(db, [i.reported_by for i in items])
    # Propozycje mapowania (tylko otwarte nazwy) — klik „Zmapuj na …” w kolejce.
    dictionary = await care_skills.load_dictionary(db) if state == "open" else None
    suggest = care_skills.suggester(dictionary) if dictionary is not None else None
    return {
        "items": [
            {
                "id": item.id,
                "name": item.name,
                "status": item.status,
                "occurrences": item.occurrences,
                "skill": (
                    {"id": item.skill_id, "name": skill_names.get(item.skill_id, "")}
                    if item.skill_id
                    else None
                ),
                "reported_by": person(item.reported_by, names),
                "suggestions": [
                    {"id": sid, "name": dictionary.names.get(sid, "")}
                    for sid in suggest(item.name)
                ]
                if suggest is not None and dictionary is not None
                else [],
                "created_at": item.created_at,
                "resolved_at": item.resolved_at,
            }
            for item in items
        ],
        "can_curate": can_curate(current_user),
    }


class MapSkillBody(BaseModel):
    skill_id: int


class CreateSkillBody(BaseModel):
    canonical_name: str = Field(min_length=1, max_length=NAME_MAX)
    category: Optional[str] = Field(default=None, max_length=64)


def _review_error(exc: care_skills.ReviewError) -> HTTPException:
    code = (
        status.HTTP_409_CONFLICT
        if exc.conflict
        else status.HTTP_422_UNPROCESSABLE_ENTITY
    )
    return HTTPException(code, str(exc))


@router.post("/skill-review/{item_id}/map")
async def map_review_item(
    item_id: int,
    body: MapSkillBody,
    current_user: User = Depends(SkillCurator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        clients = await care_skills.map_to_skill(
            db, item_id, body.skill_id, actor_id=current_user.id, now=local_now()
        )
    except care_skills.ReviewError as exc:
        await db.rollback()
        raise _review_error(exc) from exc
    await tech_map.invalidate(clients)
    return {"id": item_id, "status": "mapped", "skill_id": body.skill_id}


@router.post("/skill-review/{item_id}/create")
async def create_review_skill(
    item_id: int,
    body: CreateSkillBody,
    current_user: User = Depends(SkillCurator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        clients = await care_skills.create_skill(
            db,
            item_id,
            canonical_name=body.canonical_name,
            category=(body.category or "").strip() or None,
            actor_id=current_user.id,
            now=local_now(),
        )
    except care_skills.ReviewError as exc:
        await db.rollback()
        raise _review_error(exc) from exc
    await tech_map.invalidate(clients)
    item = await db.get(SkillReviewItem, item_id)
    return {
        "id": item_id,
        "status": "created",
        "skill_id": item.skill_id if item else None,
    }


@router.post("/skill-review/{item_id}/dismiss")
async def dismiss_review_item(
    item_id: int,
    current_user: User = Depends(SkillCurator),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        await care_skills.dismiss(
            db, item_id, actor_id=current_user.id, now=local_now()
        )
    except care_skills.ReviewError as exc:
        raise _review_error(exc) from exc
    return {"id": item_id, "status": "dismissed"}
