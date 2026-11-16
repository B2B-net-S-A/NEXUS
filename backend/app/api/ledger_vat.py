"""Księgowość → VAT (K5a): rejestry sprzedaży i zakupu z dokumentów księgi.

Prefiks ``/api/accounting`` (jak księga K1, ``app/main.py``). Bramki: sekcja
Finanse (router), „Moduł Finanse” (``FinanceModuleUser``) i przełączniki
modułów ``ledger`` oraz ``vat`` (wyłączony = 404, admin widzi zawsze).
Faktury osób zespołu (D2) widzi tylko osoba z Płacami. Konta modułu zmienia
tylko administrator (403).

* ``GET /vat?year=&month=`` — rejestry miesiąca, sumy grup (pola JPK_V7M),
  lista „do sprawdzenia”,
* ``PUT /vat/settings`` — konto VAT naliczonego,
* ``GET /vat/jpk?year=&month=`` — wersje JPK_V7M miesiąca (kwoty tylko z Płacami),
* ``POST /vat/jpk`` — nowa wersja pliku (lista „Księgowi” z Płacami albo
  administrator; walidacja XSD MF),
* ``GET /vat/jpk/{id}/file`` — plik XML (Płace albo administrator, D2),
* ``POST /vat/jpk/{id}/sent`` — oznaczenie „wysłany” z numerem UPO,
* ``PUT /vat/jpk/settings`` — e-mail i telefon w JPK (administrator),
* ``GET /vat/foreign?year=&month=`` — zakupy zagraniczne miesiąca (import usług,
  K5b-2) i dane formularza (dostawcy, waluty, konto dostawców),
* ``POST /vat/foreign`` — faktura dostawcy zagranicznego jako FVZ w buforze
  (nowy dostawca trafia do kartoteki),
* ``GET /vat/markers`` — kontrahenci ze znacznikami GTU/TP,
* ``PUT /vat/markers/{counterparty_id}`` — znaczniki kontrahenta (lista
  „Księgowi” albo administrator),
* ``GET /vat/settlement?year=&month=`` — rozliczenie VAT miesiąca (K5b-3c):
  JPK, obroty kont VAT, pozycje dokumentu (kwoty tylko z Płacami, D2),
* ``POST /vat/settlement`` — dokument rozliczenia VAT do bufora (lista
  „Księgowi” z Płacami albo administrator),
* ``GET /vat/ue?year=&month=`` — pozycje VAT-UE(5) miesiąca (K5b-3a), problemy,
* ``GET /vat/ue/file?year=&month=`` — plik VAT-UE(5) po walidacji schematem MF
  (tylko sprzedaż dla firm z UE — bez danych osób zespołu, więc bez Płac),
* ``POST /vat/jpk/compare?year=&month=`` — porównanie z JPK z Symfonii (K5b-3b,
  plik XML w żądaniu, niezapisywany; Płace albo administrator — D2),
* ``GET /vat/uek?year=&month=&issued_year=&issued_month=`` — pozycje VAT-UEK(5)
  za okres ``year``/``month`` z korekt wystawionych w miesiącu ``issued_*``
  (K5b-3c; „było” i „jest”),
* ``GET /vat/uek/file?…`` — plik VAT-UEK(5) po walidacji schematem MF (bez Płac,
  jak VAT-UE).
"""

from datetime import date, datetime, timezone
from typing import Any, Literal, Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Path,
    Query,
    Response,
    UploadFile,
    status,
)
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import FinanceModuleUser
from app.api.section_access import FINANCE_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.models.user import User
from app.services.finance_ledger.costs import LedgerError
from app.core.scheduling import business_today
from app.services.finance_ledger_schema import (
    ID_VALUE_MAX,
    NAME_MAX,
    SYMFONIA_ID_MAX,
)
from app.services.ledger import (
    documents,
    foreign,
    jpk,
    jpk_compare,
    vat,
    vat_settlement,
    vat_ue,
    vat_uek,
)
from app.services.ledger import settings as ledger_settings
from app.services.ledger.documents import Viewer
from app.services.ledger.settings import JPK_EMAIL_MAX, JPK_PHONE_MAX, MARKERS
from app.services.ledger_schema import ACCOUNT_MAX, DESCRIPTION_MAX, NUMBER_MAX
from app.services.ledger_vat_schema import NOTE_MAX, REASON_MAX

