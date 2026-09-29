"""„Champion po ludzku” — odświeżenie tekstów rekrutacji (płatny model).

``POST /api/jobs/{job_id}/plain-brief/refresh`` dopasowuje rolę, uzupełnia
brakujące hasła słowniczka, rolę i opis klienta researchem w internecie
(najwyżej trzy w żądaniu, reszta w tle) i liczy teksty rekrutacji. Zwraca to
samo co GET.

To zapis do pamięci podręcznej, nie zmiana danych biznesowych — stoi
w ``READ_ONLY_POST_ROUTE_TEMPLATES``, więc przechodzi rola z samym odczytem
Pipeline. W „podglądzie jako” 403 (nie płacimy za cudzy podgląd).

Osobny moduł, bo każda trasa w module z listy ``_RATE_LIMITED_MODULES`` musi
mieć limit. Bez ``from __future__ import annotations`` (slowapi #579).
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_db
from app.api.plain_brief import can_change_role, is_previewing, load_job
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.core.rate_limit import limiter, user_or_ip_key
from app.models.job import Job
from app.services.plain_knowledge import view

router = APIRouter(dependencies=PIPELINE_SECTION_DEPENDENCIES)


@router.post("/jobs/{job_id}/plain-brief/refresh")
@limiter.limit("10/minute", key_func=user_or_ip_key)
async def refresh_plain_brief(
    job_id: int,
    request: Request,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    if is_previewing(request):
        raise HTTPException(
            status_code=403,
            detail="W podglądzie jako inny użytkownik wyjaśnienie się nie odświeża.",
        )
    await load_job(db, current_user, job_id)
    # Wszystko, co potrzebne z `current_user`, czytamy PRZED odświeżeniem: awaria
    # modelu kończy się rollbackiem, który wygasza obiekty sesji żądania, a odczyt
    # wygasłego użytkownika to MissingGreenlet (500 bez CORS).
    user_id = current_user.id
    may_change_role = can_change_role(current_user)
    await view.refresh(db, job_id, user_id=user_id)
    job = await db.get(Job, job_id, populate_existing=True)
    if job is None:
        raise HTTPException(status_code=404, detail="Rekrutacja nie istnieje.")
    return await view.build_view(
        db, job, can_refresh=True, can_change_role=may_change_role
    )
