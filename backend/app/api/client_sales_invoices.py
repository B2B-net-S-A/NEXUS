"""Faktury do klientów (E8 cz. 1): zakładka klienta i ekran Finansów.

Dwa routery, dwie sekcje:

* ``router`` — profil klienta (sekcja Delivery, zakres klientów Delivery
  Leada z adresu), prefiks ``/api/clients``:
  ``GET /{client_id}/invoicing`` (zakładka „Faktury”), ``…/export`` (CSV/XLSX
  pozycji „do faktury”) i ``GET /sales-invoices/overdue`` (zaległości
  w zakresie konta). Wymaga „Stawki i kwoty: podgląd”, a kwoty klienta
  rozstrzyga ``financial_access.can_read_client_finance`` — Delivery Lead
  widzi wyłącznie klientów ze swojego portfela; rekruter, TCM i rola
  „Automatyzacje” nie mają podglądu kwot, więc nie wchodzą.
* ``finance_router`` — moduł Finanse (uprawnienie „Moduł Finanse”), prefiks
  ``/api/finance/sales-invoices``: lista faktur z KSeF, „do faktury” wszystkich
  klientów z eksportem, zaległości, wpłaty do sprawdzenia, „Pobierz teraz”,
  wyciąg (uznania), przypisanie, pominięcie, uznanie różnicy, ręczne
  „opłacono” i przełącznik modułu (admin).

Moduł wyłączony (``app_settings['client_invoicing']``) = 404 z powodem;
admin widzi ekrany zawsze.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.delivery_client_scope import DELIVERY_CLIENT_SCOPE_DEPENDENCIES
from app.api.deps import AdminUser, FinanceModuleUser
from app.api.financial_access import can_read_client_finance, has_financial_access
from app.api.permission_access import AmountsViewUser
from app.api.section_access import (
    DELIVERY_SECTION_DEPENDENCIES,
    FINANCE_SECTION_DEPENDENCIES,
)
from app.core.database import get_db
from app.core.scheduling import business_today
from app.models.client import Client
from app.models.client_sales_invoice import ClientSalesInvoice
from app.models.user import User
from app.services.access_scope import (
    DL_CLIENT_OUT_OF_SCOPE_DETAIL,
    is_delivery_lead_governed,
    resolve_delivery_lead_finance_client_ids,
)
from app.services.action_permissions import ProductAction, has_permission
from app.services.client_invoicing import (
    clients,
    export,
    matching,
    payments,
    sync,
    views,
)
from app.services.client_invoicing import settings as module_settings
from app.services.client_invoicing.billing import money
from app.services.client_invoicing.ledger import ZERO, check, rows_by_period
from app.services.client_sales_invoices_schema import REASON_MAX_LENGTH
from app.services.hr.bank import statements
from app.services.hr.bank.parsed import StatementError
from app.services.order_client_identity import normalize_registry_id
from app.services.permission_denial import permission_denied

router = APIRouter(
    dependencies=[*DELIVERY_SECTION_DEPENDENCIES, *DELIVERY_CLIENT_SCOPE_DEPENDENCIES]
)
finance_router = APIRouter(dependencies=FINANCE_SECTION_DEPENDENCIES)

ExportFormat = Literal["csv", "xlsx"]
EARLIEST_PAYMENT = date(2020, 1, 1)


# ── Wspólne ──────────────────────────────────────────────────────────────────


@contextmanager
def _http_errors() -> Iterator[None]:
    try:
        yield
    except (matching.MatchingError, payments.PaymentError) as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    except sync.SalesSyncError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    except StatementError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


async def _module_open(db: AsyncSession, user: User) -> bool:
    enabled = await module_settings.is_enabled(db)
    if not module_settings.open_for(user, enabled):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, module_settings.MODULE_DISABLED_DETAIL
        )
    return enabled


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


async def _client_or_404(db: AsyncSession, client_id: int) -> Client:
    client = await db.get(Client, client_id)
    if client is None or client.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie ma takiego klienta.")
    return client


async def _assert_client_finance(db: AsyncSession, user: User, client_id: int) -> None:
    """Kwoty klienta: Finanse wszędzie, Delivery Lead tylko w swoim portfelu."""

    allowed = await resolve_delivery_lead_finance_client_ids(user, db)
    if can_read_client_finance(
        user, client_id=client_id, delivery_lead_finance_client_ids=allowed
    ):
        return
    if allowed is not None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, DL_CLIENT_OUT_OF_SCOPE_DETAIL)
    raise permission_denied(ProductAction.amounts_view)


async def _finance_scope(db: AsyncSession, user: User) -> Optional[set[int]]:
    """Klienci, których kwoty widzi konto (``None`` = wszyscy)."""

    if has_financial_access(user):
        return None
    allowed = await resolve_delivery_lead_finance_client_ids(user, db)
    if allowed is None:
        return None if not is_delivery_lead_governed(user) else set()
    return set(allowed)


def _file(content: bytes, filename: str, media_type: str) -> Response:
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


async def _export_response(
    db: AsyncSession, payload: dict[str, Any], *, fmt: ExportFormat, stem: str
) -> Response:
    ids = {row["client_id"] for row in payload["rows"]}
    nips: dict[int, str] = {}
    if ids:
        for client_id, raw in (
            await db.execute(select(Client.id, Client.nip).where(Client.id.in_(ids)))
        ).all():
            nips[int(client_id)] = normalize_registry_id(raw or "")
    lines = export.table(payload["rows"], period=payload["period"], nips=nips)
    filename = f"{stem}-{payload['period']}"
    if fmt == "xlsx":
        return _file(
            export.to_xlsx(lines),
            f"{filename}.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    return _file(export.to_csv(lines), f"{filename}.csv", "text/csv; charset=utf-8")


# ── Zakładka klienta (Delivery) ──────────────────────────────────────────────


@router.get("/sales-invoices/module")
async def module_state(
    current_user: AmountsViewUser, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Czy pokazać zakładkę „Faktury” (moduł włączony albo admin)."""

    enabled = await module_settings.is_enabled(db)
    return {
        "enabled": enabled,
        "open": module_settings.open_for(current_user, enabled),
    }


