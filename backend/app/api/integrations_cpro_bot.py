"""Bot Cpro (Grok Bot): pełne zlecenie, plik CV i przyjęcie raportu.

* ``GET /api/integrations/cpro-bot/runs/{run_id}/task`` — pełne zlecenie,
  pobierane po krótkiej kopercie webhooka (Grok może obciąć długi webhook).
* ``GET /api/integrations/cpro-bot/runs/{run_id}/cv/{stage_id}`` — zatwierdzone
  CV firmowe karty z biegu (PDF, nazwa bez ``#``); historyczne zlecenia
  zachowują swój plik DOCX.
* ``POST /api/integrations/cpro-bot/runs/{run_id}`` — raport biegu.

Poświadczeniem tras jest jednorazowy token biegu z webhooka (nagłówek
``X-Run-Token``): działa tylko dla tego biegu, do przyjęcia raportu i najwyżej
2 godziny. Brak biegu, zły, zużyty i wygasły token dają tę samą odpowiedź 401.
Sesja użytkownika go nie zastępuje. Trasy działają także przy wyłączonym
``CPRO_BOT_ENABLED``: bez biegu nie ma tokenu. Zlecenie i CV zawierają dane
kandydata, wyłącznie dla tego biegu; logi to same liczby.

Bez ``from __future__ import annotations``: moduł ma ``@limiter.limit``, a z nim
ciało żądania lądowałoby jako parametr query (422).
"""

import logging
from types import SimpleNamespace
from datetime import datetime, timezone
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.integrations_sales_signals import parse_report, read_limited
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.models.candidate_stage_cv import CandidateStageCV
from app.services import candidate_audit
from app.services.cv_approved_docx import without_empty_underline
from app.services.cv_download_log import log_cv_download
from app.models.cpro_bot import CproBotRun
from app.services.cpro_bot import ingest, offer_text, runs
from app.services.cv_pdf_preview import (
    MSG_UNAVAILABLE,
    PdfPreviewUnavailable,
    pdf_from_docx,
)
from app.services.sales.bot_tasks.base import numbers_only
from app.core.http_headers import content_disposition_attachment

logger = logging.getLogger(__name__)

router = APIRouter()

AUDIT_ENDPOINT = "cpro_bot_cv"

DOCX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)


async def require_cpro_run_token(
    run_id: int,
    x_run_token: Annotated[Optional[str], Header()] = None,
    db: AsyncSession = Depends(get_db),
) -> CproBotRun:
    """Własne poświadczenie trasy: token biegu, zablokowany wiersz biegu."""

    now = datetime.now(timezone.utc)
    run = await db.get(CproBotRun, run_id)
    if run is not None and runs.token_matches(run, x_run_token, now):
        run = await db.get(
            CproBotRun, run_id, with_for_update=True, populate_existing=True
        )
        if run is not None and runs.token_matches(run, x_run_token, now):
            return run
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=runs.INVALID_TOKEN_DETAIL)


@router.get("/runs/{run_id}/task")
@limiter.limit("60/minute")
async def download_task(
    request: Request,
    run: CproBotRun = Depends(require_cpro_run_token),
) -> JSONResponse:
    """Pełna treść zlecenia bez nowego tokenu i wewnętrznych danych kart."""

    return JSONResponse(
        content=runs.task_body(run),
        headers={"Cache-Control": "private, no-store"},
    )


