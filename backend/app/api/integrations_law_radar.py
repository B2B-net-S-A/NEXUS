"""Pobranie zlecenia i przyjęcie raportu botów radaru przepisów.

``GET /api/integrations/law-radar/runs/{run_id}`` (``request_url`` z webhooka v2)
zwraca zlecenie Zbieracza albo Analityka (``task``, ``report_format``, ``request``,
``callback_url``) bez zużywania tokenu. ``POST`` na ten sam adres przyjmuje raport.
Obie metody wymagają nagłówka ``X-Run-Token``; bieg v1 nie ma GET (401).
Poświadczeniem jest jednorazowy token biegu z webhooka startowego: działa tylko
dla tego biegu, przy jednym zapisie i najwyżej 2 godziny. Brak biegu, zły, zużyty
i wygasły token dają tę samą odpowiedź 401. Sesja użytkownika go nie zastępuje.

Treść: najwyżej 512 KB (413), sprawdzana modelem rodzaju biegu (422, token
zostaje ważny). Po raporcie Zbieracza bramka i start Analityka biegną w tle
(``flow.after_collect``), żeby bot nie czekał na API Sejmu. Po raporcie
Analityka NEXUS od razu przelicza sondy dotkniętych zmian. Odpowiedź dla bota
i logi to same liczby. Trasa działa także przy wyłączonym ``LAW_RADAR_ENABLED``:
bez biegu nie ma tokenu.

Bez ``from __future__ import annotations``: moduł ma ``@limiter.limit``, a z nim
ciało żądania lądowałoby jako parametr query (422).
"""

import logging
from datetime import datetime, timezone
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.integrations_sales_signals import parse_report, read_limited
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.core.scheduling import business_date
from app.core.tasks import spawn
from app.models.law_radar import LawRadarRun
from app.services.law_radar import analyze, collect, flow, probes, runs
from app.services.sales.bot_tasks.base import numbers_only

logger = logging.getLogger(__name__)

router = APIRouter()


async def require_law_run_token(
    run_id: int,
    x_run_token: Annotated[Optional[str], Header()] = None,
    db: AsyncSession = Depends(get_db),
) -> LawRadarRun:
    """Własne poświadczenie trasy: token biegu, zablokowany wiersz biegu.

    Najpierw tani odczyt bez blokady (zły token nie trzyma blokady biegu), potem
    blokada i ponowne sprawdzenie, żeby dwa równoległe raporty nie przeszły oba.
    """

    now = datetime.now(timezone.utc)
    run = await db.get(LawRadarRun, run_id)
    if run is not None and runs.token_matches(run, x_run_token, now):
        run = await db.get(
            LawRadarRun, run_id, with_for_update=True, populate_existing=True
        )
        if run is not None and runs.token_matches(run, x_run_token, now):
            return run
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=runs.INVALID_TOKEN_DETAIL)


@router.get("/runs/{run_id}")
@limiter.limit("30/minute")
async def get_run_request(
    request: Request,
    response: Response,
    run: LawRadarRun = Depends(require_law_run_token),
) -> dict[str, Any]:
    if not runs.uses_request_fetch(run):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, detail=runs.INVALID_TOKEN_DETAIL
        )
    response.headers["Cache-Control"] = "no-store"
    logger.info("law_radar run=%s kind=%s request fetched", run.id, run.kind)
    return runs.request_body(run)


@router.post("/runs/{run_id}")
@limiter.limit("30/minute")
async def receive_report(
    request: Request,
    run: LawRadarRun = Depends(require_law_run_token),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    run_id = run.id
    raw = await read_limited(request)
    if run.kind == collect.KIND:
        report = parse_report(raw, collect.CollectReport)
        summary = await collect.ingest(db, run, report, now=now)
        await db.commit()
        if summary["new"]:
            spawn(flow.after_collect_in_background(run_id), "law_radar_after_collect")
    else:
        report = parse_report(raw, analyze.AnalyzeReport)
        if runs.uses_analyze_request_fetch(run) and not analyze.report_covers_request(
            run, report
        ):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="reviewed_item_ids musi zawierać dokładnie wszystkie pozycje zlecenia.",
            )
        summary = await analyze.ingest(db, run, report, now=now)
        await db.commit()
        try:
            await probes.recompute(
                db, summary["change_ids"], now=now, today=business_date(now)
            )
        except Exception:  # noqa: BLE001 — raport już zapisany, sondy przeliczy pętla
            await db.rollback()
            logger.exception("law_radar run=%s probe recompute failed", run_id)
    return {"status": "received", **numbers_only(summary)}