@router.get("/sales-invoices/overdue")
async def overdue_in_scope(
    current_user: AmountsViewUser, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Faktury po terminie u klientów, których kwoty widzi konto (DL — portfel)."""

    await _module_open(db, current_user)
    scope = await _finance_scope(db, current_user)
    members = await clients.family(db, scope) if scope is not None else None
    return {
        "invoices": await views.overdue(db, client_ids=members, today=business_today())
    }


@router.get("/{client_id}/invoicing")
async def client_invoicing(
    client_id: int,
    current_user: AmountsViewUser,
    db: AsyncSession = Depends(get_db),
    year: Optional[int] = Query(None, ge=2020, le=2100),
    month: Optional[int] = Query(None, ge=1, le=12),
) -> dict[str, Any]:
    enabled = await _module_open(db, current_user)
    await _client_or_404(db, client_id)
    await _assert_client_finance(db, current_user, client_id)
    period = _period(year, month)
    payload = await views.client_view(
        db, client_id=client_id, year=period[0], month=period[1], today=business_today()
    )
    payload["module_enabled"] = enabled
    payload["can_manage"] = has_permission(current_user, ProductAction.finance_module)
    return payload


@router.get("/{client_id}/invoicing/export")
async def client_invoicing_export(
    client_id: int,
    current_user: AmountsViewUser,
    db: AsyncSession = Depends(get_db),
    year: Optional[int] = Query(None, ge=2020, le=2100),
    month: Optional[int] = Query(None, ge=1, le=12),
    format: ExportFormat = Query("xlsx"),
) -> Response:
    await _module_open(db, current_user)
    await _client_or_404(db, client_id)
    await _assert_client_finance(db, current_user, client_id)
    period = _period(year, month)
    members = await clients.family(db, [client_id])
    payload = await views.month_view(
        db, year=period[0], month=period[1], client_ids=members, today=business_today()
    )
    return await _export_response(
        db, payload, fmt=format, stem=f"do-faktury-klient-{client_id}"
    )


# ── Finanse ──────────────────────────────────────────────────────────────────


class ModuleIn(BaseModel):
    enabled: bool


class TargetIn(BaseModel):
    group_id: Optional[int] = Field(None, gt=0)
    order_id: Optional[int] = Field(None, gt=0)

    @model_validator(mode="after")
    def _exactly_one(self) -> "TargetIn":
        if (self.group_id is None) == (self.order_id is None):
            raise ValueError("Wskaż zamówienie albo osobę z zamówienia.")
        return self


class AssignIn(BaseModel):
    targets: list[TargetIn] = Field(..., min_length=1, max_length=20)
    year: int = Field(..., ge=2020, le=2100)
    month: int = Field(..., ge=1, le=12)


class ReasonIn(BaseModel):
    reason: str = Field(..., min_length=1, max_length=REASON_MAX_LENGTH)


class MarkPaidIn(BaseModel):
    amount: Decimal = Field(..., gt=0, max_digits=14, decimal_places=2)
    paid_on: date
    reason: str = Field(..., min_length=1, max_length=REASON_MAX_LENGTH)


class CreditAssignIn(BaseModel):
    invoice_id: int = Field(..., gt=0)


async def _invoice_or_404(db: AsyncSession, invoice_id: int) -> ClientSalesInvoice:
    invoice = await db.scalar(
        select(ClientSalesInvoice)
        .where(ClientSalesInvoice.id == invoice_id)
        .with_for_update()
    )
    if invoice is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie ma takiej faktury.")
    return invoice


async def _detail(db: AsyncSession, invoice_id: int) -> dict[str, Any]:
    chain = await views.chain_for(db, invoice_id)
    if chain is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie ma takiej faktury.")
    return await views.invoice_detail(db, chain, today=business_today())


@finance_router.get("")
async def finance_invoices(
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
    year: Optional[int] = Query(None, ge=2020, le=2100),
    month: Optional[int] = Query(None, ge=1, le=12),
) -> dict[str, Any]:
    enabled = await _module_open(db, current_user)
    period = _period(year, month)
    payload = await views.month_view(
        db, year=period[0], month=period[1], client_ids=None, today=business_today()
    )
    return {
        "period": payload["period"],
        "module_enabled": enabled,
        "invoices": payload["invoices"],
        "summary": payload["summary"],
    }


@finance_router.get("/to-invoice")
async def finance_to_invoice(
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
    year: Optional[int] = Query(None, ge=2020, le=2100),
    month: Optional[int] = Query(None, ge=1, le=12),
) -> dict[str, Any]:
    await _module_open(db, current_user)
    period = _period(year, month)
    return {
        "period": f"{period[0]:04d}-{period[1]:02d}",
        "clients": await views.client_summary(
            db, year=period[0], month=period[1], today=business_today()
        ),
    }


@finance_router.get("/to-invoice/export")
async def finance_to_invoice_export(
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
    year: Optional[int] = Query(None, ge=2020, le=2100),
    month: Optional[int] = Query(None, ge=1, le=12),
    format: ExportFormat = Query("xlsx"),
) -> Response:
    await _module_open(db, current_user)
    period = _period(year, month)
    payload = await views.month_view(
        db, year=period[0], month=period[1], client_ids=None, today=business_today()
    )
    return await _export_response(db, payload, fmt=format, stem="do-faktury")


@finance_router.get("/overdue")
async def finance_overdue(
    current_user: FinanceModuleUser, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await _module_open(db, current_user)
    return {
        "invoices": await views.overdue(db, client_ids=None, today=business_today())
    }


@finance_router.get("/credits")
async def finance_credits(
    current_user: FinanceModuleUser, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await _module_open(db, current_user)
    return {"credits": await views.credits_view(db, today=business_today())}


@finance_router.get("/status")
async def finance_status(
    current_user: FinanceModuleUser, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await _module_open(db, current_user)
    return await sync.status(db)


@finance_router.post("/fetch")
async def finance_fetch(
    current_user: FinanceModuleUser, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    enabled = await _module_open(db, current_user)
    if not enabled:
        raise HTTPException(
            status.HTTP_409_CONFLICT, module_settings.MODULE_DISABLED_DETAIL
        )
    with _http_errors():
        return await sync.fetch_now(db, actor_id=current_user.id)


@finance_router.post("/statements")
async def finance_statement(
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
    file: UploadFile = File(..., description="Wyciąg MT940 albo CAMT.053"),
) -> dict[str, Any]:
    """Uznania z wyciągu → zapłaty faktur do klientów (obciążenia zostają Płacom)."""

    enabled = await _module_open(db, current_user)
    if not enabled:
        raise HTTPException(
            status.HTTP_409_CONFLICT, module_settings.MODULE_DISABLED_DETAIL
        )
    raw = await file.read(statements.MAX_STATEMENT_BYTES + 1)
    with _http_errors():
        parsed = statements.parse_file(raw)
    sha = hashlib.sha256(raw).hexdigest()
    # Ta sama blokada co import Płac: ten sam plik wgrany w obu miejscach naraz
    # czeka, a drugi przebieg widzi już zapisane uznania.
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
        {"key": f"hr-statement:{sha}"},
    )
    result = await payments.import_credits(
        db, parsed, sha=sha, actor_id=current_user.id
    )
    return {"format": parsed.format, "statement": sha[:12], **result.as_dict()}


@finance_router.put("/module")
async def finance_module(
    body: ModuleIn, current_user: AdminUser, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return await module_settings.set_enabled(db, body.enabled, actor=current_user)


@finance_router.post("/credits/{payment_id}/assign")
async def finance_credit_assign(
    payment_id: int,
    body: CreditAssignIn,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _module_open(db, current_user)
    with _http_errors():
        payment = await payments.assign_credit(
            db, payment_id, body.invoice_id, actor_id=current_user.id
        )
    return {
        "id": payment.id,
        "invoice_id": payment.invoice_id,
        "match_status": "matched",
    }


@finance_router.post("/credits/{payment_id}/ignore")
async def finance_credit_ignore(
    payment_id: int,
    body: ReasonIn,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _module_open(db, current_user)
    with _http_errors():
        payment = await payments.ignore_credit(
            db, payment_id, reason=body.reason, actor_id=current_user.id
        )
    return {"id": payment.id, "match_status": payment.match_status}


@finance_router.get("/{invoice_id}")
async def finance_invoice(
    invoice_id: int, current_user: FinanceModuleUser, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await _module_open(db, current_user)
    return await _detail(db, invoice_id)


@finance_router.get("/{invoice_id}/options")
async def finance_invoice_options(
    invoice_id: int,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
    client_id: Optional[int] = Query(None, gt=0),
    year: Optional[int] = Query(None, ge=2020, le=2100),
    month: Optional[int] = Query(None, ge=1, le=12),
) -> dict[str, Any]:
    """Zamówienia do „Przypisz”: klient faktury (albo wskazany) w miesiącu faktury."""

    await _module_open(db, current_user)
    invoice = await db.get(ClientSalesInvoice, invoice_id)
    if invoice is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie ma takiej faktury.")
    target_client = invoice.client_id or client_id
    if target_client is None:
        return {"client_id": None, "options": []}
    await _client_or_404(db, target_client)
    if year is None and month is None and invoice.period_year is not None:
        year, month = int(invoice.period_year), int(invoice.period_month)
    period = _period(year, month)
    return {
        "client_id": target_client,
        "period": f"{period[0]:04d}-{period[1]:02d}",
        "options": await views.assignment_options(
            db, client_id=target_client, year=period[0], month=period[1]
        ),
    }


@finance_router.post("/{invoice_id}/assign")
async def finance_invoice_assign(
    invoice_id: int,
    body: AssignIn,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _module_open(db, current_user)
    invoice = await _invoice_or_404(db, invoice_id)
    with _http_errors():
        await matching.assign(
            db,
            invoice,
            targets=[
                matching.Target(group_id=t.group_id, order_id=t.order_id)
                for t in body.targets
            ],
            period=(body.year, body.month),
            actor_id=current_user.id,
        )
    return await _detail(db, invoice_id)


@finance_router.post("/{invoice_id}/ignore")
async def finance_invoice_ignore(
    invoice_id: int,
    body: ReasonIn,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _module_open(db, current_user)
    invoice = await _invoice_or_404(db, invoice_id)
    with _http_errors():
        await matching.ignore(db, invoice, reason=body.reason, actor_id=current_user.id)
    return await _detail(db, invoice_id)


@finance_router.post("/{invoice_id}/reopen")
async def finance_invoice_reopen(
    invoice_id: int, current_user: FinanceModuleUser, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await _module_open(db, current_user)
    invoice = await _invoice_or_404(db, invoice_id)
    with _http_errors():
        await matching.reopen(db, invoice, actor_id=current_user.id)
    return await _detail(db, invoice_id)


@finance_router.post("/{invoice_id}/accept-difference")
async def finance_invoice_accept(
    invoice_id: int,
    body: ReasonIn,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """„Uznaj różnicę” — dotyczy tej kwoty; inna różnica wraca do sprawdzenia."""

    await _module_open(db, current_user)
    await _invoice_or_404(db, invoice_id)
    chain = await views.chain_for(db, invoice_id)
    if chain is None or chain.head.id != invoice_id:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Różnicę uznaje się na fakturze pierwotnej."
        )
    rows = await rows_by_period(db, [chain])
    result = check(chain, rows.get(chain.period or (0, 0), {}))
    if result.status not in ("difference", "accepted") or result.difference is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Ta faktura nie ma różnicy do uznania."
        )
    note = " ".join(body.reason.split())
    if len(note) < 3:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Podaj powód (co najmniej 3 znaki)."
        )
    head = chain.head
    head.difference_accepted_amount = money(result.difference)
    head.difference_reason = note
    head.difference_accepted_by = current_user.id
    head.difference_accepted_at = datetime.now(timezone.utc)
    await db.flush()
    return await _detail(db, invoice_id)


@finance_router.post("/{invoice_id}/mark-paid")
async def finance_invoice_mark_paid(
    invoice_id: int,
    body: MarkPaidIn,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _module_open(db, current_user)
    await _invoice_or_404(db, invoice_id)
    if body.paid_on < EARLIEST_PAYMENT or body.paid_on > business_today():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Data zapłaty nie może być w przyszłości.",
        )
    chain = await views.chain_for(db, invoice_id)
    if chain is not None and chain.to_pay <= ZERO:
        raise HTTPException(status.HTTP_409_CONFLICT, "Faktura jest już opłacona.")
    with _http_errors():
        await payments.mark_paid(
            db,
            invoice_id,
            amount=body.amount,
            paid_on=body.paid_on,
            reason=body.reason,
            actor_id=current_user.id,
        )
    return await _detail(db, invoice_id)


__all__ = ["finance_router", "router"]