router = APIRouter(dependencies=FINANCE_SECTION_DEPENDENCIES)


ID_MAX = 2**63 - 1
#: ``finance_counterparties.id`` to INTEGER — większa liczba = 422, nie 500.
COUNTERPARTY_ID_MAX = 2**31 - 1
#: Nadwyżka z poprzedniej deklaracji (P_39) w pełnych złotych (TKwotaC: 14 cyfr).
SURPLUS_MAX = 10**14 - 1


class VatAccountsBody(BaseModel):
    """``None`` = bez zmiany; pusty ``foreign_account`` wyłącza zakładanie dostawców."""

    input_account: Optional[str] = Field(default=None, max_length=ACCOUNT_MAX + 8)
    foreign_account: Optional[str] = Field(default=None, max_length=ACCOUNT_MAX + 8)
    #: Różnice z zaokrągleń w rozliczeniu VAT (K5b-3c); pusty = brak konta.
    rounding_gain_account: Optional[str] = Field(
        default=None, max_length=ACCOUNT_MAX + 8
    )
    rounding_loss_account: Optional[str] = Field(
        default=None, max_length=ACCOUNT_MAX + 8
    )


class JpkBody(BaseModel):
    year: int = Field(ge=2000, le=2100)
    month: int = Field(ge=1, le=12)
    #: Uzasadnienie korekty (P_ORDZU) — wymagane po wysłanej wersji.
    reason: Optional[str] = Field(default=None, max_length=REASON_MAX)
    #: P_39 dla pierwszego miesiąca w NEXUSIE (pełne złote).
    opening_surplus: Optional[int] = Field(default=None, ge=0, le=SURPLUS_MAX)


class SettlementBody(BaseModel):
    year: int = Field(ge=2000, le=2100)
    month: int = Field(ge=1, le=12)


class JpkSentBody(BaseModel):
    note: Optional[str] = Field(default=None, max_length=NOTE_MAX)


class JpkContactBody(BaseModel):
    email: str = Field(max_length=JPK_EMAIL_MAX)
    phone: str = Field(default="", max_length=JPK_PHONE_MAX)


class NewSupplierBody(BaseModel):
    name: str = Field(max_length=NAME_MAX)
    country: str = Field(max_length=2)
    tax_id: Optional[str] = Field(default=None, max_length=ID_VALUE_MAX + 8)
    symfonia_partner_id: Optional[str] = Field(default=None, max_length=SYMFONIA_ID_MAX)
    #: Puste = pierwszy wolny numer pod kontem dostawców zagranicznych.
    account: Optional[str] = Field(default=None, max_length=ACCOUNT_MAX + 8)


class ForeignPurchaseBody(BaseModel):
    """Faktura dostawcy zagranicznego: dostawca z listy albo nowy (jedno z dwóch)."""

    supplier_id: Optional[int] = Field(default=None, ge=1, le=COUNTERPARTY_ID_MAX)
    new_supplier: Optional[NewSupplierBody] = None
    number: str = Field(max_length=NUMBER_MAX)
    issue_date: date
    #: Wykonanie usługi = obowiązek podatkowy (okres VAT i dzień kursu).
    service_date: date
    #: Otrzymanie faktury (DataWplywu w JPK); puste = data wystawienia.
    received_date: Optional[date] = None
    currency: str = Field(max_length=3)
    #: Netto w walucie faktury (kropka albo przecinek; ujemna = korekta).
    net: str = Field(max_length=24)
    vat_rate: Literal["23", "8", "5"]
    deduction: Literal["full", "none"]
    cost_account: str = Field(max_length=ACCOUNT_MAX + 8)
    description: Optional[str] = Field(default=None, max_length=DESCRIPTION_MAX)


class MarkersBody(BaseModel):
    markers: list[str] = Field(default_factory=list, max_length=len(MARKERS))


def _fail(exc: LedgerError) -> HTTPException:
    return HTTPException(exc.status, exc.message)


async def _context(
    db: AsyncSession, user: User
) -> tuple[ledger_settings.LedgerSettings, Viewer]:
    current = await ledger_settings.load(db)
    if not (
        ledger_settings.module_open(user, current, "ledger")
        and ledger_settings.module_open(user, current, "vat")
    ):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, ledger_settings.MODULE_DISABLED_DETAIL
        )
    return current, documents.viewer_for(user, current)


