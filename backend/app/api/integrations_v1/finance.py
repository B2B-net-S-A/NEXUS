"""Finanse w API integracyjnym v1 (``finance:read`` / ``finance:write``).

* „Zmiany w zamówieniach” (Zmiany · Wejścia · Zejścia · Kończące się ·
  Braki) — ten sam audyt miesiąca co ekran (``build_order_changes``), z polem
  „Zrobione” i odhaczaniem pozycji kluczem (autor = konto serwisowe).
* „Zamówienia PDF” — lista, plik i ZIP. Pobranie kluczem NIE zmienia statusu
  „Nowy / Pobrane przez Ciebie” ludzi (``order_pdf_downloads`` jest per osoba).
* Wyniki miesięczne z arkusza Finansów i ich import (``replace`` jak na
  ekranie; ``dry_run`` = odczyt arkusza i sprawdzenie konfliktu okresu, bez
  zapisu pliku — plik trafia na dysk PRZED wierszem w bazie).

Kwoty: ``finance:read`` to moduł rozliczeń, więc kwoty sprzedaży (stawka do
klienta, przychód, faktura) widzi z samego scope'u. Koszty — stawka
konsultanta, wynagrodzenie, marża — tylko z ``amounts:read`` (decyzja Artura
14.10.2026); bez niego są ``null`` i ``costs_redacted = true``. Patrz
„Koszty tylko z amounts:read” niżej.

Moduł NIE MOŻE mieć ``from __future__ import annotations`` (slowapi #579).
"""