@router.get("/runs/{run_id}/cv/{stage_id}")
@limiter.limit("60/minute")
async def download_cv(
    request: Request,
    stage_id: int,
    run: CproBotRun = Depends(require_cpro_run_token),
    db: AsyncSession = Depends(get_db),
) -> Response:
    from app.api.candidate_stage_cv import approved_version_for_download  # noqa: PLC0415

    if stage_id not in {int(s) for s in run.stage_ids or []}:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail="Nie ma tej karty w biegu."
        )
    item = next(
        (
            i
            for i in (run.request or {}).get("items", [])
            if int(i.get("ref", 0)) == stage_id
        ),
        None,
    )
    card = ((run.request or {}).get("cards") or {}).get(str(stage_id)) or {}
    cv_stage_id = card.get("cv_stage_id")
    csv = await db.scalar(
        select(CandidateStageCV).where(
            CandidateStageCV.candidate_stage_id == int(cv_stage_id or 0)
        )
    )
    if item is None or csv is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Brak zatwierdzonego CV.")
    offer = item.get("offer") or {}
    file_format = offer.get("cv_format", "docx")
    if file_format not in ("pdf", "docx"):
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="Nieznany format CV biegu."
        )
    version_number = offer.get("cv_version")
    if version_number is None and file_format == "docx":
        # Stare zlecenia nie zamrażały numeru: zachowują dotychczasowe
        # pobranie bieżącej zatwierdzonej wersji, zamiast zgadywania z dat.
        if csv.branded_status != "finalized":
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, detail="Brak zatwierdzonego CV."
            )
        version_number = csv.branded_version
    elif type(version_number) is not int or version_number <= 0:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="Niepoprawna wersja CV biegu."
        )
    version = await approved_version_for_download(db, csv, version_number)
    filename = offer_text.safe_filename(
        offer.get("cv_file_name"), extension=f".{file_format}"
    )
    run_id = run.id
    if file_format == "pdf":
        # Ten sam firmowy PDF co podgląd zatwierdzonej wersji. Link dostępowy
        # do osobnego panelu klienta nie jest częścią załącznika oferty w Cpro.
        docx = version.docx_content
        # Konwersja może potrwać kilkadziesiąt sekund: nie trzymamy w tym
        # czasie połączenia i blokady biegu. Żadnego wpisu pobrania jeszcze.
        await db.commit()
        try:
            content = await pdf_from_docx(docx)
        except PdfPreviewUnavailable as error:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, detail=MSG_UNAVAILABLE
            ) from error
        # Raport lub wygaśnięcie tokenu w czasie konwersji odbiera dostęp;
        # ponownie blokujemy bieg przed wydaniem CV i wpisem audytu.
        await require_cpro_run_token(run_id, request.headers.get("X-Run-Token"), db)
    else:
        # Historyczny DOCX zachowuje własny format i czyszczenie podkreśleń.
        content = without_empty_underline(version.docx_content)
    # Ślad wydania CV jak w API v1: dziennik pobrań i audyt kandydata, dopiero
    # przy oddanym pliku (odmowa zgody 409 nie jest pobraniem). To transfer do
    # bota poza EOG — musi być widoczny w „kto dostał moje CV”.
    await log_cv_download(
        db,
        intent="download",
        surface=None,
        entity_type="candidate_stage_cv",
        entity_id=csv.id,
        user=SimpleNamespace(id=None),
        file_format=file_format,
        state="approved",
        version=version.version,
    )
    candidate_audit.record_candidate_audit(
        db,
        action=candidate_audit.CV_DOWNLOADED,
        user_id=None,
        entity_id=csv.candidate_id,
        details={"endpoint": AUDIT_ENDPOINT, "format": file_format, "run_id": run_id},
    )
    # Bieg trzyma blokadę wiersza z poświadczenia; plik nie potrzebuje transakcji.
    await db.commit()
    logger.info("cpro_bot run=%s cv served", run_id)
    return Response(
        content=content,
        media_type="application/pdf" if file_format == "pdf" else DOCX_MEDIA_TYPE,
        headers={
            "Content-Disposition": content_disposition_attachment(filename),
            "Cache-Control": "private, no-store",
            "X-CV-Version": str(version.version),
        },
    )


@router.post("/runs/{run_id}")
@limiter.limit("30/minute")
async def receive_report(
    request: Request,
    run: CproBotRun = Depends(require_cpro_run_token),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    run_id = run.id
    raw = await read_limited(request)
    report = parse_report(raw, ingest.CproReport)
    summary = await ingest.apply_report(db, run, report, now=now)
    counts = summary.get("counts", {})
    logger.info(
        "cpro_bot run=%s received submitted=%s draft=%s failed=%s moved=%s",
        run_id,
        counts.get("submitted", 0),
        counts.get("draft", 0),
        counts.get("failed", 0),
        counts.get("moved", 0),
    )
    return {"status": "received", **numbers_only(counts)}
