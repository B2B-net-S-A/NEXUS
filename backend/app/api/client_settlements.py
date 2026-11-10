"""Finanse → Rozliczenia (roadmapa ``docs/rozliczenia-klientow-roadmapa.md``, E1.3).

Moduł Finanse (``FinanceModuleUser``) i sekcja Finanse; wyłączony moduł
``client_settlements`` = 404 (admin widzi zawsze). Kwoty i marża idą tylko do
kont z dostępem finansowym (``has_financial_access``), reszta dostaje ``null``.
Faktury kontraktorów z KSeF (E4): zatwierdzenie albo odrzucenie podpowiedzi NIP-u.
"""

from decimal import Decimal
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import FinanceModuleUser
from app.api.financial_access import has_financial_access
from app.api.section_access import FINANCE_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.core.http_headers import content_disposition
from app.core.scheduling import business_today, local_now
from app.models.user import User
from app.models.consultant_portal import CpDocument
from app.services.client_settlements import client_invoice, contractor_invoices, service
from app.services.consultant_portal import documents as portal_documents
from app.services.client_settlements import settings as module_settings
from app.services.client_settlements.service import SettlementError

router = APIRouter(dependencies=FINANCE_SECTION_DEPENDENCIES)

MONTH_PATTERN = r"^[0-9]{4}-(0[1-9]|1[0-2])$"
#: ``estimate`` — plan miesiąca przed jego końcem (E5.3).
KIND_PATTERN = r"^(actual|estimate)$"


class MdIn(BaseModel):
    md_regular: Decimal = Field(ge=0, le=31)
    md_extra: Optional[Decimal] = Field(default=None, ge=0, le=31)


class NeedsFixIn(BaseModel):
    reason: str = Field(min_length=5, max_length=1000)


class BatchIn(BaseModel):
    client_id: int
    month: str = Field(pattern=MONTH_PATTERN)
    kind: str = Field(default="actual", pattern=KIND_PATTERN)


class RuleIn(BaseModel):
    key: str = Field(max_length=64)
    level: str = Field(max_length=8)
    params: dict[str, str] = Field(default_factory=dict)


class RulesIn(BaseModel):
    effective_from: str = Field(pattern=MONTH_PATTERN)
    rules: list[RuleIn] = Field(max_length=200)


async def _open(db: AsyncSession, user: User) -> None:
    enabled = await module_settings.is_enabled(db)
    if not module_settings.open_for(user, enabled):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, module_settings.MODULE_DISABLED_DETAIL
        )


def _fail(exc: SettlementError) -> HTTPException:
    return HTTPException(exc.status, exc.message)


async def _commit(db: AsyncSession) -> None:
    await db.commit()


@router.get("/module")
async def module_state(
    current_user: FinanceModuleUser, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Czy pokazać zakładkę „Rozliczenia” (moduł włączony albo admin)."""

    enabled = await module_settings.is_enabled(db)
    return {"enabled": enabled, "open": module_settings.open_for(current_user, enabled)}


@router.get("/clients")
async def clients(
    current_user: FinanceModuleUser, db: AsyncSession = Depends(get_db)
) -> list[dict[str, Any]]:
    await _open(db, current_user)
    today = business_today()
    previous = f"{today.year - (today.month == 1)}-{(today.month - 2) % 12 + 1:02d}"
    return await service.clients_overview(db, previous)


@router.get("")
async def month(
    current_user: FinanceModuleUser,
    client_id: int = Query(..., ge=1),
    month: str = Query(..., pattern=MONTH_PATTERN),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _open(db, current_user)
    try:
        return await service.month_view(
            db, client_id, month, amounts=has_financial_access(current_user)
        )
    except SettlementError as exc:
        raise _fail(exc) from exc


@router.get("/contract/{contract_id}")
async def contract_detail(
    contract_id: int,
    current_user: FinanceModuleUser,
    month: str = Query(..., pattern=MONTH_PATTERN),
    kind: str = Query("actual", pattern=KIND_PATTERN),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _open(db, current_user)
    try:
        return await service.detail(
            db,
            contract_id,
            month,
            amounts=has_financial_access(current_user),
            kind=kind,
        )
    except SettlementError as exc:
        raise _fail(exc) from exc


@router.put("/contract/{contract_id}/md")
async def set_md(
    contract_id: int,
    body: MdIn,
    current_user: FinanceModuleUser,
    month: str = Query(..., pattern=MONTH_PATTERN),
    kind: str = Query("actual", pattern=KIND_PATTERN),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _open(db, current_user)
    try:
        await service.set_md(
            db,
            contract_id,
            month,
            md_regular=body.md_regular,
            md_extra=body.md_extra,
            actor=current_user,
            kind=kind,
        )
        await _commit(db)
        return await service.detail(
            db,
            contract_id,
            month,
            amounts=has_financial_access(current_user),
            kind=kind,
        )
    except SettlementError as exc:
        await db.rollback()
        raise _fail(exc) from exc


@router.post("/contract/{contract_id}/accept")
async def accept(
    contract_id: int,
    current_user: FinanceModuleUser,
    month: str = Query(..., pattern=MONTH_PATTERN),
    kind: str = Query("actual", pattern=KIND_PATTERN),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _open(db, current_user)
    try:
        await service.accept(
            db, contract_id, month, actor=current_user, now=local_now(), kind=kind
        )
        await _commit(db)
        return await service.detail(
            db,
            contract_id,
            month,
            amounts=has_financial_access(current_user),
            kind=kind,
        )
    except SettlementError as exc:
        # Przeliczony stan (np. „Brak MD”) zostaje zapisany, odmowa dotyczy przyjęcia.
        await _commit(db)
        raise _fail(exc) from exc


@router.post("/contract/{contract_id}/needs-fix")
async def needs_fix(
    contract_id: int,
    body: NeedsFixIn,
    current_user: FinanceModuleUser,
    month: str = Query(..., pattern=MONTH_PATTERN),
    kind: str = Query("actual", pattern=KIND_PATTERN),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _open(db, current_user)
    try:
        await service.needs_fix(
            db,
            contract_id,
            month,
            reason=body.reason,
            actor=current_user,
            now=local_now(),
            kind=kind,
        )
        await _commit(db)
        return await service.detail(
            db,
            contract_id,
            month,
            amounts=has_financial_access(current_user),
            kind=kind,
        )
    except SettlementError as exc:
        await db.rollback()
        raise _fail(exc) from exc


@router.post("/accept-batch")
async def accept_batch(
    body: BatchIn, current_user: FinanceModuleUser, db: AsyncSession = Depends(get_db)
) -> dict[str, int]:
    await _open(db, current_user)
    accepted = await service.accept_batch(
        db,
        body.client_id,
        body.month,
        actor=current_user,
        now=local_now(),
        kind=body.kind,
    )
    await _commit(db)
    return {"accepted": accepted}


@router.get("/rules/{client_id}")
async def rules(
    client_id: int,
    current_user: FinanceModuleUser,
    month: str = Query(..., pattern=MONTH_PATTERN),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _open(db, current_user)
    try:
        return await service.rules_screen(db, client_id, month)
    except SettlementError as exc:
        raise _fail(exc) from exc


@router.put("/rules/{client_id}")
async def save_rules(
    client_id: int,
    body: RulesIn,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _open(db, current_user)
    try:
        await service.save_rules(
            db,
            client_id,
            effective_from=body.effective_from,
            items=[r.model_dump() for r in body.rules],
            actor=current_user,
        )
        await _commit(db)
        return await service.rules_screen(db, client_id, body.effective_from)
    except SettlementError as exc:
        await db.rollback()
        raise _fail(exc) from exc


@router.post("/rules/{client_id}/copy-from/{source_client_id}")
async def copy_rules(
    client_id: int,
    source_client_id: int,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _open(db, current_user)
    current = service.today_month(business_today())
    try:
        await service.copy_rules(
            db, client_id, source_client_id, month=current, actor=current_user
        )
        await _commit(db)
        return await service.rules_screen(db, client_id, current)
    except SettlementError as exc:
        await db.rollback()
        raise _fail(exc) from exc


async def _nip_decision(
    db: AsyncSession, invoice_id: int, user: User, *, approve: bool
) -> dict[str, Any]:
    decide = (
        contractor_invoices.approve_nip if approve else contractor_invoices.reject_nip
    )
    try:
        invoice = await decide(db, invoice_id, user, local_now())
    except contractor_invoices.ContractorInvoiceError as exc:
        await db.rollback()
        raise HTTPException(exc.status, exc.message) from exc
    contract_id, month = invoice.contract_id, invoice.period_month
    await _commit(db)
    if contract_id is None or month is None:
        return {"invoice_id": invoice_id}
    return await service.detail(
        db, contract_id, month, amounts=has_financial_access(user)
    )


@router.post("/contractor-invoices/{invoice_id}/approve-nip")
async def approve_nip(
    invoice_id: int, current_user: FinanceModuleUser, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await _open(db, current_user)
    return await _nip_decision(db, invoice_id, current_user, approve=True)


@router.post("/contractor-invoices/{invoice_id}/reject-nip")
async def reject_nip(
    invoice_id: int, current_user: FinanceModuleUser, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await _open(db, current_user)
    return await _nip_decision(db, invoice_id, current_user, approve=False)


# ── Faktura do klienta i estymacja (E5) ──────────────────────────────────────


@router.get("/client-invoice")
async def client_invoice_month(
    current_user: FinanceModuleUser,
    client_id: int = Query(..., ge=1),
    month: str = Query(..., pattern=MONTH_PATTERN),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _open(db, current_user)
    try:
        return await client_invoice.invoice_month(
            db, client_id, month, amounts=has_financial_access(current_user)
        )
    except SettlementError as exc:
        raise _fail(exc) from exc


@router.get("/client-invoice/attachments")
async def client_invoice_attachments(
    current_user: FinanceModuleUser,
    client_id: int = Query(..., ge=1),
    month: str = Query(..., pattern=MONTH_PATTERN),
    contract_id: Optional[int] = Query(None, ge=1),
    issued_only: bool = Query(False),
    db: AsyncSession = Depends(get_db),
) -> Response:
    await _open(db, current_user)
    try:
        content, count = await client_invoice.attachments_zip(
            db, client_id, month, contract_id=contract_id, issued_only=issued_only
        )
    except SettlementError as exc:
        raise _fail(exc) from exc
    if count == 0:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "W tym miesiącu nie ma plików przyjętych RCP."
        )
    return Response(
        content,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="rcp-{client_id}-{month}.zip"'
        },
    )


@router.get("/contract/{contract_id}/documents/{document_id}")
async def contract_document(
    contract_id: int,
    document_id: int,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    """Plik RCP albo maila z karty osoby — do sprawdzenia przed przyjęciem
    zbiorczym (pytanie rozliczeń 10.11). Jak w portalu: zawsze jako załącznik."""

    await _open(db, current_user)
    document = await db.get(CpDocument, document_id)
    if document is None or document.contract_id != contract_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie ma takiego pliku.")
    try:
        path = portal_documents.path_for(document.file_path)
    except FileNotFoundError:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Plik nie jest dostępny na dysku."
        ) from None
    name = document.file_name or f"dokument-{document.id}"
    return FileResponse(
        path,
        media_type=document.mime,
        headers={"Content-Disposition": content_disposition(name, "attachment")},
    )


@router.get("/estimates")
async def estimates(
    current_user: FinanceModuleUser,
    client_id: int = Query(..., ge=1),
    month: str = Query(..., pattern=MONTH_PATTERN),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _open(db, current_user)
    try:
        return await client_invoice.estimates(
            db, client_id, month, amounts=has_financial_access(current_user)
        )
    except SettlementError as exc:
        raise _fail(exc) from exc