import asyncio
import hashlib
import hmac
import re
from datetime import date, datetime
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
from app.api.deps import Caller
from app.api.integrations_v1.common import (
    AmountLevel,
    FinanceRead,
    FinanceWrite,
    IdPath,
    IntegrationRoute,
    amount_level,
    idempotent_write,
    integration_actor,
    principal_of,
    principal_rate_key,
    read_rate_limit,
    write_rate_limit,
)
from app.core.config import settings
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.models.service_account import ServiceScope
from app.schemas.finance import (
    FinanceImportResult,
    FinancePeriod,
    FinanceResultsResponse,
    FinanceTotals,
    MoneyPLN,
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


# ── Koszty tylko z amounts:read ──────────────────────────────────────────────
#
# Sprzedaż (stawka do klienta, przychód, faktura) widać z ``finance:read``.
# Koszt — stawka konsultanta, stawka kosztowa MD, wynagrodzenie — i marża
# dopiero z ``amounts:read``. Koszt siedzi też w dwóch napisach, które nie są
# polami kwot: w kluczu pozycji szkicu (``order_change_checks._order_state``)
# i w opisach historii i odhaczeń (``finance_order_changes._change_description``,
# ``order_change_checks._event_summary``). Oba są tu czyszczone; testy
# budują opisy prawdziwymi funkcjami, więc zmiana ich treści zapali test.


def _sees_costs(caller: Caller) -> bool:
    return amount_level(caller) is AmountLevel.all


# Aneks przedłużający umowę (``kind = "amendment"``) bywa aneksem z konsultantem
# — dokument może podawać jego stawkę. Bez ``amounts:read`` API go nie
# pokazuje i nie wydaje; zamówienia klientów (sprzedaż) zostają.
def _visible_pdf_entries(entries: list, caller: Caller) -> list:
    if _sees_costs(caller):
        return entries
    return [entry for entry in entries if entry.kind != "amendment"]


def _hidden_item_key(key: str) -> str:
    """Klucz pozycji bez kwot dla klucza bez ``amounts:read``.

    Klucz szkicu niesie stawki (``…:draft:<start>:<koszt>:<przychód>``) —
    w ich miejsce idzie skrót HMAC całego klucza. Skrót bez sekretu dałoby się
    odwrócić zgadywaniem stawki; z sekretem nie. Zmiana stawki szkicu zmienia
    skrót tak samo jak klucz, więc odhaczenie nieaktualnej pozycji dalej daje
    409. Klucze bez kwot zostają bez zmian (te same co na ekranie).
    """
    head, separator, _ = key.partition(":draft:")
    if not separator:
        return key
    pepper = f"integrations-v1:item-key:{settings.SECRET_KEY}".encode()
    digest = hmac.new(pepper, key.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{head}:draft:h{digest}"


_COST_RATE_CHANGE = "Zmiana stawki kosztowej"
#: „…; koszt 1 200,00 PLN/MD, przychód …” (``_new_order_value``) — do przecinka
#: przed przychodem albo do końca napisu (opis odhaczenia bywa ucięty).
_NEW_ORDER_COST = re.compile(r"(; koszt ).*?(?=, przychód |$)")


def _summary_without_costs(text: str) -> str:
    if text.startswith(_COST_RATE_CHANGE):
        return f"{_COST_RATE_CHANGE} (kwoty tylko z amounts:read)"
    return _NEW_ORDER_COST.sub(r"\1ukryty", text)


def _changes_without_costs(response: OrderChangesResponse) -> dict:
    """Pola listy do podmiany: bez stawek kosztowych, kluczy i opisów z kosztem."""

    def change(item):
        update = {"rate_cost": None, "item_key": _hidden_item_key(item.item_key)}
        if item.kind == "rate_cost":
            update.update(old_amount=None, new_amount=None)
        return item.model_copy(update=update)

    def entry(item):
        return item.model_copy(
            update={"rate_cost": None, "item_key": _hidden_item_key(item.item_key)}
        )

    def exit_(item):
        return item.model_copy(update={"rate_cost": None})

    return {
        "changes": [change(item) for item in response.changes],
        "entries": [entry(item) for item in response.entries],
        "exits": [exit_(item) for item in response.exits],
        "ending_orders": [exit_(item) for item in response.ending_orders],
        "superseded": [
            check.model_copy(
                update={
                    "item_key": _hidden_item_key(check.item_key),
                    "summary": _summary_without_costs(check.summary),
                }
            )
            for check in response.superseded
        ],
    }


def _find_item(response: OrderChangesResponse, key: str, *, costs: bool):
    """Jak ``order_change_checks.find_item``, z kluczem w tej postaci, w jakiej
    klucz go widzi. Bez ``amounts:read`` pełny klucz szkicu NIE jest
    przyjmowany — inaczej 200/409 zdradzałoby zgadniętą stawkę."""
    for tab, item in order_change_checks.iter_items(response):
        real = order_change_checks.item_key(tab, item)
        if key == (real if costs else _hidden_item_key(real)):
            return tab, item
    return None


class OrderChangesOut(OrderChangesResponse):
    """Audyt miesiąca. Bez ``amounts:read`` (``costs_redacted``): ``rate_cost``,
    kwoty zmiany stawki kosztowej i koszt w opisach są ukryte, a klucz pozycji
    szkicu ma skrót zamiast stawek."""

    costs_redacted: bool


class OrderHistoryOut(OrderHistoryResponse):
    """Historia zamówienia; bez ``amounts:read`` opisy nie podają kosztu."""

    costs_redacted: bool


class FinanceTotalsOut(FinanceTotals):
    """Kafle miesiąca; koszt, marża i ich pochodne bez ``amounts:read`` = ``null``."""

    cost: Optional[MoneyPLN]
    margin: Optional[MoneyPLN]
    cost_without_margin: Optional[MoneyPLN]


class FinanceResultsOut(FinanceResultsResponse):
    """Wyniki miesiąca. Bez ``amounts:read`` (``costs_redacted``) wiersze nie
    mają stawki kosztowej MD, wynagrodzenia i marży, a kafle — kosztu i marży."""

    totals: FinanceTotalsOut
    costs_redacted: bool


_RESULT_ROW_COSTS = (
    "cost_rate_md",
    "compensation",
    "margin_pln",
    "margin_pct",
    "margin_percent",
)
_RESULT_TOTAL_COSTS = ("cost", "margin", "avg_margin_pct", "cost_without_margin")


def _results_out(result: FinanceResultsResponse, *, costs: bool) -> FinanceResultsOut:
    rows = result.rows
    totals = result.totals.model_dump()
    if not costs:
        hidden = dict.fromkeys(_RESULT_ROW_COSTS)
        rows = [row.model_copy(update=hidden) for row in rows]
        totals.update(dict.fromkeys(_RESULT_TOTAL_COSTS))
    return FinanceResultsOut(
        year=result.year,
        month=result.month,
        run_id=result.run_id,
        rows=rows,
        totals=FinanceTotalsOut(**totals),
        needs_completion_count=result.needs_completion_count,
        costs_redacted=not costs,
    )


# ── Zmiany w zamówieniach ────────────────────────────────────────────────────


@router.get(
    "/finance/order-changes",
    response_model=OrderChangesOut,
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
    ``POST /finance/order-changes/checks``. Koszty (``rate_cost``, kwoty
    zmiany stawki kosztowej) tylko z ``amounts:read``.
    """
    year, month = finance_routes._order_changes_period(year, month)
    filters = finance_routes._order_changes_filters(q, client_id, date_from, date_to)
    full = await build_order_changes(db, year, month)
    can_check = ServiceScope.finance_write.value in principal_of(caller).scopes
    decorated = await order_change_checks.decorate(db, full, can_check=can_check)
    response = apply_filters(decorated, filters)
    costs = _sees_costs(caller)
    hidden = {} if costs else _changes_without_costs(response)
    return OrderChangesOut(**{**dict(response), **hidden}, costs_redacted=not costs)


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
    response_model=OrderHistoryOut,
    summary="Historia zamówienia: zmiany i odhaczenia",
)
@limiter.limit(read_rate_limit, key_func=principal_rate_key)
async def order_changes_history(
    request: Request,
    caller: FinanceRead,
    db: AsyncSession = Depends(get_db),
    order_id: Optional[int] = Query(None, ge=1, le=2_147_483_647),
    order_group_id: Optional[int] = Query(None, ge=1, le=2_147_483_647),
):
    """Opisy zmian stawki kosztowej podają kwoty tylko z ``amounts:read``."""
    history = await finance_routes.get_order_change_history(
        _user=None, order_id=order_id, order_group_id=order_group_id, db=db
    )
    costs = _sees_costs(caller)
    items = history.items
    if not costs:
        items = [
            entry.model_copy(update={"summary": _summary_without_costs(entry.summary)})
            for entry in items
        ]
    return OrderHistoryOut(items=items, costs_redacted=not costs)


class CheckIn(BaseModel):
    year: int = Field(..., ge=2000, le=2100)
    month: int = Field(..., ge=1, le=12)
    item_key: str = Field(..., min_length=1, max_length=255)
    done: bool = True


class CheckOut(BaseModel):
    """Stan pozycji po zapisie; autor i czas, gdy jest odhaczona."""

    item_key: str
    done: bool
    by_name: Optional[str] = None
    at: Optional[datetime] = None


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
    """Pozycja musi istnieć w audycie miesiąca — inaczej 409 (widok nieaktualny).
    ``item_key`` dokładnie taki, jaki podał odczyt tym kluczem API."""
    costs = _sees_costs(caller)

    async def run():
        response = await build_order_changes(db, body.year, body.month)
        found = _find_item(response, body.item_key, costs=costs)
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
        # `set_check` zwraca autora i czas odhaczenia (albo None po cofnięciu);
        # stan po zapisie to zawsze stan żądany — także gdy już taki był.
        check = await order_change_checks.set_check(
            db,
            year=body.year,
            month=body.month,
            tab=tab,
            item=item,
            done=body.done,
            user=integration_actor(caller),
        )
        return 200, CheckOut(
            item_key=body.item_key,
            done=body.done,
            by_name=check.by_name if check is not None else None,
            at=check.at if check is not None else None,
        )

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
    caller: FinanceRead,
    db: AsyncSession = Depends(get_db),
    year: Optional[int] = Query(None, ge=2000, le=2100),
    month: Optional[int] = Query(None, ge=1, le=12),
):
    """Klienci i pliki; ``pending_change`` = zamówienie ma „Do zrobienia” w Zmianach."""
    year, month = finance_routes._order_changes_period(year, month)
    entries = await finance_order_pdfs.collect_entries(
        db, window=finance_order_pdfs.month_bounds(year, month)
    )
    entries = _visible_pdf_entries(entries, caller)
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
    caller: FinanceRead,
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
    entries = _visible_pdf_entries(entries, caller)
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
    caller: FinanceRead,
    db: AsyncSession = Depends(get_db),
):
    if kind == "amendment" and not _sees_costs(caller):
        raise HTTPException(
            403,
            detail={
                "error": "insufficient_scope",
                "message": (
                    "Aneks do umowy może podawać stawkę konsultanta — "
                    "wymaga scope'u amounts:read."
                ),
                "required": ["amounts:read"],
                "missing": ["amounts:read"],
            },
        )
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
    response_model=FinanceResultsOut,
    summary="Wyniki miesiąca (koszt, przychód, marża)",
)
@limiter.limit(read_rate_limit, key_func=principal_rate_key)
async def finance_results(
    request: Request,
    caller: FinanceRead,
    db: AsyncSession = Depends(get_db),
    year: int = Query(..., ge=2000, le=2100),
    month: int = Query(..., ge=1, le=12),
):
    """Przychód i faktura z ``finance:read``; stawka kosztowa MD,
    wynagrodzenie i marża tylko z ``amounts:read``."""
    result = await finance_routes.get_results(
        _user=None,
        year=year,
        month=month,
        q=None,
        sort="row_number",
        direction="asc",
        db=db,
    )
    return _results_out(result, costs=_sees_costs(caller))


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
