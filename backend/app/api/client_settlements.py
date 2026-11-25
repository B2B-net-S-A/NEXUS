"""Finanse → Rozliczenia (roadmapa ``docs/rozliczenia-klientow-roadmapa.md``, E1.3).

Moduł Finanse (``FinanceModuleUser``) i sekcja Finanse; wyłączony moduł
``client_settlements`` = 404 (admin widzi zawsze). Kwoty i marża idą tylko do
kont z dostępem finansowym (``has_financial_access``), reszta dostaje ``null``.
Faktury kontraktorów z KSeF (E4): zatwierdzenie albo odrzucenie podpowiedzi NIP-u.

``delivery_router`` (E5.1, decyzja Artura z 09.11.2026): Delivery Lead widzi
„Do faktury dla klienta” z marżą w zł i % u swoich klientów (kwoty według
``can_read_client_finance``) i rozstrzyga koszty integracji, które wpisały Finanse.
Stoi pod ``/api/my-clients`` za sekcją Delivery, bo DL nie ma modułu Finanse.

Dodatki do rozliczenia kontraktora (13.11.2026): wpis Finansów, zatwierdzenie,
odrzucenie z powodem, fakturowanie klientowi i pliki dodatku.
"""

from decimal import Decimal
from typing import Annotated, Any, Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminUser, FinanceModuleUser
from app.api.financial_access import can_read_client_finance, has_financial_access
from app.api.permission_access import DeliveryViewUser
from app.api.section_access import (
    DELIVERY_SECTION_DEPENDENCIES,
    FINANCE_SECTION_DEPENDENCIES,
)
from app.core.database import get_db
from app.core.http_headers import content_disposition
from app.core.scheduling import business_today, local_now
from app.models.user import User
from app.models.client_settlement import ClientSettlementExtra
from app.models.consultant_portal import CpDocument
from app.services.client_settlements import client_documents as many_documents
from app.services.access_scope import (
    assert_delivery_lead_client_visible,
    resolve_delivery_lead_client_ids,
    resolve_delivery_lead_finance_client_ids,
)
from app.services.client_settlements import (
    client_acceptance,
    client_invoice,
    contract_nip_review,
    contractor_invoices,
    integration_costs,
    service,
    service_confirmation,
    signoffs,
)
from app.services.client_settlements import extras as settlement_extras
from app.services.consultant_portal import documents as portal_documents
from app.services.consultant_portal import preview as panel_preview_service
from app.services.consultant_portal.auth import PortalError
from app.services.hr_documents_schema import MAX_FILE_BYTES
from app.services.client_settlements import settings as module_settings
from app.services.client_settlements import month_close, start_checklist, team_month
from app.services.hr import audit
from app.services.client_settlements.service import SettlementError

router = APIRouter(dependencies=FINANCE_SECTION_DEPENDENCIES)
delivery_router = APIRouter(dependencies=DELIVERY_SECTION_DEPENDENCIES)

MONTH_PATTERN = r"^[0-9]{4}-(0[1-9]|1[0-2])$"
#: ``estimate`` — plan miesiąca przed jego końcem (E5.3).
KIND_PATTERN = r"^(actual|estimate)$"


class ModuleIn(BaseModel):
    enabled: bool


class MdIn(BaseModel):
    md_regular: Decimal = Field(ge=0, le=31)
    md_extra: Optional[Decimal] = Field(default=None, ge=0, le=31)


class NeedsFixIn(BaseModel):
    reason: str = Field(min_length=5, max_length=1000)


class BatchIn(BaseModel):
    client_id: int
    month: str = Field(pattern=MONTH_PATTERN)
    kind: str = Field(default="actual", pattern=KIND_PATTERN)


class AcceptanceIn(BaseModel):
    client_id: int
    month: str = Field(pattern=MONTH_PATTERN)
    contract_ids: list[int] = Field(min_length=1, max_length=500)


class RuleIn(BaseModel):
    key: str = Field(max_length=64)
    level: str = Field(max_length=8)
    params: dict[str, str] = Field(default_factory=dict)


