"""Zlecenie i raport bota Sprzedaży (Grok Bot) dla jednego biegu.

``GET /api/integrations/sales-signals/runs/{run_id}`` (``request_url`` z webhooka
v2) zwraca pełne zlecenie: ``task``, ``report_format``, ``request``, ``firms``,
``callback_url`` i parametry, bez zużywania tokenu. ``POST`` na ten sam adres
przyjmuje raport. Obie metody wymagają nagłówka ``X-Run-Token``.
Poświadczeniem jest jednorazowy token biegu z webhooka startowego: działa tylko
dla tego biegu, przy jednym raporcie i najwyżej 2 godziny. Brak biegu, zły, zużyty
i wygasły token dają tę samą odpowiedź 401, żeby nie dało się zgadywać numerów biegów.

Treść raportu sprawdza model rodzaju biegu z rejestru zadań bota
(``services/sales/bot_tasks``): pusta treść i niezgodna z modelem to 422 (token
zostaje ważny), za duża 413, bieg rodzaju spoza rejestru 409 (bieg zostaje
zamknięty jako ``failed``).

Bez ``from __future__ import annotations``: moduł ma ``@limiter.limit``, a z nim
ciało żądania lądowałoby jako parametr query (422).
"""

import json
import logging
from datetime import datetime, timezone
from typing import Annotated, Any, Optional, get_args

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ValidationError
from pydantic_core import ErrorType
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rate_limit import limiter
from app.core.tasks import spawn
from app.models.sales import SalesSignalRun
from app.services.sales import bot_tasks, signals
from app.services.sales import registry_cards
from app.services.sales.bot_tasks import people

logger = logging.getLogger(__name__)

router = APIRouter()

#: Największy realny raport: 50 sygnałów (do ok. 3,6 KB) albo punkty dla 25 firm
#: (do ok. 5,6 KB na firmę), poniżej 200 KB; więcej to obciążenie, nie raport.
MAX_REPORT_BYTES = 512 * 1024
TOO_LARGE_DETAIL = "Raport przekracza limit 512 KB."
#: Boty czasem wysyłają pierwszy POST bez treści (24.11.2026).
EMPTY_REPORT_DETAIL = (
    "Pusta treść raportu. Wyślij raport jako JSON w treści tego samego POST "
    "(Content-Type: application/json, nagłówek X-Run-Token). Token biegu jest "
    "nadal ważny."
)
UNKNOWN_KIND_DETAIL = "Ten rodzaj biegu nie jest obsługiwany."
INVALID_PEOPLE_REPORT_DETAIL = "Raport osób nie jest zgodny z formatem zlecenia."
COGNISM_REPORT_FIELDS = (
    people.CognismReport.model_fields.keys()
    | people.CognismFirm.model_fields.keys()
    | people.CognismPerson.model_fields.keys()
)
COGNISM_VALIDATION_CODES = frozenset(get_args(ErrorType))


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
    """JSON raportu sprawdzony modelem rodzaju; błąd w kształcie zwykłego 422.

    Pusta treść (także same białe znaki) to osobne 422 z poleceniem, co wysłać.
    """

    if not raw.strip():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, detail=EMPTY_REPORT_DETAIL
        )
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


def _cognism_report_detail(exc: RequestValidationError) -> str:
    """Wskaż miejsce błędu bez odsyłania wartości i nazw obcych pól."""

    issues: list[str] = []
    for error in exc.errors():
        code = error["type"]
        parts = () if code == "json_invalid" else error["loc"][1:]
        path = "body"
        if code == "extra_forbidden":
            # Klucz spoza schematu również może zawierać dane kontaktowe.
            parts = parts[:-1]
        for part in parts:
            if isinstance(part, int):
                path += f"[{part}]"
            else:
                field = part if part in COGNISM_REPORT_FIELDS else "<field>"
                path += f".{field}"
        if code == "extra_forbidden":
            path += ".<extra>"
        issue = f"{path}: {code if code in COGNISM_VALIDATION_CODES else 'invalid'}"
        if issue not in issues:
            issues.append(issue)
        if len(issues) == 5:
            break
    details = ", ".join(issues)
    return f"{INVALID_PEOPLE_REPORT_DETAIL} {details}"


@router.get("/runs/{run_id}")
@limiter.limit("30/minute")
async def get_run_request(
    request: Request,
    response: Response,
    run: SalesSignalRun = Depends(require_signal_run_token),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Pełne zlecenie biegu dla bota (webhook v2); token zostaje ważny do raportu."""

    if bot_tasks.for_run(run) is None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=UNKNOWN_KIND_DETAIL)
    response.headers["Cache-Control"] = "no-store"
    body = await signals.request_body(db, run)
    logger.info(
        "sales_bot run=%s kind=%s request fetched firms=%d",
        run.id,
        run.kind,
        len(body["firms"]),
    )
    return body


@router.post("/runs/{run_id}")
@limiter.limit("30/minute")
async def receive_report(
    request: Request,
    run: SalesSignalRun = Depends(require_signal_run_token),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    task = bot_tasks.for_run(run)
    if task is None:
        # Bieg rodzaju, którego rejestr już nie zna: zamknięty, token zużyty.
        run.status, run.token_hash, run.error = "failed", None, "nieznany rodzaj"
        await db.commit()
        logger.warning(
            "sales_bot run=%s kind=%s refused: unknown kind", run.id, run.kind
        )
        raise HTTPException(status.HTTP_409_CONFLICT, detail=UNKNOWN_KIND_DETAIL)
    raw = await read_limited(request)
    if not raw.strip():
        logger.warning("sales_bot run=%s kind=%s empty report body", run.id, run.kind)
    try:
        report = parse_report(raw, task.report_model)
    except RequestValidationError as exc:
        if task is people.COGNISM:
            detail = _cognism_report_detail(exc)
            logger.warning(
                "sales_bot run=%s source=cognism report rejected: %s", run.id, detail
            )
            raise HTTPException(422, detail=detail) from None
        if run.kind == "people":
            # Szczegóły walidacji mogą zawierać nazwiska i dane kontaktowe.
            raise HTTPException(422, detail=INVALID_PEOPLE_REPORT_DETAIL) from None
        raise
    summary = await bot_tasks.ingest(
        db, task, run, report, now=datetime.now(timezone.utc)
    )
    await db.commit()
    if run.kind == "enrich" and registry_cards.enabled():
        # NIP wpisany przez bota idzie od razu do rejestrów (tylko karty bez
        # sprawdzenia z tym numerem, ``registry_cards.due_company_ids``).
        spawn(
            registry_cards.check_after_save([int(cid) for cid in run.company_ids]),
            "sales_registry_after_enrich",
        )
    if run.kind == "briefing" and summary.get("potential"):
        # Research do oceny potencjału zapisany: ocenę pisze model w tle.
        from app.services.sales import potential  # noqa: PLC0415

        spawn(potential.assess_run(run.id), "sales_potential_assess")
    return {"status": "received", **task.reply(summary)}