@router.get("/vat")
async def vat_registers(
    current_user: FinanceModuleUser,
    year: int = Query(ge=2000, le=2100),
    month: int = Query(ge=1, le=12),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    current, viewer = await _context(db, current_user)
    try:
        return await vat.registers(db, viewer, current, year=year, month=month)
    except LedgerError as exc:
        raise _fail(exc) from exc


@router.put("/vat/settings")
async def set_vat_accounts(
    body: VatAccountsBody,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _, viewer = await _context(db, current_user)
    if not viewer.admin:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "To ustawienie zmienia tylko administrator."
        )
    try:
        current = await ledger_settings.set_vat_accounts(
            db, body.model_dump(), actor=current_user
        )
    except LedgerError as exc:
        await db.rollback()
        raise _fail(exc) from exc
    await db.commit()
    return ledger_settings.to_json(current)["vat"]


@router.get("/vat/jpk")
async def jpk_overview(
    current_user: FinanceModuleUser,
    year: int = Query(ge=2000, le=2100),
    month: int = Query(ge=1, le=12),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    current, viewer = await _context(db, current_user)
    return await jpk.overview(db, viewer, current, year=year, month=month)


@router.post("/vat/jpk", status_code=status.HTTP_201_CREATED)
async def jpk_prepare(
    body: JpkBody,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    current, viewer = await _context(db, current_user)
    try:
        result = await jpk.prepare(
            db,
            viewer,
            current,
            year=body.year,
            month=body.month,
            reason=body.reason,
            opening_surplus=body.opening_surplus,
            now=datetime.now(timezone.utc),
        )
    except LedgerError as exc:
        await db.rollback()
        raise _fail(exc) from exc
    await db.commit()
    return result


@router.get("/vat/jpk/{file_id}/file")
async def jpk_file(
    current_user: FinanceModuleUser,
    file_id: int = Path(ge=1, le=ID_MAX),
    db: AsyncSession = Depends(get_db),
) -> Response:
    _, viewer = await _context(db, current_user)
    try:
        name, content = await jpk.download(db, viewer, file_id)
    except LedgerError as exc:
        raise _fail(exc) from exc
    return Response(
        content=content,
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.post("/vat/jpk/{file_id}/sent")
async def jpk_sent(
    body: JpkSentBody,
    current_user: FinanceModuleUser,
    file_id: int = Path(ge=1, le=ID_MAX),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _, viewer = await _context(db, current_user)
    try:
        result = await jpk.mark_sent(
            db, viewer, file_id, note=body.note, now=datetime.now(timezone.utc)
        )
    except LedgerError as exc:
        await db.rollback()
        raise _fail(exc) from exc
    await db.commit()
    return result


@router.put("/vat/jpk/settings")
async def set_jpk_contact(
    body: JpkContactBody,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _, viewer = await _context(db, current_user)
    if not viewer.admin:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "To ustawienie zmienia tylko administrator."
        )
    try:
        current = await ledger_settings.set_jpk_contact(
            db, body.model_dump(), actor=current_user
        )
    except LedgerError as exc:
        await db.rollback()
        raise _fail(exc) from exc
    await db.commit()
    return ledger_settings.to_json(current)["jpk"]


@router.get("/vat/settlement")
async def vat_settlement_preview(
    current_user: FinanceModuleUser,
    year: int = Query(ge=2000, le=2100),
    month: int = Query(ge=1, le=12),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    current, viewer = await _context(db, current_user)
    try:
        return await vat_settlement.preview(db, viewer, current, year=year, month=month)
    except LedgerError as exc:
        raise _fail(exc) from exc


@router.post("/vat/settlement")
async def vat_settlement_prepare(
    body: SettlementBody,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    current, viewer = await _context(db, current_user)
    try:
        result = await vat_settlement.prepare(
            db, viewer, current, year=body.year, month=body.month
        )
    except LedgerError as exc:
        await db.rollback()
        raise _fail(exc) from exc
    await db.commit()
    return result


@router.get("/vat/foreign")
async def foreign_purchases(
    current_user: FinanceModuleUser,
    year: int = Query(ge=2000, le=2100),
    month: int = Query(ge=1, le=12),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    current, viewer = await _context(db, current_user)
    try:
        return await foreign.overview(db, viewer, current, year=year, month=month)
    except LedgerError as exc:
        raise _fail(exc) from exc


@router.post("/vat/foreign", status_code=status.HTTP_201_CREATED)
async def create_foreign_purchase(
    body: ForeignPurchaseBody,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    current, viewer = await _context(db, current_user)
    try:
        result = await foreign.create(
            db, viewer, current, body.model_dump(), today=business_today()
        )
    except LedgerError as exc:
        await db.rollback()
        raise _fail(exc) from exc
    await db.commit()
    return result


@router.get("/vat/markers")
async def vat_markers(
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    current, viewer = await _context(db, current_user)
    return await vat.markers(db, viewer, current)


@router.put("/vat/markers/{counterparty_id}")
async def set_vat_markers(
    body: MarkersBody,
    current_user: FinanceModuleUser,
    counterparty_id: int = Path(ge=1, le=COUNTERPARTY_ID_MAX),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _, viewer = await _context(db, current_user)
    if not viewer.approver:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Znaczniki JPK ustawia osoba z listy „Księgowi” albo administrator.",
        )
    try:
        current = await ledger_settings.set_vat_markers(
            db, counterparty_id, body.markers, actor=current_user
        )
    except LedgerError as exc:
        await db.rollback()
        raise _fail(exc) from exc
    await db.commit()
    return await vat.marked_item(db, current, counterparty_id)


@router.get("/vat/ue")
async def vat_ue_overview(
    current_user: FinanceModuleUser,
    year: int = Query(ge=2000, le=2100),
    month: int = Query(ge=1, le=12),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    current, viewer = await _context(db, current_user)
    try:
        return await vat_ue.overview(db, viewer, current, year=year, month=month)
    except LedgerError as exc:
        raise _fail(exc) from exc


@router.get("/vat/ue/file")
async def vat_ue_file(
    current_user: FinanceModuleUser,
    year: int = Query(ge=2000, le=2100),
    month: int = Query(ge=1, le=12),
    db: AsyncSession = Depends(get_db),
) -> Response:
    current, viewer = await _context(db, current_user)
    try:
        name, content = await vat_ue.file(db, viewer, current, year=year, month=month)
    except LedgerError as exc:
        raise _fail(exc) from exc
    return Response(
        content=content,
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.post("/vat/jpk/compare")
async def jpk_compare_with_symfonia(
    current_user: FinanceModuleUser,
    year: int = Query(ge=2000, le=2100),
    month: int = Query(ge=1, le=12),
    file: UploadFile = File(..., description="JPK_V7M z Symfonii (XML)"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    current, viewer = await _context(db, current_user)
    content = await file.read(jpk_compare.MAX_BYTES + 1)
    try:
        return await jpk_compare.run(
            db, viewer, current, year=year, month=month, content=content
        )
    except LedgerError as exc:
        raise _fail(exc) from exc


@router.get("/vat/uek")
async def vat_uek_overview(
    current_user: FinanceModuleUser,
    year: int = Query(ge=2000, le=2100),
    month: int = Query(ge=1, le=12),
    issued_year: int = Query(ge=2000, le=2100),
    issued_month: int = Query(ge=1, le=12),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    current, viewer = await _context(db, current_user)
    try:
        return await vat_uek.overview(
            db,
            viewer,
            current,
            year=year,
            month=month,
            issued_year=issued_year,
            issued_month=issued_month,
        )
    except LedgerError as exc:
        raise _fail(exc) from exc


@router.get("/vat/uek/file")
async def vat_uek_file(
    current_user: FinanceModuleUser,
    year: int = Query(ge=2000, le=2100),
    month: int = Query(ge=1, le=12),
    issued_year: int = Query(ge=2000, le=2100),
    issued_month: int = Query(ge=1, le=12),
    db: AsyncSession = Depends(get_db),
) -> Response:
    current, viewer = await _context(db, current_user)
    try:
        name, content = await vat_uek.file(
            db,
            viewer,
            current,
            year=year,
            month=month,
            issued_year=issued_year,
            issued_month=issued_month,
        )
    except LedgerError as exc:
        raise _fail(exc) from exc
    return Response(
        content=content,
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )
