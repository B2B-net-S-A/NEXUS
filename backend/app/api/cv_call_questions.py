"""Pytania pod CV w ściądze do rozmowy — odczyt (migracja 0650).

``GET /api/candidates/{candidate_id}/jobs/{job_id}/call-questions`` nic nie
zapisuje, nie woła modelu i nie pobiera pliku CV. Odświeżenie (płatny model) jest
w ``cv_call_questions_refresh.py``, osobnym module z limitem żądań.

Moduł bez ``from __future__ import annotations``, jak ``plain_brief.py``.
"""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_db
from app.api.plain_brief import is_previewing
from app.api.recruitment_access import ensure_job_read_access
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.services import cv_call_questions

router = APIRouter(dependencies=PIPELINE_SECTION_DEPENDENCIES)


@router.get("/candidates/{candidate_id}/jobs/{job_id}/call-questions")
async def get_call_questions(
    candidate_id: int,
    job_id: int,
    request: Request,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    await ensure_job_read_access(db, current_user, job_id)
    return await cv_call_questions.build_view(
        db, candidate_id, job_id, can_refresh=not is_previewing(request)
    )