class IntegrationCostIn(BaseModel):
    amount: Decimal = Field(gt=0, le=100000, decimal_places=2)
    description: str = Field(min_length=3, max_length=300)


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


@router.put("/module")
async def set_module(
    body: ModuleIn, current_user: AdminUser, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Włącznik modułu (admin). Bez wysyłki do kogokolwiek: zmienia, kto w firmie
    widzi ekrany i czy NEXUS zapisuje faktury kontraktorów z KSeF."""

    value = await module_settings.set_enabled(db, body.enabled, actor=current_user)
    audit.record(
        db,
        actor_user_id=current_user.id,
        subject_user_id=None,
        entity_type="client_settlements",
        entity_id=0,
        action="module_switch_changed",
        details={"enabled": value["enabled"]},
    )
    await db.commit()
    return {**value, "open": module_settings.open_for(current_user, value["enabled"])}


@router.get("/start")
async def start_state(
    current_user: AdminUser, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Karta „Start rozliczeń” (admin): przełączniki i to, czego brakuje do startu."""

    return await start_checklist.load(db)


@router.get("/clients")
async def clients(
    current_user: FinanceModuleUser, db: AsyncSession = Depends(get_db)
) -> list[dict[str, Any]]:
    await _open(db, current_user)
    today = business_today()
    previous = f"{today.year - (today.month == 1)}-{(today.month - 2) % 12 + 1:02d}"
    return await service.clients_overview(db, previous)


@router.get("/overview")
async def month_overview(
    current_user: FinanceModuleUser,
    month: str = Query(..., pattern=MONTH_PATTERN),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """„Przebieg miesiąca”: wszyscy klienci i kolejka decyzji po powodzie."""

    await _open(db, current_user)
    return await month_close.overview(
        db, month, amounts=has_financial_access(current_user)
    )


@router.get("/team")
async def team_overview(
    current_user: FinanceModuleUser,
    month: str = Query(..., pattern=MONTH_PATTERN),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Biuro w „Przebiegu miesiąca”: ewidencja, faktura z KSeF i zapłata, bez kwot."""

    await _open(db, current_user)
    return await team_month.team_month(db, month)


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


@router.get("/contract/{contract_id}/panel-preview")
async def panel_preview(
    contract_id: int,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Panel oczami konsultanta, tylko do odczytu: działa przy zamkniętym panelu."""

    await _open(db, current_user)
    try:
        return await panel_preview_service.build(
            db, contract_id, today=business_today(), now=local_now()
        )
    except PortalError as exc:
        raise HTTPException(exc.status, exc.message) from exc


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


@router.get("/contract-nip-review")
async def contract_nip_review_list(
    current_user: FinanceModuleUser, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Umowy B2B, których ``partner_nip`` wskazuje inną firmę (audyt 25.11.2026)."""

    await _open(db, current_user)
    return await contract_nip_review.review(db, business_today())


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
            db,
            client_id,
            month,
            amounts=has_financial_access(current_user),
            today=business_today(),
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


# ── Dokument dla klienta na projekt (E6.2) ───────────────────────────────────


@router.get("/client-documents")
async def client_documents(
    current_user: FinanceModuleUser,
    client_id: int = Query(..., ge=1),
    month: str = Query(..., pattern=MONTH_PATTERN),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Dokumenty dla klienta z reguły ``cl.client_document``: potwierdzenia usług
    per projekt (E6.2), protokół odbioru na cały miesiąc (E6.1) albo arkusze
    zbiorcze per podpisujący (E6.2)."""

    await _open(db, current_user)
    amounts = has_financial_access(current_user)
    try:
        many = await many_documents.collect(db, client_id, month, amounts=amounts)
        if many is not None:
            return many
        return await service_confirmation.collect(db, client_id, month, amounts=amounts)
    except SettlementError as exc:
        raise _fail(exc) from exc


#: ``protocol`` i ``package`` — PKO (E6.1); ``sheet``, ``sheets`` i
#: ``invoice_sheet`` — arkusze Velo (E6.2); bez ``kind`` — PDF projektu (E6.2).
DOCUMENT_FILE_KINDS = r"^(protocol|package|sheet|sheets|invoice_sheet)$"
#: Dokumenty z kwotami (stawki, wartości) tylko dla kont z dostępem do kwot.
WITH_AMOUNTS = {"protocol", "package", "invoice_sheet"}


@router.get("/client-documents/file")
async def client_document_file(
    current_user: FinanceModuleUser,
    client_id: int = Query(..., ge=1),
    month: str = Query(..., pattern=MONTH_PATTERN),
    project: Optional[str] = Query(None, min_length=1, max_length=200),
    kind: Optional[str] = Query(None, pattern=DOCUMENT_FILE_KINDS),
    signer: Optional[str] = Query(None, min_length=1, max_length=255),
    db: AsyncSession = Depends(get_db),
) -> Response:
    await _open(db, current_user)
    if kind in WITH_AMOUNTS and not has_financial_access(current_user):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Ten dokument ma kwoty: potrzebny dostęp do kwot.",
        )
    try:
        if kind == "protocol":
            content, name = await many_documents.protocol_pdf(db, client_id, month)
        elif kind == "package":
            content, name = await many_documents.package_zip(db, client_id, month)
        elif kind == "sheet":
            if not signer:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY, "Wybierz podpisującego."
                )
            content, name = await many_documents.sheet_pdf(db, client_id, month, signer)
        elif kind == "sheets":
            content, name = await many_documents.sheets_zip(db, client_id, month)
        elif kind == "invoice_sheet":
            content, name = await many_documents.invoice_sheet_pdf(db, client_id, month)
        else:
            if not project:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY, "Wybierz projekt."
                )
            content, name = await service_confirmation.document(
                db, client_id, month, project
            )
    except SettlementError as exc:
        raise _fail(exc) from exc
    media = "application/zip" if name.endswith(".zip") else "application/pdf"
    return Response(
        content,
        media_type=media,
        headers={"Content-Disposition": content_disposition(name, "attachment")},
    )


# ── KEŚU klienta z Jirą (E6.3) ───────────────────────────────────────────────


@router.get("/contract/{contract_id}/kesu/package")
async def kesu_package(
    contract_id: int,
    current_user: FinanceModuleUser,
    month: str = Query(..., pattern=MONTH_PATTERN),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """PDF do podpisu spółki: KEŚU ze stawką MD i faktury kosztów w jednym pliku."""

    await _open(db, current_user)
    if not has_financial_access(current_user):
        # KEŚU ze stawką to kwoty: tylko konta z dostępem do kwot.
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Paczka KEŚU ma kwoty.")
    try:
        content, name = await service.kesu_package(db, contract_id, month)
    except SettlementError as exc:
        raise _fail(exc) from exc
    return Response(
        content,
        media_type="application/pdf",
        headers={"Content-Disposition": content_disposition(name, "attachment")},
    )


@router.post("/contract/{contract_id}/pay-on-mail")
async def pay_on_mail(
    contract_id: int,
    current_user: FinanceModuleUser,
    month: str = Query(..., pattern=MONTH_PATTERN),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Podpisujący KEŚU nieobecny: zapłata po mailowej akceptacji (``pay.mail_accept_fallback``)."""

    await _open(db, current_user)
    try:
        await service.pay_on_mail(
            db, contract_id, month, actor=current_user, now=local_now()
        )
        await _commit(db)
        return await service.detail(
            db, contract_id, month, amounts=has_financial_access(current_user)
        )
    except SettlementError as exc:
        await db.rollback()
        raise _fail(exc) from exc


@router.post("/client-documents/signed")
async def client_document_signed(
    current_user: FinanceModuleUser,
    month: Annotated[str, Form(pattern=MONTH_PATTERN)],
    file: Annotated[UploadFile, File()],
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Podpisany przez klienta protokół albo arkusz zbiorczy wgrany przez Finanse
    (gdy nie przyszedł na rozliczenia@). Rozpoznanie po treści, jak z maila."""

    await _open(db, current_user)
    data = await file.read(portal_documents.MAX_FILE_BYTES + 1)
    if len(data) > portal_documents.MAX_FILE_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "Plik ma ponad 20 MB.")
    year, mon = (int(x) for x in month.split("-"))
    now = local_now()
    try:
        stored = await portal_documents.store(
            db,
            contract_id=None,
            kind="report",
            year=year,
            month=mon,
            content=data,
            file_name=file.filename,
            channel="portal",
            now=now,
        )
    except PortalError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    document = stored.document
    # Zapis już rozpoznaje dokument (jak z maila); drugi raz tylko, gdy nie wyszło
    # (np. ten sam plik wgrany wcześniej, zanim osoby miały rozliczenia).
    if document.status == "received" and not await signoffs.apply(
        db, document, now=now
    ):
        await db.rollback()
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Nie rozpoznano podpisanego protokołu ani arkusza zbiorczego: potrzebny PDF "
            "z podpisem elektronicznym i osobami z tego miesiąca.",
        )
    await _commit(db)
    return {"document_id": document.id, "recognized": True}


# ── Akceptacja klienta po zbiorczej wysyłce KCP (E6.5, Bank Pocztowy) ─────────


@router.get("/client-acceptance")
async def client_acceptance_month(
    current_user: FinanceModuleUser,
    client_id: int = Query(..., ge=1),
    month: str = Query(..., pattern=MONTH_PATTERN),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Paczki KCP do klienta: kto wysłany, kto zaakceptowany, szkic maila."""

    await _open(db, current_user)
    try:
        return await client_acceptance.month_view(db, client_id, month)
    except SettlementError as exc:
        raise _fail(exc) from exc


@router.get("/client-acceptance/package")
async def client_acceptance_package(
    current_user: FinanceModuleUser,
    client_id: int = Query(..., ge=1),
    month: str = Query(..., pattern=MONTH_PATTERN),
    all_people: bool = Query(False),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Zip z KCP w PDF (nazwy „J. Kowalski.pdf”); domyślnie osoby do wysłania."""

    await _open(db, current_user)
    try:
        content, count = await client_acceptance.package(
            db, client_id, month, only_to_send=not all_people
        )
    except SettlementError as exc:
        raise _fail(exc) from exc
    if not count:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie ma KCP do wysłania.")
    return Response(
        content,
        media_type="application/zip",
        headers={
            "Content-Disposition": content_disposition(f"KCP_{month}.zip", "attachment")
        },
    )


@router.post("/client-acceptance/sent")
async def client_acceptance_sent(
    body: AcceptanceIn,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Finanse wysłały paczkę z Outlooka: osoby czekają na akceptację klienta."""

    await _open(db, current_user)
    try:
        count = await client_acceptance.mark_sent(
            db,
            body.client_id,
            body.month,
            body.contract_ids,
            actor=current_user,
            now=local_now(),
        )
    except SettlementError as exc:
        await db.rollback()
        raise _fail(exc) from exc
    await _commit(db)
    return {"sent": count}


@router.post("/client-acceptance/accept")
async def client_acceptance_accept(
    body: AcceptanceIn,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """„Klient zaakceptował”, gdy odpowiedzi banku NEXUS nie odczytał sam."""

    await _open(db, current_user)
    try:
        count = await client_acceptance.accept(
            db,
            body.client_id,
            body.month,
            body.contract_ids,
            actor=current_user,
            now=local_now(),
        )
    except SettlementError as exc:
        await db.rollback()
        raise _fail(exc) from exc
    await _commit(db)
    return {"accepted": count}


@router.post("/client-acceptance/reply")
async def client_acceptance_reply(
    current_user: FinanceModuleUser,
    month: Annotated[str, Form(pattern=MONTH_PATTERN)],
    file: Annotated[UploadFile, File()],
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Odpowiedź klienta (MSG albo EML) wgrana przez Finanse, gdy przyszła na
    skrzynkę koordynatora, a nie na rozliczenia@."""

    await _open(db, current_user)
    data = await file.read(portal_documents.MAX_FILE_BYTES + 1)
    if len(data) > portal_documents.MAX_FILE_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "Plik ma ponad 20 MB.")
    year, mon = (int(x) for x in month.split("-"))
    now = local_now()
    try:
        stored = await portal_documents.store(
            db,
            contract_id=None,
            kind="report",
            year=year,
            month=mon,
            content=data,
            file_name=file.filename,
            channel="portal",
            now=now,
        )
    except PortalError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    document = stored.document
    # Zapis już czyta odpowiedź (jak z rozliczenia@); drugi raz tylko, gdy nie wyszło
    # (np. ten sam plik wgrany, zanim osoby były wysłane do klienta).
    if document.status == "received" and not await client_acceptance.apply(
        db, document, now=now
    ):
        await db.rollback()
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Nie rozpoznano akceptacji: potrzebny mail z domeny klienta z odpowiedzią "
            "akceptującą i osoby wysłane do akceptacji. Zaznacz akceptację przyciskiem.",
        )
    await _commit(db)
    return {"document_id": document.id, "recognized": True}


@router.get("/contract/{contract_id}/kcp")
async def contract_kcp(
    contract_id: int,
    current_user: FinanceModuleUser,
    month: str = Query(..., pattern=MONTH_PATTERN),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """KCP osoby w PDF: od konsultanta albo złożona z eksportu Redmine."""

    await _open(db, current_user)
    try:
        content, name = await client_acceptance.card_pdf(db, contract_id, month)
    except SettlementError as exc:
        raise _fail(exc) from exc
    return Response(
        content,
        media_type="application/pdf",
        headers={"Content-Disposition": content_disposition(name, "attachment")},
    )


# ── Koszty integracji (E5.1) ─────────────────────────────────────────────────


@router.get("/contract/{contract_id}/integration-costs")
async def contract_integration_costs(
    contract_id: int,
    current_user: FinanceModuleUser,
    month: str = Query(..., pattern=MONTH_PATTERN),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _open(db, current_user)
    try:
        return await integration_costs.card(
            db, contract_id, month, amounts=has_financial_access(current_user)
        )
    except SettlementError as exc:
        raise _fail(exc) from exc


@router.post("/contract/{contract_id}/integration-costs")
async def add_integration_cost(
    contract_id: int,
    body: IntegrationCostIn,
    current_user: FinanceModuleUser,
    month: str = Query(..., pattern=MONTH_PATTERN),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Koszt integracji przy osobie i miesiącu; czeka na zgodę DL-a klienta."""

    await _open(db, current_user)
    try:
        await integration_costs.add(
            db,
            contract_id,
            month,
            amount=body.amount,
            description=body.description,
            actor=current_user,
        )
        await _commit(db)
        return await integration_costs.card(
            db, contract_id, month, amounts=has_financial_access(current_user)
        )
    except SettlementError as exc:
        await db.rollback()
        raise _fail(exc) from exc


@router.delete("/contract/{contract_id}/integration-costs/{cost_id}")
async def withdraw_integration_cost(
    contract_id: int,
    cost_id: int,
    current_user: FinanceModuleUser,
    month: str = Query(..., pattern=MONTH_PATTERN),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _open(db, current_user)
    try:
        await integration_costs.withdraw(db, cost_id, contract_id)
        await _commit(db)
        return await integration_costs.card(
            db, contract_id, month, amounts=has_financial_access(current_user)
        )
    except SettlementError as exc:
        await db.rollback()
        raise _fail(exc) from exc


# ── Delivery Lead: marża i koszty integracji swoich klientów (E5.1) ──────────


async def _delivery_client(db: AsyncSession, user: User, client_id: int) -> bool:
    """Moduł włączony, klient z portfela DL-a; zwraca, czy konto widzi kwoty."""

    await _open(db, user)
    assert_delivery_lead_client_visible(
        client_id, await resolve_delivery_lead_client_ids(user, db)
    )
    return can_read_client_finance(
        user,
        client_id=client_id,
        delivery_lead_finance_client_ids=(
            await resolve_delivery_lead_finance_client_ids(user, db)
        ),
    )


async def _delivery_view(
    db: AsyncSession, user: User, client_id: int, month: str, amounts: bool
) -> dict[str, Any]:
    invoice = await client_invoice.invoice_month(
        db, client_id, month, amounts=amounts, today=business_today()
    )
    return {
        **invoice,
        "integration": await integration_costs.client_month(
            db, client_id, month, amounts=amounts
        ),
        "can_decide": await integration_costs.is_client_delivery_lead(
            db, user, client_id
        ),
    }


@delivery_router.get("/{client_id}/settlements")
async def delivery_settlements(
    client_id: int,
    current_user: DeliveryViewUser,
    month: str = Query(..., pattern=MONTH_PATTERN),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Miesiąc klienta dla DL-a: pozycje, netto, koszt, koszty integracji i marża."""

    amounts = await _delivery_client(db, current_user, client_id)
    try:
        return await _delivery_view(db, current_user, client_id, month, amounts)
    except SettlementError as exc:
        raise _fail(exc) from exc


async def _delivery_decision(
    db: AsyncSession,
    user: User,
    client_id: int,
    cost_id: int,
    month: str,
    *,
    approve: bool,
) -> dict[str, Any]:
    amounts = await _delivery_client(db, user, client_id)
    try:
        await integration_costs.decide(
            db,
            cost_id,
            approve=approve,
            actor=user,
            now=local_now(),
            client_id=client_id,
        )
        await _commit(db)
        return await _delivery_view(db, user, client_id, month, amounts)
    except SettlementError as exc:
        await db.rollback()
        raise _fail(exc) from exc


@delivery_router.post("/{client_id}/settlements/integration-costs/{cost_id}/approve")
async def approve_integration_cost(
    client_id: int,
    cost_id: int,
    current_user: DeliveryViewUser,
    month: str = Query(..., pattern=MONTH_PATTERN),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await _delivery_decision(
        db, current_user, client_id, cost_id, month, approve=True
    )


@delivery_router.post("/{client_id}/settlements/integration-costs/{cost_id}/reject")
async def reject_integration_cost(
    client_id: int,
    cost_id: int,
    current_user: DeliveryViewUser,
    month: str = Query(..., pattern=MONTH_PATTERN),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await _delivery_decision(
        db, current_user, client_id, cost_id, month, approve=False
    )


# ── Dodatki do rozliczenia kontraktora (13.11.2026) ─────────────────────────


class ExtraIn(BaseModel):
    month: str = Field(pattern=MONTH_PATTERN)
    kind: str = Field(max_length=20)
    amount: Decimal = Field(gt=0, le=100000)
    description: Optional[str] = Field(default=None, max_length=300)
    bill_to_client: bool = False


class ExtraApproveIn(BaseModel):
    bill_to_client: Optional[bool] = None


class ExtraRejectIn(BaseModel):
    reason: str = Field(min_length=5, max_length=500)


class ExtraBillingIn(BaseModel):
    bill_to_client: bool


def _extra_fail(exc: settlement_extras.ExtraError) -> HTTPException:
    return HTTPException(exc.status, exc.message)


async def _extras_detail(
    db: AsyncSession, contract_id: int, month: str, user: User
) -> dict[str, Any]:
    return await service.detail(
        db, contract_id, month, amounts=has_financial_access(user)
    )


@router.post("/contract/{contract_id}/extras")
async def add_extra(
    contract_id: int,
    body: ExtraIn,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Dodatek wpisany przez Finanse na karcie osoby — od razu zatwierdzony."""

    await _open(db, current_user)
    try:
        await settlement_extras.create(
            db,
            contract_id,
            body.month,
            kind=body.kind,
            amount=body.amount,
            description=body.description,
            source=settlement_extras.SOURCE_FINANCE,
            actor_id=current_user.id,
            now=local_now(),
            bill_to_client=body.bill_to_client,
            approve=True,
        )
        await _commit(db)
    except settlement_extras.ExtraError as exc:
        await db.rollback()
        raise _extra_fail(exc) from exc
    return await _extras_detail(db, contract_id, body.month, current_user)


@router.post("/contract/{contract_id}/extras/{extra_id}/approve")
async def approve_extra(
    contract_id: int,
    extra_id: int,
    body: ExtraApproveIn,
    current_user: FinanceModuleUser,
    month: str = Query(..., pattern=MONTH_PATTERN),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _open(db, current_user)
    try:
        await settlement_extras.approve(
            db,
            extra_id,
            contract_id,
            actor_id=current_user.id,
            now=local_now(),
            bill_to_client=body.bill_to_client,
        )
        await _commit(db)
    except settlement_extras.ExtraError as exc:
        await db.rollback()
        raise _extra_fail(exc) from exc
    return await _extras_detail(db, contract_id, month, current_user)


@router.post("/contract/{contract_id}/extras/{extra_id}/reject")
async def reject_extra(
    contract_id: int,
    extra_id: int,
    body: ExtraRejectIn,
    current_user: FinanceModuleUser,
    month: str = Query(..., pattern=MONTH_PATTERN),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _open(db, current_user)
    try:
        await settlement_extras.reject(
            db,
            extra_id,
            contract_id,
            actor_id=current_user.id,
            now=local_now(),
            reason=body.reason,
        )
        await _commit(db)
    except settlement_extras.ExtraError as exc:
        await db.rollback()
        raise _extra_fail(exc) from exc
    return await _extras_detail(db, contract_id, month, current_user)


@router.post("/contract/{contract_id}/extras/{extra_id}/billing")
async def extra_billing(
    contract_id: int,
    extra_id: int,
    body: ExtraBillingIn,
    current_user: FinanceModuleUser,
    month: str = Query(..., pattern=MONTH_PATTERN),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Czy dodatek idzie na fakturę dla klienta (``cl.extra_costs_on_invoice``)."""

    await _open(db, current_user)
    try:
        await settlement_extras.set_billing(
            db, extra_id, contract_id, bill_to_client=body.bill_to_client
        )
        await _commit(db)
    except settlement_extras.ExtraError as exc:
        await db.rollback()
        raise _extra_fail(exc) from exc
    return await _extras_detail(db, contract_id, month, current_user)


@router.post("/contract/{contract_id}/extras/{extra_id}/documents")
async def extra_document_upload(
    contract_id: int,
    extra_id: int,
    current_user: FinanceModuleUser,
    file: Annotated[UploadFile, File()],
    month: str = Query(..., pattern=MONTH_PATTERN),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Plik dodatku od Finansów (np. paragon z maila konsultanta)."""

    await _open(db, current_user)
    data = await file.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE, "Dokument może mieć najwyżej 20 MB."
        )
    extra = await db.get(ClientSettlementExtra, extra_id)
    if extra is None or extra.contract_id != contract_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie ma takiego dodatku.")
    try:
        await settlement_extras.add_document(
            db,
            extra,
            content=data,
            file_name=file.filename,
            channel="staff",
            uploaded_by=current_user.id,
        )
        await _commit(db)
    except settlement_extras.ExtraError as exc:
        await db.rollback()
        raise _extra_fail(exc) from exc
    return await _extras_detail(db, contract_id, month, current_user)


@router.get("/contract/{contract_id}/extras/{extra_id}/documents/{document_id}")
async def extra_document(
    contract_id: int,
    extra_id: int,
    document_id: int,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    await _open(db, current_user)
    try:
        document, path = await settlement_extras.document_of(
            db, contract_id, extra_id, document_id
        )
    except settlement_extras.ExtraError as exc:
        raise _extra_fail(exc) from exc
    name = document.file_name or f"dokument-{document.id}"
    return FileResponse(
        path,
        media_type=document.mime,
        headers={"Content-Disposition": content_disposition(name, "attachment")},
    )
