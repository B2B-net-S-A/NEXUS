"""Wystawianie faktur sprzedaży z NEXUSA do KSeF (E4) — ekran Finansów.

Prefiks ``/api/finance/issued-invoices``, sekcja Finanse i uprawnienie
„Moduł Finanse” (``FinanceModuleUser``) na każdej trasie. Moduł faktur do
klientów wyłączony (``app_settings['client_invoicing']``) = 404 z powodem;
admin widzi ekrany zawsze (jak „Faktury do klientów”).

* ``GET/PUT /settings`` — dane sprzedawcy, rachunki, serie, stawki;
  ``PUT /series/{code}`` — „następny numer” serii w miesiącu,
* ``GET /to-issue`` — „Wystaw za miesiąc”; ``POST /drafts`` — szkice z zaznaczonych,
* ``GET ""`` — lista (``view=drafts|sent``), ``GET/PUT/DELETE /{id}`` — karta,
* ``POST /{id}/send`` — wysyłka do KSeF (``KSEF_SALES_ISSUE_MODE``),
  ``POST /{id}/check`` — „Sprawdź status”,
* ``POST /{id}/correction``, ``POST /advance`` — korekta i zaliczkowa,
* ``GET /{id}/pdf``, ``/upo``, ``/xml`` — pliki.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy import update as sql_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import FinanceModuleUser
from app.api.section_access import FINANCE_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.core.scheduling import business_today
from app.models.client_issued_invoice import ClientIssuedInvoice
from app.models.user import User
from app.services.client_invoicing import (
    clients,
    invoice_pdf,
    issue,
    issue_settings,
    ksef_send,
    numbering,
)
from app.services.client_invoicing import settings as module_settings
from app.services.client_invoice_issue_schema import SERIES
from app.services.hr.ksef.client import KsefApiError

logger = logging.getLogger(__name__)
router = APIRouter(dependencies=FINANCE_SECTION_DEPENDENCIES)

VIEW_STATUSES = {
    "drafts": ("draft", "rejected", "failed"),
    "sent": ("sending", "sent", "accepted", "cancelled"),
}


@contextmanager
def _http_errors() -> Iterator[None]:
    try:
        yield
    except (issue.IssueError, numbering.NumberingError) as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    except issue_settings.IssueSettingsError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


async def _module_open(db: AsyncSession, user: User) -> None:
    enabled = await module_settings.is_enabled(db)
    if not module_settings.open_for(user, enabled):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, module_settings.MODULE_DISABLED_DETAIL
        )


def _period(year: Optional[int], month: Optional[int]) -> tuple[int, int]:
    """Miesiąc z zapytania; domyślnie poprzedni (faktury wystawia się po miesiącu)."""

    if (year is None) != (month is None):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Podaj rok i miesiąc razem."
        )
    if year is not None and month is not None:
        return year, month
    today = business_today()
    return (today.year - 1, 12) if today.month == 1 else (today.year, today.month - 1)


async def _invoice(
    db: AsyncSession, invoice_id: int, *, lock: bool = False
) -> ClientIssuedInvoice:
    query = select(ClientIssuedInvoice).where(ClientIssuedInvoice.id == invoice_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    invoice = await db.scalar(query)
    if invoice is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie ma takiej faktury.")
    return invoice


async def _card(db: AsyncSession, invoice: ClientIssuedInvoice) -> dict[str, Any]:
    names = await clients.names(db, [invoice.client_id])
    return await issue.payload(
        db,
        invoice,
        settings=await issue_settings.load(db),
        config=ksef_send.load_config(),
        client_name=names.get(invoice.client_id),
    )


def _file(content: bytes, filename: str, media_type: str) -> Response:
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _client_factory() -> ksef_send.ClientFactory:
    # Odczyt w chwili wywołania — testy podstawiają fałszywy serwer KSeF.
    return ksef_send.default_client


# ── Ustawienia ──────────────────────────────────────────────────────────────


class SettingsIn(BaseModel):
    seller: dict[str, Any] = Field(default_factory=dict)
    accounts: dict[str, Any] = Field(default_factory=dict)
    payment_days: int = Field(14, ge=0, le=180)
    default_vat: str = "23"
    exemption_basis: str = Field("", max_length=255)
    service_name: str = Field("", max_length=120)
    series: dict[str, str] = Field(default_factory=dict)
    clients: dict[str, Any] = Field(default_factory=dict)


class SeriesIn(BaseModel):
    year: int = Field(..., ge=2020, le=2100)
    month: int = Field(..., ge=1, le=12)
    next_number: int = Field(..., ge=1, le=999999)


@router.get("/settings")
async def get_settings(
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
    year: Optional[int] = Query(None, ge=2020, le=2100),
    month: Optional[int] = Query(None, ge=1, le=12),
) -> dict[str, Any]:
    await _module_open(db, current_user)
    today = business_today()
    period = (year, month) if year and month else (today.year, today.month)
    data = await issue_settings.load(db)
    override_ids = [int(key) for key in data["clients"]]
    return {
        "settings": data,
        "client_names": {
            str(key): value
            for key, value in (await clients.names(db, override_ids)).items()
        },
        "series": await numbering.series_view(
            db, year=period[0], month=period[1], patterns=data["series"]
        ),
        "series_period": f"{period[0]:04d}-{period[1]:02d}",
        "series_labels": issue_settings.SERIES_LABELS,
        "vat_rates": [
            {"code": rate.code, "label": rate.label}
            for rate in issue.VAT_RATES.values()
        ],
        "ksef": ksef_send.status_payload(ksef_send.load_config()),
        "missing": issue_settings.seller_missing(data),
    }


@router.put("/settings")
async def put_settings(
    body: SettingsIn,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _module_open(db, current_user)
    with _http_errors():
        saved = await issue_settings.save(
            db, body.model_dump(), actor_id=current_user.id
        )
    await db.commit()
    return {"settings": saved}


@router.put("/series/{code}")
async def put_series(
    code: str,
    body: SeriesIn,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _module_open(db, current_user)
    if code not in SERIES:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie ma takiej serii.")
    with _http_errors():
        await numbering.set_next(
            db,
            code=code,
            year=body.year,
            month=body.month,
            next_number=body.next_number,
            actor_id=current_user.id,
        )
    await db.commit()
    data = await issue_settings.load(db)
    return {
        "series": await numbering.series_view(
            db, year=body.year, month=body.month, patterns=data["series"]
        )
    }


# ── Wystaw za miesiąc, szkice ───────────────────────────────────────────────


class DraftsIn(BaseModel):
    year: int = Field(..., ge=2020, le=2100)
    month: int = Field(..., ge=1, le=12)
    keys: list[str] = Field(..., min_length=1, max_length=200)
    split: Literal["order", "person"] = "order"


class AdvanceIn(BaseModel):
    client_id: int = Field(..., gt=0)
    currency: Literal["PLN", "EUR", "USD"] = "PLN"
    received_on: date


class CorrectionIn(BaseModel):
    reason: str = Field(..., min_length=3, max_length=256)


class InvoiceIn(BaseModel):
    """Pola szkicu; brak pola = bez zmian."""

    issue_date: Optional[date] = None
    sale_date: Optional[date] = None
    period_from: Optional[date] = None
    period_to: Optional[date] = None
    due_date: Optional[date] = None
    client_order_number: Optional[str] = Field(None, max_length=256)
    notes: Optional[str] = Field(None, max_length=1000)
    correction_reason: Optional[str] = Field(None, max_length=256)
    currency: Optional[Literal["PLN", "EUR", "USD"]] = None
    series_code: Optional[Literal["PL", "UE"]] = None
    buyer: Optional[dict[str, Any]] = None
    lines: Optional[list[dict[str, Any]]] = Field(None, max_length=200)


@router.get("/to-issue")
async def to_issue(
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
    year: Optional[int] = Query(None, ge=2020, le=2100),
    month: Optional[int] = Query(None, ge=1, le=12),
) -> dict[str, Any]:
    await _module_open(db, current_user)
    period = _period(year, month)
    return await issue.to_issue(db, year=period[0], month=period[1])


@router.post("/drafts", status_code=status.HTTP_201_CREATED)
async def create_drafts(
    body: DraftsIn,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _module_open(db, current_user)
    with _http_errors():
        created = await issue.create_drafts(
            db,
            year=body.year,
            month=body.month,
            keys=body.keys,
            split=body.split,
            actor_id=current_user.id,
            today=business_today(),
        )
    await db.commit()
    return {"created": [invoice.id for invoice in created]}


@router.post("/advance", status_code=status.HTTP_201_CREATED)
async def create_advance(
    body: AdvanceIn,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _module_open(db, current_user)
    with _http_errors():
        invoice = await issue.create_advance(
            db,
            client_id=body.client_id,
            currency=body.currency,
            received_on=body.received_on,
            actor_id=current_user.id,
            today=business_today(),
        )
    await db.commit()
    return await _card(db, invoice)


@router.get("")
async def listing(
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
    view: Literal["drafts", "sent"] = Query("drafts"),
    year: Optional[int] = Query(None, ge=2020, le=2100),
    month: Optional[int] = Query(None, ge=1, le=12),
) -> dict[str, Any]:
    await _module_open(db, current_user)
    if (year is None) != (month is None):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Podaj rok i miesiąc razem."
        )
    config = ksef_send.load_config()
    return {
        "invoices": await issue.listing(
            db,
            statuses=VIEW_STATUSES[view],
            settings=await issue_settings.load(db),
            config=config,
            year=year,
            month=month,
        ),
        "ksef": ksef_send.status_payload(config),
    }


@router.get("/{invoice_id}")
async def card(
    invoice_id: int,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _module_open(db, current_user)
    return await _card(db, await _invoice(db, invoice_id))


@router.put("/{invoice_id}")
async def update(
    invoice_id: int,
    body: InvoiceIn,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _module_open(db, current_user)
    invoice = await _invoice(db, invoice_id, lock=True)
    with _http_errors():
        await issue.update(
            db,
            invoice,
            body.model_dump(exclude_unset=True, mode="python"),
            actor_id=current_user.id,
        )
    await db.commit()
    return await _card(db, invoice)


@router.delete("/{invoice_id}")
async def remove(
    invoice_id: int,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _module_open(db, current_user)
    invoice = await _invoice(db, invoice_id, lock=True)
    with _http_errors():
        outcome = await issue.delete(db, invoice, actor_id=current_user.id)
    await db.commit()
    return {"result": outcome}


@router.post("/{invoice_id}/correction", status_code=status.HTTP_201_CREATED)
async def correction(
    invoice_id: int,
    body: CorrectionIn,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _module_open(db, current_user)
    original = await _invoice(db, invoice_id)
    with _http_errors():
        invoice = await issue.create_correction(
            db,
            original,
            reason=body.reason,
            actor_id=current_user.id,
            today=business_today(),
        )
    await db.commit()
    return await _card(db, invoice)


@router.post("/{invoice_id}/send")
async def send(
    invoice_id: int,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _module_open(db, current_user)
    config = ksef_send.load_config()
    invoice = await _invoice(db, invoice_id, lock=True)
    with _http_errors():
        xml = await issue.prepare_send(
            db, invoice, config=config, actor_id=current_user.id
        )
    # Numer i XML zapisane przed rozmową z KSeF; blokada serii puszcza tutaj.
    await db.commit()

    async def remember(progress: ksef_send.TransmitResult) -> None:
        # Sesja (i numer pliku) w bazie, zanim pójdzie dalej: padnięcie procesu
        # w trakcie zostawia fakturę do „Sprawdź status”, nie martwą.
        await db.execute(
            sql_update(ClientIssuedInvoice)
            .where(ClientIssuedInvoice.id == invoice_id)
            .values(
                ksef_session_ref=progress.session_ref,
                ksef_invoice_ref=progress.invoice_ref,
            )
        )
        await db.commit()

    try:
        result = await ksef_send.transmit(
            config, xml, client_factory=_client_factory(), on_progress=remember
        )
    except Exception:  # noqa: BLE001 — stan faktury musi zostać rozstrzygnięty
        logger.exception("[client-invoicing] wysyłka faktury %s przerwana", invoice_id)
        await db.rollback()
        invoice = await _invoice(db, invoice_id)
        # Bez zapisanej sesji plik nie mógł dotrzeć (sesja zapisuje się przed
        # wysyłką pliku) — faktura wraca do ponownej wysyłki z tym samym numerem.
        result = ksef_send.TransmitResult(
            stage="send" if invoice.ksef_session_ref else "open",
            session_ref=invoice.ksef_session_ref,
            invoice_ref=invoice.ksef_invoice_ref,
            error=KsefApiError("internal"),
        )
    invoice = await _invoice(db, invoice_id, lock=True)
    await issue.apply_result(db, invoice, result, actor_id=current_user.id)
    await db.commit()
    return await _card(db, invoice)


@router.post("/{invoice_id}/check")
async def check(
    invoice_id: int,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _module_open(db, current_user)
    config = ksef_send.load_config()
    invoice = await _invoice(db, invoice_id)
    if invoice.status not in issue.CHECKABLE and not (
        invoice.status == "accepted" and not invoice.upo_xml
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, "Nie ma czego sprawdzać.")
    if not config.enabled:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            ksef_send.DISABLED_REASONS.get(config.disabled_reason or "", ""),
        )
    if not invoice.ksef_session_ref:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Wysyłka nie otworzyła sesji w KSeF, więc plik nie dotarł. Po "
            f"{int(issue.STALE_UNSENT_AFTER.total_seconds() // 60)} minutach od "
            "wysyłki fakturę można wysłać ponownie albo wycofać.",
        )
    result = await ksef_send.check(
        config,
        session_ref=invoice.ksef_session_ref,
        invoice_ref=invoice.ksef_invoice_ref,
        ksef_number=invoice.ksef_number,
        xml=invoice.xml.encode("utf-8") if invoice.xml else None,
        client_factory=_client_factory(),
    )
    invoice = await _invoice(db, invoice_id, lock=True)
    await issue.apply_result(db, invoice, result, actor_id=current_user.id)
    await db.commit()
    return await _card(db, invoice)


# ── Pliki ───────────────────────────────────────────────────────────────────


@router.get("/{invoice_id}/pdf")
async def pdf(
    invoice_id: int,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> Response:
    await _module_open(db, current_user)
    invoice = await _invoice(db, invoice_id)
    corrected = (
        await db.get(ClientIssuedInvoice, invoice.corrects_id)
        if invoice.corrects_id
        else None
    )
    html = invoice_pdf.render_html(
        invoice,
        await issue_settings.load(db),
        corrected_number=corrected.invoice_number if corrected else None,
    )
    content = await asyncio.to_thread(invoice_pdf.render_pdf, html)
    return _file(content, invoice_pdf.filename(invoice), "application/pdf")


@router.get("/{invoice_id}/upo")
async def upo(
    invoice_id: int,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> Response:
    await _module_open(db, current_user)
    invoice = await _invoice(db, invoice_id)
    if not invoice.upo_xml:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "UPO jeszcze nie ma.")
    stem = (invoice.invoice_number or str(invoice.id)).replace("/", "-")
    return _file(invoice.upo_xml.encode("utf-8"), f"upo-{stem}.xml", "application/xml")


@router.get("/{invoice_id}/xml")
async def xml(
    invoice_id: int,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> Response:
    await _module_open(db, current_user)
    invoice = await _invoice(db, invoice_id)
    if not invoice.xml:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "XML powstaje przy wysyłce do KSeF."
        )
    stem = (invoice.invoice_number or str(invoice.id)).replace("/", "-")
    return _file(invoice.xml.encode("utf-8"), f"fa3-{stem}.xml", "application/xml")
