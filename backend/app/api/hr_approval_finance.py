"""Finanse → „Wydatki ze zgodą” (etap 3 zgód, 0485, decyzje Artura 20.10.2026).

Prefiks ``/api/finance/approved-expenses`` (``app/main.py``, za wyłącznikiem
programu). Bramki: sekcja Finanse (router), uprawnienie „Moduł Finanse”
(``FinanceModuleUser`` z ``api/permission_access.py``) i moduł „Zgody”
włączony. Premie poza umową są tu tylko sumą miesiąca (bez osób) — reszta
w Płacach. Serwis: ``services/hr/approvals/settlement.py`` i
``finance_views.py``.

* ``GET /summary?year=&month=`` — kafle i suma miesiąca per rodzaj,
* ``GET /to-settle`` — zgody z dokumentem do rozliczenia i czekające na fakturę,
* ``POST /documents/{id}/settle`` — „Rozliczone” (nikt nie rozlicza własnego),
* ``GET /subscriptions`` — rejestr subskrypcji (z odnowieniami),
* ``GET /invoices?state=unmatched|fixed_cost|dismissed`` — „Faktury bez zgody”,
* ``POST /documents/{id}/pin`` — przypnij do zgody, ``/close`` — zamknij
  z notatką, ``/reopen`` — wróć do kolejki,
* ``GET /requests?q=`` — zgody do wyboru przy przypinaniu,
* ``GET/POST /fixed-sellers``, ``DELETE /fixed-sellers/{nip}`` — „stały koszt”.
"""

from contextlib import contextmanager
from typing import Any, Iterator, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.hr_gates import ensure_module
from app.api.permission_access import FinanceModuleUser
from app.api.section_access import FINANCE_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.core.scheduling import business_today
from app.models.hr_approval import ApprovalDocument
from app.models.user import User
from app.services.hr import modules as hr_modules
from app.services.hr.approvals import finance_views, settlement
from app.services.hr.approvals.service import ApprovalError
from app.services.hr.approvals.settlement_payload import document_payload

router = APIRouter(dependencies=FINANCE_SECTION_DEPENDENCIES)


@contextmanager
def _http_errors() -> Iterator[None]:
    try:
        yield
    except ApprovalError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc


async def _finance(user: User, db: AsyncSession) -> User:
    await ensure_module(db, user, hr_modules.HrModule.approvals)
    return user


class NoteIn(BaseModel):
    note: Optional[str] = Field(default=None, max_length=2000)


class PinIn(BaseModel):
    request_id: int = Field(ge=1)


class FixedSellerIn(BaseModel):
    seller_nip: str = Field(max_length=20)
    note: Optional[str] = Field(default=None, max_length=2000)


async def _doc(db: AsyncSession, doc: ApprovalDocument, viewer: User) -> dict[str, Any]:
    await db.refresh(doc)
    return document_payload(doc, viewer=viewer)


@router.get("/summary")
async def summary(
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
    year: Optional[int] = Query(default=None, ge=2020, le=2100),
    month: Optional[int] = Query(default=None, ge=1, le=12),
) -> dict[str, Any]:
    await _finance(current_user, db)
    today = business_today()
    return await finance_views.summary(db, year or today.year, month or today.month)


@router.get("/to-settle")
async def to_settle(
    current_user: FinanceModuleUser, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await _finance(current_user, db)
    return await finance_views.to_settle(db, current_user)


@router.post("/documents/{document_id}/settle")
async def settle(
    document_id: int,
    payload: NoteIn,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _finance(current_user, db)
    with _http_errors():
        doc = await settlement.settle_document(
            db, current_user, document_id, note=payload.note
        )
    return await _doc(db, doc, current_user)


@router.get("/subscriptions")
async def subscriptions(
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
    include_ended: bool = Query(default=False),
) -> dict[str, Any]:
    await _finance(current_user, db)
    return {
        "items": await finance_views.subscriptions(
            db, current_user, include_ended=include_ended
        )
    }


@router.get("/invoices")
async def invoices(
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
    state: Literal["unmatched", "fixed_cost", "dismissed"] = Query(default="unmatched"),
) -> dict[str, Any]:
    await _finance(current_user, db)
    return {"items": await finance_views.unmatched(db, current_user, state=state)}


@router.post("/documents/{document_id}/pin")
async def pin(
    document_id: int,
    payload: PinIn,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _finance(current_user, db)
    with _http_errors():
        doc = await settlement.pin_document(
            db, current_user, document_id, payload.request_id
        )
    return await _doc(db, doc, current_user)


@router.post("/documents/{document_id}/close")
async def close(
    document_id: int,
    payload: NoteIn,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _finance(current_user, db)
    with _http_errors():
        doc = await settlement.close_document(
            db, current_user, document_id, note=payload.note
        )
    return await _doc(db, doc, current_user)


@router.post("/documents/{document_id}/reopen")
async def reopen(
    document_id: int,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _finance(current_user, db)
    with _http_errors():
        doc = await settlement.reopen_document(db, current_user, document_id)
    return await _doc(db, doc, current_user)


@router.get("/requests")
async def open_requests(
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
    q: str = Query(default="", max_length=100),
) -> dict[str, Any]:
    await _finance(current_user, db)
    return {"items": await finance_views.open_requests(db, q)}


@router.get("/fixed-sellers")
async def fixed_sellers(
    current_user: FinanceModuleUser, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await _finance(current_user, db)
    return {"items": await finance_views.fixed_sellers(db)}


@router.post("/fixed-sellers")
async def add_fixed_seller(
    payload: FixedSellerIn,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _finance(current_user, db)
    with _http_errors():
        moved = await settlement.add_fixed_seller(
            db, current_user, seller_nip=payload.seller_nip, note=payload.note
        )
    return {"moved": moved, "items": await finance_views.fixed_sellers(db)}


@router.delete("/fixed-sellers/{seller_nip}")
async def remove_fixed_seller(
    seller_nip: str,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _finance(current_user, db)
    with _http_errors():
        moved = await settlement.remove_fixed_seller(db, current_user, seller_nip)
    return {"moved": moved, "items": await finance_views.fixed_sellers(db)}
