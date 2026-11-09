"""Przyjęcie raportu bota researchu (Grok Bot) dla jednego biegu.

``POST /api/integrations/sales-signals/runs/{run_id}`` z nagłówkiem ``X-Run-Token``.
Poświadczeniem jest jednorazowy token biegu z webhooka startowego: działa tylko
dla tego biegu, tylko raz i najwyżej 2 godziny. Brak biegu, zły, zużyty i wygasły
token dają tę samą odpowiedź 401, żeby nie dało się zgadywać numerów biegów.

Bez ``from __future__ import annotations``: moduł ma ``@limiter.limit``, a z nim
ciało żądania lądowałoby jako parametr query (422).
"""

import logging
from datetime import datetime, timezone
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rate_limit import limiter
from app.models.sales import SalesSignalRun
from app.services.sales import signals

logger = logging.getLogger(__name__)

router = APIRouter()


async def require_signal_run_token(
    run_id: int,
    x_run_token: Annotated[Optional[str], Header()] = None,
    db: AsyncSession = Depends(get_db),
) -> SalesSignalRun:
    """Własne poświadczenie trasy: token biegu, zablokowany wiersz biegu.

    Zły token kończy się 401 przed limitem ``@limiter.limit`` (zależność biegnie
    przed treścią trasy), ale nie zakłada blokady: token ma 256 bitów, więc
    zgadywanie to tylko obciążenie, a nie obejście.
    """

    # Najpierw tani odczyt bez blokady: zły token nie trzyma blokady wiersza biegu,
    # który czeka na prawdziwy raport. Blokada i ponowne sprawdzenie dopiero dla
    # pasującego tokenu, żeby dwa równoległe raporty nie przeszły oba.
    now = datetime.now(timezone.utc)
    run = await db.get(SalesSignalRun, run_id)
    if run is not None and signals.token_matches(run, x_run_token, now):
        run = await db.get(
            SalesSignalRun, run_id, with_for_update=True, populate_existing=True
        )
        if run is not None and signals.token_matches(run, x_run_token, now):
            return run
    raise HTTPException(
        status.HTTP_401_UNAUTHORIZED, detail=signals.INVALID_TOKEN_DETAIL
    )


@router.post("/runs/{run_id}")
@limiter.limit("30/minute")
async def receive_report(
    request: Request,
    report: signals.RunReport,
    run: SalesSignalRun = Depends(require_signal_run_token),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    summary = await signals.ingest(db, run, report, now=datetime.now(timezone.utc))
    await db.commit()
    return {
        "status": "received",
        "leads": summary["leads"],
        "leads_new": summary["leads_new"],
        "briefings": summary["briefings"],
        "dropped": {
            "outside_window": len(summary["dropped"]["outside_window"]),
            "nexus_clients": len(summary["dropped"]["nexus_clients"]),
            "unknown_company": summary["dropped"]["unknown_company"],
            "duplicates": summary["dropped"]["duplicates"],
        },
    }
