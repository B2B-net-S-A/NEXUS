"""„Nowe CV”, strona 1 — najmocniejszy wynik z CV (wariant E2, 22.11.2026).

``POST /api/candidates/stages/{stage_id}/cv/page1/results`` liczy od nowa listę
zdań „najmocniejszy wynik” z bieżącej treści edytora CV etapu i oddaje
zaktualizowane dodatki strony 1 (`page1_extras`: `results`, `result_index`,
`results_source_sha` i reszta kluczy bez zmian). Od 25.11.2026 ten sam bieg
układa też zdania 1–3 strony 1 (`why_generated`, `why`; „Ułóż zdania od
nowa” w edytorze, `services/cv_page1_why.py`). Logika:
`services/cv_page1_results.py`.

``POST /api/candidates/stages/{stage_id}/cv/page1/highlight`` (26.11.2026)
szuka od nowa propozycji wyróżnika pod nazwiskiem (nagroda, wyróżnienie,
certyfikat z MUST, każda z cytatem sprawdzonym kodem) i oddaje dodatki
strony 1 z `highlight_proposals`. Propozycja trafia do CV dopiero po
przyjęciu przez rekrutera (`PATCH …/cv/page1`). Logika:
`services/cv_page1_highlight.py`, własny klucz AI `cv_page1_highlight`.

Bramki jak przy innych trasach CV etapu (`_load_csv_for_stage`: zespół
rekrutacji, prawo do zapisu). Awaria modelu = 503 z polskim komunikatem,
a strona 1 bierze dalej trzeci punkt „Dlaczego”. Osobny moduł, bo trasa ma
limit żądań (płatny model), a `candidate_stage_cv.py` ma
``from __future__ import annotations``. Bez tego importu tutaj — slowapi #579.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.candidate_access import CandidateWriteAccess
from app.api.candidate_stage_cv import _load_csv_for_stage
from app.core.database import get_db
from app.core.rate_limit import limiter, user_or_ip_key
from app.services import cv_layout as layout_service
from app.services import cv_page1_highlight as page1_highlight
from app.services import cv_page1_results as page1_results

router = APIRouter()

LIMIT = "20/minute"


@router.post("/candidates/stages/{stage_id}/cv/page1/results")
@limiter.limit(LIMIT, key_func=user_or_ip_key)
async def refresh_stage_cv_page1_results(
    stage_id: int,
    request: Request,
    current_user: CandidateWriteAccess,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Znajdź od nowa najmocniejsze wyniki i zdania 1–3 strony 1 „Nowego CV”."""
    if not layout_service.enabled():
        raise HTTPException(409, layout_service.MSG_DISABLED)
    # Odczyt PRZED modelem: awaria kończy się rollbackiem, który wygasza
    # obiekty sesji żądania, a odczyt wygasłego użytkownika to 500.
    user_id = current_user.id
    csv = await _load_csv_for_stage(db, stage_id, current_user)
    if csv.branded_status == "none" or not (csv.branded_draft_html or "").strip():
        raise HTTPException(409, layout_service.MSG_NO_CV)
    outcome = await page1_results.refresh_stage_cv(
        db, csv.id, user_id=user_id, force=True
    )
    if outcome.status == page1_results.FAILED:
        raise HTTPException(503, page1_results.MSG_FAILED)
    return dict(outcome.extras or {})


@router.post("/candidates/stages/{stage_id}/cv/page1/highlight")
@limiter.limit(LIMIT, key_func=user_or_ip_key)
async def refresh_stage_cv_page1_highlight(
    stage_id: int,
    request: Request,
    current_user: CandidateWriteAccess,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Poszukaj od nowa propozycji wyróżnika strony 1 „Nowego CV”."""
    if not layout_service.enabled():
        raise HTTPException(409, layout_service.MSG_DISABLED)
    user_id = current_user.id
    csv = await _load_csv_for_stage(db, stage_id, current_user)
    if csv.branded_status == "none" or not (csv.branded_draft_html or "").strip():
        raise HTTPException(409, layout_service.MSG_NO_CV)
    outcome = await page1_highlight.refresh_highlight(
        db, csv.id, user_id=user_id, force=True
    )
    if outcome.status == page1_highlight.FAILED:
        raise HTTPException(503, page1_highlight.MSG_FAILED)
    return dict(outcome.extras or {})
