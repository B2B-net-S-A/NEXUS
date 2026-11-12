"""Przyjęcie raportu bota researchu (Grok Bot) dla jednego biegu.

``POST /api/integrations/sales-signals/runs/{run_id}`` z nagłówkiem ``X-Run-Token``.
Poświadczeniem jest jednorazowy token biegu z webhooka startowego: działa tylko
dla tego biegu, tylko raz i najwyżej 2 godziny. Brak biegu, zły, zużyty i wygasły
token dają tę samą odpowiedź 401, żeby nie dało się zgadywać numerów biegów.

Treść raportu sprawdza model rodzaju biegu z rejestru zadań bota
(``services/sales/bot_tasks``): za duża treść to 413, niezgodna z modelem 422,
bieg rodzaju spoza rejestru 409 (bieg zostaje zamknięty jako ``failed``).

Bez ``from __future__ import annotations``: moduł ma ``@limiter.limit``, a z nim
ciało żądania lądowałoby jako parametr query (422).
"""

import json
import logging
from datetime import datetime, timezone
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rate_limit import limiter
from app.models.sales import SalesSignalRun
from app.services.sales import bot_tasks, signals

logger = logging.getLogger(__name__)

router = APIRouter()

#: Największy realny raport: 50 sygnałów (do ok. 3,6 KB) albo punkty dla 25 firm
#: (do ok. 5,6 KB na firmę), poniżej 200 KB; więcej to obciążenie, nie raport.
MAX_REPORT_BYTES = 512 * 1024
TOO_LARGE_DETAIL = "Raport przekracza limit 512 KB."
UNKNOWN_KIND_DETAIL = "Ten rodzaj biegu nie jest obsługiwany."


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


async def read_limited(request: Request, limit: int = MAX_REPORT_BYTES) -> bytes:
    """Treść żądania najwyżej ``limit`` bajtów; więcej to 413 bez czytania reszty."""

    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        raise HTTPException(413, TOO_LARGE_DETAIL)
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise HTTPException(413, TOO_LARGE_DETAIL)
        chunks.append(chunk)
    return b"".join(chunks)


def parse_report(raw: bytes, model: type[BaseModel]) -> BaseModel:
    """JSON raportu sprawdzony modelem rodzaju; błąd w kształcie zwykłego 422."""

    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise RequestValidationError(
            [
                {
                    "type": "json_invalid",
                    "loc": ("body", 0),
                    "msg": "JSON decode error",
                    "input": {},
                    "ctx": {"error": type(exc).__name__},
                }
            ]
        ) from None
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise RequestValidationError(
            [
                {**error, "loc": ("body", *error["loc"])}
                for error in exc.errors(include_url=False)
            ]
        ) from None


@router.post("/runs/{run_id}")
@limiter.limit("30/minute")
async def receive_report(
    request: Request,
    run: SalesSignalRun = Depends(require_signal_run_token),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    task = bot_tasks.get(run.kind)
    if task is None:
        # Bieg rodzaju, którego rejestr już nie zna: zamknięty, token zużyty.
        run.status, run.token_hash, run.error = "failed", None, "nieznany rodzaj"
        await db.commit()
        logger.warning(
            "sales_bot run=%s kind=%s refused: unknown kind", run.id, run.kind
        )
        raise HTTPException(status.HTTP_409_CONFLICT, detail=UNKNOWN_KIND_DETAIL)
    report = parse_report(await read_limited(request), task.report_model)
    summary = await bot_tasks.ingest(
        db, task, run, report, now=datetime.now(timezone.utc)
    )
    await db.commit()
    return {"status": "received", **task.reply(summary)}
