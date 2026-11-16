"""Księgowość → Sprawozdania (K8a): bilans, RZiS i pozycje kont.

Prefiks ``/api/accounting`` (jak księga K1, ``app/main.py``). Bramki: sekcja
Finanse (router), „Moduł Finanse” (``FinanceModuleUser``) i przełączniki
modułów ``ledger`` oraz ``reports`` (wyłączony = 404, admin widzi zawsze).
Pozycję konta zmienia się zapisem konta w planie (``PATCH /chart/{id}``,
pole ``report_line`` — walidacja znacznikiem MF).

* ``GET /reports/statements?year=&month_from=&month_to=`` — bilans na koniec
  ``month_to`` i RZiS (wariant porównawczy) za ``month_from``–``month_to``,
  konta bez pozycji i ostrzeżenia,
* ``GET /reports/accounts`` — plan kont z pozycją sprawozdania i jej źródłem,
* ``GET /reports/markers`` — słownik znaczników MF (JPK_KR_PD, jednostki
  pozostałe) do wyboru pozycji.

K8c — roczne JPK_KR_PD(1) i JPK_ST_KR(1) (NEXUS niczego nie wysyła):

* ``GET /reports/jpk-kr?year=`` — braki blokujące obu plików, ostrzeżenia
  i co wolno tej osobie,
* ``GET /reports/jpk-kr/file?year=&kind=kr|st&correction=`` — plik XML
  sprawdzony schematem MF; JPK_KR_PD (dokumenty płacowe, D2) tylko osoba
  z Płacami albo administrator,
* ``POST /reports/jpk-kr/compare?year=`` — porównanie z plikiem z Symfonii
  (rok w trybie ``symfonia``/``parallel``; Płace albo administrator),
* ``PUT /reports/jpk-kr/settings`` — adres siedziby i CIT estoński
  (administrator).
"""

from datetime import datetime, timezone
from typing import Any, Literal, Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
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
from app.services.ledger import jpk_kr, jpk_kr_compare, jpk_st_kr, markers, statements
from app.services.ledger import settings as ledger_settings
from app.services.ledger.documents import Viewer, viewer_for

router = APIRouter(dependencies=FINANCE_SECTION_DEPENDENCIES)


async def _require_open(db: AsyncSession, user: User) -> ledger_settings.LedgerSettings:
    current = await ledger_settings.load(db)
    if not (
        ledger_settings.module_open(user, current, "ledger")
        and ledger_settings.module_open(user, current, "reports")
    ):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, ledger_settings.MODULE_DISABLED_DETAIL
        )
    return current


async def _context(
    db: AsyncSession, user: User
) -> tuple[ledger_settings.LedgerSettings, Viewer]:
    current = await _require_open(db, user)
    return current, viewer_for(user, current)


@router.get("/reports/statements")
async def financial_statements(
    current_user: FinanceModuleUser,
    year: int = Query(ge=2000, le=2100),
    month_from: Optional[int] = Query(default=None, ge=1, le=12),
    month_to: Optional[int] = Query(default=None, ge=1, le=12),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _require_open(db, current_user)
    try:
        return await statements.statements(
            db, year=year, month_from=month_from, month_to=month_to
        )
    except LedgerError as exc:
        raise HTTPException(exc.status, exc.message) from exc


@router.get("/reports/accounts")
async def report_accounts(
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _require_open(db, current_user)
    return {"items": await statements.account_positions(db)}


@router.get("/reports/markers")
async def report_markers(
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _require_open(db, current_user)
    return {"items": markers.catalogue()}


@router.get("/reports/jpk-kr")
async def jpk_kr_overview(
    current_user: FinanceModuleUser,
    year: int = Query(ge=2000, le=2100),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    current, viewer = await _context(db, current_user)
    try:
        overview = await jpk_kr.overview(db, viewer, current, year=year)
        overview["st"] = await jpk_st_kr.overview(db, current, year=year)
    except LedgerError as exc:
        raise HTTPException(exc.status, exc.message) from exc
    return overview


@router.get("/reports/jpk-kr/file")
async def jpk_kr_file(
    current_user: FinanceModuleUser,
    year: int = Query(ge=2000, le=2100),
    kind: Literal["kr", "st"] = Query(default="kr"),
    correction: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
) -> Response:
    current, viewer = await _context(db, current_user)
    now = datetime.now(timezone.utc)
    try:
        if kind == "st":
            name, content = await jpk_st_kr.file(
                db, current, year=year, correction=correction, now=now
            )
        else:
            name, content = await jpk_kr.file(
                db, viewer, current, year=year, correction=correction, now=now
            )
    except LedgerError as exc:
        raise HTTPException(exc.status, exc.message) from exc
    return Response(
        content=content,
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.post("/reports/jpk-kr/compare")
async def jpk_kr_compare_with_symfonia(
    current_user: FinanceModuleUser,
    year: int = Query(ge=2000, le=2100),
    file: UploadFile = File(..., description="JPK_KR_PD z Symfonii (XML)"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    current, viewer = await _context(db, current_user)
    content = await file.read(jpk_kr_compare.MAX_BYTES + 1)
    try:
        return await jpk_kr_compare.run(db, viewer, current, year=year, content=content)
    except LedgerError as exc:
        raise HTTPException(exc.status, exc.message) from exc


class JpkKrAddressBody(BaseModel):
    province: str = Field(default="", max_length=200)
    county: str = Field(default="", max_length=200)
    commune: str = Field(default="", max_length=200)
    street: str = Field(default="", max_length=200)
    building: str = Field(default="", max_length=200)
    unit: str = Field(default="", max_length=200)
    city: str = Field(default="", max_length=200)
    postal_code: str = Field(default="", max_length=200)


class JpkKrSettingsBody(BaseModel):
    address: JpkKrAddressBody = Field(default_factory=JpkKrAddressBody)
    estonian: bool = False
    estonian_since: Optional[int] = Field(default=None, ge=2000, le=2100)


@router.put("/reports/jpk-kr/settings")
async def jpk_kr_settings(
    body: JpkKrSettingsBody,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _, viewer = await _context(db, current_user)
    if not viewer.admin:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "To ustawienie zmienia tylko administrator."
        )
    try:
        current = await ledger_settings.set_jpk_kr(
            db, body.model_dump(), actor=current_user
        )
    except LedgerError as exc:
        await db.rollback()
        raise HTTPException(exc.status, exc.message) from exc
    await db.commit()
    return ledger_settings.to_json(current)["jpk_kr"]
