"""Finanse w API integracyjnym v1 (``finance:read`` / ``finance:write``).

* „Zmiany w zamówieniach” (Zmiany · Wejścia · Zejścia · Kończące się ·
  Braki) — ten sam audyt miesiąca co ekran (``build_order_changes``), z polem
  „Zrobione” i odhaczaniem pozycji kluczem (autor = konto serwisowe).
* „Zamówienia PDF” — lista, plik i ZIP. Pobranie kluczem NIE zmienia statusu
  „Nowy / Pobrane przez Ciebie” ludzi (``order_pdf_downloads`` jest per osoba).
* Wyniki miesięczne z arkusza Finansów i ich import (``replace`` jak na
  ekranie; ``dry_run`` = odczyt arkusza i sprawdzenie konfliktu okresu, bez
  zapisu pliku — plik trafia na dysk PRZED wierszem w bazie).

Moduł NIE MOŻE mieć ``from __future__ import annotations`` (slowapi #579).
"""

import asyncio
import hashlib
from datetime import date
from typing import Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import finance as finance_routes
from app.api.integrations_v1.common import (
    FinanceRead,
    FinanceWrite,
    IdPath,
    IntegrationRoute,
    idempotent_write,
    integration_actor,
    principal_of,
    principal_rate_key,
    read_rate_limit,
    write_rate_limit,
)
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.models.service_account import ServiceScope
from app.schemas.finance import (
    FinanceImportResult,
    FinancePeriod,
    FinanceResultsResponse,
)
from app.schemas.finance_order_changes import (
    OrderChangesResponse,
    OrderChangesSummaryResponse,
    OrderHistoryResponse,
)
from app.schemas.finance_order_pdfs import (
    OrderPdfClient,
    OrderPdfMonthsResponse,
    OrderPdfsResponse,
)
from app.services import finance_order_pdfs, order_change_checks
from app.services.finance_import import (
    FinanceHeaderError,
    FinanceWorkbookError,
    parse_finance_workbook,
)
from app.services.finance_order_changes import apply_filters, build_order_changes
from app.core.http_headers import content_disposition_attachment

router = APIRouter(route_class=IntegrationRoute)


# ── Zmiany w zamówieniach ────────────────────────────────────────────────────


@router.get(
    "/finance/order-changes",
    response_model=OrderChangesResponse,
    summary="Zmiany w zamówieniach za miesiąc",
)
@limiter.limit(read_rate_limit, key_func=principal_rate_key)
async def order_changes(
    request: Request,
    caller: FinanceRead,
    db: AsyncSession = Depends(get_db),
    year: Optional[int] = Query(None, ge=2000, le=2100),
    month: Optional[int] = Query(None, ge=1, le=12),
    q: Optional[str] = Query(None, max_length=200),
    client_id: Optional[int] = Query(None, ge=1, le=2_147_483_647),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
):
    """Audyt miesiąca (domyślnie bieżący, czas Europe/Warsaw) z „Zrobione”.

    Pozycja ma ``item_key`` — tym kluczem odhacza się ją w
    ``POST /finance/order-changes/checks``.
    """
    year, month = finance_routes._order_changes_period(year, month)
    filters = finance_routes._order_changes_filters(q, client_id, date_from, date_to)
    full = await build_order_changes(db, year, month)
    can_check = ServiceScope.finance_write.value in principal_of(caller).scopes
    decorated = await order_change_checks.decorate(db, full, can_check=can_check)
    return apply_filters(decorated, filters)


@router.get(
    "/finance/order-changes/summary",
    response_model=OrderChangesSummaryResponse,
    summary="Liczniki „Do zrobienia” bieżącego miesiąca",
)
@limiter.limit(read_rate_limit, key_func=principal_rate_key)
async def order_changes_summary(
    request: Request,
    _caller: FinanceRead,
    db: AsyncSession = Depends(get_db),
):
    return await finance_routes.get_order_changes_summary(_user=None, db=db)


@router.get(
    "/finance/order-changes/history",
    response_model=OrderHistoryResponse,
    summary="Historia zamówienia: zmiany i odhaczenia",
)
@limiter.limit(read_rate_limit, key_func=principal_rate_key)
async def order_changes_history(
    request: Request,
    _caller: FinanceRead,
    db: AsyncSession = Depends(get_db),
    order_id: Optional[int] = Query(None, ge=1, le=2_147_483_647),
    order_group_id: Optional[int] = Query(None, ge=1, le=2_147_483_647),
):
    return await finance_routes.get_order_change_history(
        _user=None, order_id=order_id, order_group_id=order_group_id, db=db
    )


class CheckIn(BaseModel):
    year: int = Field(..., ge=2000, le=2100)
    month: int = Field(..., ge=1, le=12)
    item_key: str = Field(..., min_length=1, max_length=255)
    done: bool = True


class CheckOut(BaseModel):
    item_key: str
    done: bool


@router.post(
    "/finance/order-changes/checks",
    response_model=CheckOut,
    summary="Odhacz pozycję jako „Zrobione” (albo cofnij)",
)
@limiter.limit(write_rate_limit, key_func=principal_rate_key)
async def set_check(
    request: Request,
    body: CheckIn,
    caller: FinanceWrite,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Pozycja musi istnieć w audycie miesiąca — inaczej 409 (widok nieaktualny)."""

    async def run():
        response = await build_order_changes(db, body.year, body.month)
        found = order_change_checks.find_item(response, body.item_key)
        if found is None:
            raise HTTPException(
                409,
                detail={
                    "error": "item_not_in_month",
                    "message": "Tej pozycji nie ma już w wybranym miesiącu — "
                    "zamówienie zmieniło się w międzyczasie. Pobierz audyt ponownie.",
                },
            )
        tab, item = found
        done = await order_change_checks.set_check(
            db,
            year=body.year,
            month=body.month,
            tab=tab,
            item=item,
            done=body.done,
            user=integration_actor(caller),
        )
        return 200, CheckOut(item_key=body.item_key, done=done)

    return await idempotent_write(
        request, db, caller, payload=body.model_dump(), run=run
    )


# ── Zamówienia PDF ───────────────────────────────────────────────────────────


@router.get(
    "/finance/order-pdfs/months",
    response_model=OrderPdfMonthsResponse,
    summary="Miesiące z PDF-ami zamówień",
)
@limiter.limit(read_rate_limit, key_func=principal_rate_key)
async def order_pdf_months(
    request: Request,
    _caller: FinanceRead,
    db: AsyncSession = Depends(get_db),
):
    return await finance_routes.get_order_pdf_months(_user=None, db=db)


@router.get(
    "/finance/order-pdfs",
    response_model=OrderPdfsResponse,
    summary="PDF-y zamówień startujących w miesiącu",
)
@limiter.limit(read_rate_limit, key_func=principal_rate_key)
async def order_pdfs(
    request: Request,
    _caller: FinanceRead,
    db: AsyncSession = Depends(get_db),
    year: Optional[int] = Query(None, ge=2000, le=2100),
    month: Optional[int] = Query(None, ge=1, le=12),
):
    """Klienci i pliki; ``pending_change`` = zamówienie ma „Do zrobienia” w Zmianach."""
    year, month = finance_routes._order_changes_period(year, month)
    entries = await finance_order_pdfs.collect_entries(
        db, window=finance_order_pdfs.month_bounds(year, month)
    )
    todo_orders, todo_groups = await finance_routes._pending_change_orders(
        db, year, month
    )

    def pending(entry) -> bool:
        if entry.kind == "order":
            return entry.id in todo_orders
        if entry.kind == "group":
            return entry.id in todo_groups
        return False

    return OrderPdfsResponse(
        year=year,
        month=month,
        clients=[
            OrderPdfClient(
                client_id=bucket["client_id"],
                client_name=bucket["client_name"],
                files=[
                    finance_routes._order_pdf_file(
                        entry, downloaded_at=None, pending_change=pending(entry)
                    )
                    for entry in bucket["files"]
                ],
            )
            for bucket in finance_order_pdfs.group_by_client(entries)
        ],
    )


@router.get("/finance/order-pdfs/zip", summary="ZIP z PDF-ami zamówień miesiąca")
@limiter.limit(read_rate_limit, key_func=principal_rate_key)
async def order_pdfs_zip(
    request: Request,
    _caller: FinanceRead,
    db: AsyncSession = Depends(get_db),
    year: int = Query(..., ge=2000, le=2100),
    month: int = Query(..., ge=1, le=12),
    client_id: Optional[int] = Query(None, ge=1, le=2_147_483_647),
    files: Optional[str] = Query(
        None, max_length=20000, description="np. order:1,group:2"
    ),
):
    """Jak „Pobierz ZIP” w Finansach; brakujący plik trafia do ``BRAKUJACE_PLIKI.txt``."""
    entries = await finance_order_pdfs.collect_entries(
        db, window=finance_order_pdfs.month_bounds(year, month)
    )
    if client_id is not None:
        entries = [e for e in entries if e.client_id == client_id]
    if files is not None:
        wanted = set(finance_routes._parse_file_refs(files))
        entries = [e for e in entries if (e.kind, e.id) in wanted]
    if not entries:
        raise HTTPException(404, detail="Brak plików do spakowania.")
    if len(entries) > finance_routes.MAX_ZIP_FILES:
        raise HTTPException(
            422,
            detail=f"Za dużo plików w jednym archiwum (limit {finance_routes.MAX_ZIP_FILES}).",
        )
    members = [(entry, finance_routes._entry_path(entry)) for entry in entries]
    zip_path = await asyncio.to_thread(
        finance_order_pdfs.build_zip_file, members, client_folders=client_id is None
    )
    filename = (
        finance_order_pdfs.client_zip_name(entries[0].client_name, year, month)
        if client_id is not None
        else finance_order_pdfs.month_zip_name(year, month)
    )
    return FileResponse(
        zip_path,
        media_type="application/zip",
        headers={
            "Content-Disposition": content_disposition_attachment(
                filename, fallback="zamowienia.zip"
            )
        },
        background=BackgroundTask(finance_order_pdfs.remove_file_quietly, zip_path),
    )


@router.get(
    "/finance/order-pdfs/{kind}/{entry_id}/file",
    summary="PDF zamówienia (nazwa z nazwiskiem i okresem)",
)
@limiter.limit(read_rate_limit, key_func=principal_rate_key)
async def order_pdf_file(
    request: Request,
    kind: finance_order_pdfs.PdfKind,
    entry_id: IdPath,
    _caller: FinanceRead,
    db: AsyncSession = Depends(get_db),
):
    entry = await finance_order_pdfs.find_entry(db, kind, entry_id)
    if entry is None:
        raise HTTPException(404, detail="Nie znaleziono pliku zamówienia.")
    abs_path = finance_routes._entry_path(entry)
    if abs_path is None:
        raise HTTPException(404, detail="Plik nie jest już dostępny na dysku.")
    return FileResponse(
        path=abs_path,
        media_type=entry.content_type or "application/pdf",
        headers={
            "Content-Disposition": content_disposition_attachment(
                entry.download_name, fallback="zamowienie.pdf"
            )
        },
    )


# ── Wyniki miesięczne ────────────────────────────────────────────────────────


@router.get(
    "/finance/periods",
    response_model=list[FinancePeriod],
    summary="Miesiące z aktualnym importem wyników",
)
@limiter.limit(read_rate_limit, key_func=principal_rate_key)
async def finance_periods(
    request: Request,
    _caller: FinanceRead,
    db: AsyncSession = Depends(get_db),
):
    return await finance_routes.list_periods(_user=None, db=db)


@router.get(
    "/finance/results",
    response_model=FinanceResultsResponse,
    summary="Wyniki miesiąca (koszt, przychód, marża)",
)
@limiter.limit(read_rate_limit, key_func=principal_rate_key)
async def finance_results(
    request: Request,
    _caller: FinanceRead,
    db: AsyncSession = Depends(get_db),
    year: int = Query(..., ge=2000, le=2100),
    month: int = Query(..., ge=1, le=12),
):
    return await finance_routes.get_results(
        _user=None,
        year=year,
        month=month,
        q=None,
        sort="row_number",
        direction="asc",
        db=db,
    )


class FinanceImportDryRun(BaseModel):
    dry_run: bool = True
    year: int
    month: int
    rows: int
    needs_completion: int
    rejected: int
    would_replace_run_id: Optional[int]


@router.post(
    "/finance/imports",
    response_model=FinanceImportResult,
    status_code=201,
    summary="Import arkusza wyników miesiąca (XLSX)",
)
@limiter.limit(write_rate_limit, key_func=principal_rate_key)
async def finance_import(
    request: Request,
    caller: FinanceWrite,
    db: AsyncSession = Depends(get_db),
    file: UploadFile = File(...),
    year: int = Form(..., ge=2000, le=2100),
    month: int = Form(..., ge=1, le=12),
    replace: bool = Form(False),
    dry_run: bool = Query(
        False, description="Odczyt arkusza i konflikt okresu, bez zapisu."
    ),
) -> Response:
    """Jak „Wgraj arkusz” w Finansach: istniejący miesiąc bez ``replace`` = 409."""
    payload = await file.read(finance_routes.MAX_UPLOAD_BYTES + 1)
    await file.seek(0)

    if dry_run:
        if len(payload) > finance_routes.MAX_UPLOAD_BYTES:
            raise HTTPException(413, detail="Plik przekracza 15 MB.")
        try:
            parsed = await run_in_threadpool(parse_finance_workbook, payload)
        except FinanceHeaderError as exc:
            raise HTTPException(
                422,
                detail={
                    "error": "header_mismatch",
                    "message": "Nagłówki arkusza nie zgadzają się z wzorem Finansów.",
                    "missing": exc.missing,
                    "unexpected": exc.unexpected,
                },
            ) from exc
        except FinanceWorkbookError as exc:
            raise HTTPException(
                422, detail="Nie udało się odczytać pliku jako arkusza .xlsx."
            ) from exc
        existing = await finance_routes._current_run(db, year, month)
        if existing is not None and not replace:
            raise HTTPException(
                409,
                detail={
                    "error": "period_has_import",
                    "message": "Miesiąc ma już aktualny import — wyślij z replace=true.",
                    "run_id": existing.id,
                    "row_count": existing.row_count,
                },
            )
        return JSONResponse(
            FinanceImportDryRun(
                year=year,
                month=month,
                rows=len(parsed.rows),
                needs_completion=parsed.needs_completion,
                rejected=len(parsed.critical_errors),
                would_replace_run_id=existing.id if existing is not None else None,
            ).model_dump()
        )

    async def run():
        # Trasa ekranu czyta z „osoby” wyłącznie `.id` (autor = None, ślad
        # konta przez `details.via` na `Activity`). Sama commituje.
        result = await finance_routes.import_workbook(
            user=integration_actor(caller),
            db=db,
            file=file,
            year=year,
            month=month,
            replace=replace,
        )
        return 201, result

    return await idempotent_write(
        request,
        db,
        caller,
        payload={
            "year": year,
            "month": month,
            "replace": replace,
            "file_sha256": hashlib.sha256(payload).hexdigest(),
        },
        run=run,
    )
