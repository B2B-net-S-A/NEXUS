"""Admin API ingestu profili Championa — cel POST-ów collectora z sesji Traffita.

UWAGA: ten moduł NIE może mieć ``from __future__ import annotations`` —
slowapi + Annotated multipart + PEP 563 przenosi guardy w parametry query
(422 na poprawnym body; ta sama pułapka co w candidate_activity_summary).

CORS — WAŻNE (zweryfikowane 2026-08-19): per-route CORS jest NIEWYKONALNY.
Starlette ``CORSMiddleware`` przechwytuje preflight OPTIONS dla origina spoza
``settings.CORS_ORIGINS`` i zwraca 400 BEZ ``Access-Control-Allow-Origin``
ZANIM żądanie dotrze do handlera tras — więc żaden ręczny nagłówek dopięty
tutaj nie odblokuje przeglądarki. Aby collector (karta traffit.com) mógł
POST-ować cross-origin, ``https://b2bnetwork.traffit.com`` MUSI być w env
``CORS_ORIGINS`` (świadoma aktywacja). Bez tego endpoint działa tylko dla
klientów nie-przeglądarkowych z tokenem (np. curl). Auth zawsze przez Bearer,
więc poszerzenie CORS o traffit samo w sobie niczego nie autoryzuje —
NEXUS nie używa cookie, a traffit origin nie ma tokenu użytkownika NEXUS.
"""

import logging

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminUser, get_db
from app.core.rate_limit import limiter
from app.models.ai_feature import AIFeatureKey
from app.models.job import Job
from app.services.ai_quota import AIQuotaExceeded, ai_feature
from app.services.champion_profile_ingest import (
    extract_document_text,
    ingest_parsed_profile,
    parse_champion_document,
    validate_upload,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/champion-profiles", tags=["admin-champion"])

# Origin collectora — do wpisania w env CORS_ORIGINS przy aktywacji przez
# przeglądarkę (patrz docstring modułu: per-route CORS jest niewykonalny).
COLLECTOR_ORIGIN = "https://b2bnetwork.traffit.com"


def _json(payload: dict, status_code: int = 200) -> JSONResponse:
    return JSONResponse(payload, status_code=status_code)


@router.get("/coverage")
async def champion_coverage(
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """Zestaw external_id traffitowych ofert Z profilem — diff dla collectora.

    Collector liczy `braki = mapa_traffit − covered` lokalnie; dzięki temu
    każdy kolejny bieg (świeży sync) płaci tylko za realnie brakujące pliki.
    """
    rows = (
        await db.execute(
            select(Job.external_id).where(
                Job.external_source == "traffit",
                Job.champion_profile.is_not(None),
            )
        )
    ).all()
    covered = sorted({int(eid) for (eid,) in rows if eid and str(eid).isdigit()})
    total_traffit = (
        await db.execute(select(Job.id).where(Job.external_source == "traffit"))
    ).all()
    return _json(
        {
            "covered_external_ids": covered,
            "covered_count": len(covered),
            "traffit_jobs_total": len(total_traffit),
        }
    )


@router.post("/ingest")
# 120/min, nie 30: powierzchnia admin-only, a realny koszt ogranicza sam parse
# LLM (~2-4 s/plik). 30/min dławiło BURSTY tanich odpowiedzi skip/no_job
# collectora (pauza 150 ms), zamieniając idempotentny re-run w ścianę 429.
@limiter.limit("120/minute")
async def champion_ingest(
    request: Request,
    current_user: AdminUser,
    file: UploadFile = File(...),
    external_rid: str = Form(...),
    file_id: int = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """Jeden plik profilu (docx/pdf) → parse (Haiku, kwota) → FILL_EMPTY do oferty.

    Idempotentny: oferta z niepustym profilem wraca jako
    ``champion_skipped_nonempty`` bez wywołania AI — ponowny bieg collectora
    na pokrytych rekrutacjach jest darmowy.
    """
    content = await file.read()
    error = validate_upload(file.filename or "", len(content), external_rid)
    if error:
        return _json({"detail": error}, status_code=422)
    rid = int(external_rid)

    # Tani pre-check PRZED kosztem LLM: oferta nieznana albo już pokryta
    # nie powinna palić kwoty.
    job = (
        await db.execute(
            select(Job).where(
                Job.external_source == "traffit", Job.external_id == str(rid)
            )
        )
    ).scalar_one_or_none()
    if job is None:
        return _json({"outcome": "no_job", "external_rid": rid})
    if isinstance(job.champion_profile, dict) and job.champion_profile:
        return _json(
            {
                "outcome": "champion_skipped_nonempty",
                "external_rid": rid,
                "job_id": job.id,
            }
        )

    text = extract_document_text(content, file.filename or "")
    if not text or len(text) < 200:
        return _json({"outcome": "no_text", "external_rid": rid}, status_code=422)

    try:
        async with ai_feature(db, AIFeatureKey.champion_profile_parse):
            parsed = await parse_champion_document(text)
    except AIQuotaExceeded as exc:
        return _json({"detail": str(exc)}, status_code=503)
    except ValueError as exc:
        logger.warning("champion-ingest: parse padł dla rid=%s: %s", rid, exc)
        return _json(
            {"outcome": "parse_failed", "external_rid": rid, "detail": str(exc)},
            status_code=422,
        )

    outcome = await ingest_parsed_profile(
        db, external_rid=rid, file_id=file_id, parsed=parsed
    )
    logger.info("champion-ingest: rid=%s -> %s", rid, outcome.get("outcome"))
    return _json(outcome)


# Uwaga kontraktowa: 401/403 od zależności auth NIE niosą nagłówków CORS
# (HTTPException omija _cors). To celowe — skrypt na obcym originie nie
# odczyta nawet kodu odmowy.
