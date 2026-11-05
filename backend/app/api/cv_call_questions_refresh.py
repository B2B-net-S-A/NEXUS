"""Pytania pod CV w ściądze do rozmowy — odświeżenie (płatny model, migracja 0651).

``POST /api/candidates/{candidate_id}/jobs/{job_id}/call-questions/refresh`` liczy
pytania, gdy ich nie ma albo zmieniło się CV lub Champion. Zwraca to samo co GET.

To zapis do pamięci podręcznej, nie zmiana danych biznesowych, więc stoi
w ``READ_ONLY_POST_ROUTE_TEMPLATES``. W „podglądzie jako” 403 (nie płacimy za
cudzy podgląd). Osobny moduł, bo każda trasa w module z listy
``_RATE_LIMITED_MODULES`` musi mieć limit. Bez ``from __future__ import
annotations`` (slowapi #579).
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_db
from app.api.plain_brief import is_previewing
from app.api.recruitment_access import ensure_job_read_access
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.core.rate_limit import limiter, user_or_ip_key
from app.services import cv_call_questions

router = APIRouter(dependencies=PIPELINE_SECTION_DEPENDENCIES)


@router.post("/candidates/{candidate_id}/jobs/{job_id}/call-questions/refresh")
@limiter.limit("20/minute", key_func=user_or_ip_key)
async def refresh_call_questions(
    candidate_id: int,
    job_id: int,
    request: Request,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    if is_previewing(request):
        raise HTTPException(
            status_code=403,
            detail="W podglądzie jako inny użytkownik pytania się nie odświeżają.",
        )
    await ensure_job_read_access(db, current_user, job_id)
    # Odczyt PRZED odświeżeniem: awaria modelu kończy się rollbackiem, który
    # wygasza obiekty sesji żądania, a odczyt wygasłego użytkownika to 500.
    user_id = current_user.id
    await cv_call_questions.refresh(db, candidate_id, job_id, user_id=user_id)
    return await cv_call_questions.build_view(
        db, candidate_id, job_id, can_refresh=True
    )
