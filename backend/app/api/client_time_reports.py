"""Finanse → Rozliczenia → Raport klienta (T4T): plan Nordei N1.

Te same bramki co ``client_settlements.py`` (moduł Finanse, sekcja Finanse,
wyłączony moduł rozliczeń = 404). Godziny widzi każdy z dostępem do
rozliczeń; kwoty faktury kontraktora i stawka tylko przy
``can_read_client_finance`` (Finanse, DL u swojego klienta — decyzja Artura
z 13.11.2026, odpowiedź A5).
"""

import re
from datetime import date
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi import status as http_status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import FinanceModuleUser
from app.api.financial_access import can_read_client_finance
from app.api.section_access import FINANCE_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.core.scheduling import business_today, local_now
from app.models.user import User
from app.services.access_scope import resolve_delivery_lead_finance_client_ids
from app.services.client_settlements import settings as module_settings
from app.services.client_settlements import time_reports
from app.services.client_settlements.service import SettlementError

router = APIRouter(dependencies=FINANCE_SECTION_DEPENDENCIES)

MONTH_PATTERN = r"^[0-9]{4}-(0[1-9]|1[0-2])$"
KEY_PATTERN = r"^([A-Za-z][A-Za-z0-9]{3,15}|c[0-9]{1,10})$"
MAX_UPLOAD_BYTES = 30 * 1024 * 1024


class ManualIdIn(BaseModel):
    client_id: int = Field(ge=1)
    contract_id: int = Field(ge=1)
    kind: str = Field(pattern=r"^(client_person_no|project_no)$")
    value: str = Field(min_length=4, max_length=32)


async def _open(db: AsyncSession, user: User) -> None:
    enabled = await module_settings.is_enabled(db)
    if not module_settings.open_for(user, enabled):
        raise HTTPException(
            http_status.HTTP_404_NOT_FOUND, module_settings.MODULE_DISABLED_DETAIL
        )


def _fail(exc: SettlementError) -> HTTPException:
    return HTTPException(exc.status, exc.message)


async def _amounts(db: AsyncSession, user: User, client_id: int) -> bool:
    return can_read_client_finance(
        user,
        client_id=client_id,
        delivery_lead_finance_client_ids=await resolve_delivery_lead_finance_client_ids(
            user, db
        ),
    )


@router.get("/clients")
async def clients(
    current_user: FinanceModuleUser,
    month: str = Query(..., pattern=MONTH_PATTERN),
    db: AsyncSession = Depends(get_db),
) -> dict[str, list[int]]:
    """Klienci z podzakładką „Raport klienta (T4T)” w tym miesiącu."""

    await _open(db, current_user)
    return {"client_ids": await time_reports.enabled_clients(db, month)}


@router.get("")
async def month(
    current_user: FinanceModuleUser,
    client_id: int = Query(..., ge=1),
    month: str = Query(..., pattern=MONTH_PATTERN),
    version_id: Optional[int] = Query(None, ge=1),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _open(db, current_user)
    try:
        return await time_reports.month_view(
            db, client_id, month, version_id=version_id
        )
    except SettlementError as exc:
        raise _fail(exc) from exc


@router.post("")
async def upload(
    current_user: FinanceModuleUser,
    client_id: int = Form(..., ge=1),
    month: str = Form(..., pattern=MONTH_PATTERN),
    received_on: date = Form(...),
    sheet: Optional[str] = Form(None, max_length=64),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Nowa wersja raportu T4T. Plik z kilkoma arkuszami raportu bez ``sheet``
    zwraca ``needs_sheet`` z listą arkuszy i niczego nie zapisuje."""

    await _open(db, current_user)
    if received_on > business_today():
        raise HTTPException(
            http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Data otrzymania raportu nie może być z przyszłości.",
        )
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            http_status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"Plik większy niż {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.",
        )
    try:
        result = await time_reports.upload(
            db,
            client_id,
            month,
            received_on=received_on,
            file_name=file.filename,
            content=content,
            sheet=sheet,
            actor=current_user,
        )
        await db.commit()
        return result
    except SettlementError as exc:
        await db.rollback()
        raise _fail(exc) from exc


@router.get("/person/{key}")
async def person(
    key: str,
    current_user: FinanceModuleUser,
    client_id: int = Query(..., ge=1),
    month: str = Query(..., pattern=MONTH_PATTERN),
    version_id: Optional[int] = Query(None, ge=1),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Karta osoby: ``key`` = numer osoby u klienta albo ``c<kontrakt>``."""

    await _open(db, current_user)
    if not re.match(KEY_PATTERN, key):
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "Nie ma takiej osoby.")
    try:
        return await time_reports.person_card(
            db,
            client_id,
            month,
            key,
            version_id=version_id,
            amounts=await _amounts(db, current_user, client_id),
        )
    except SettlementError as exc:
        raise _fail(exc) from exc


@router.get("/ids")
async def ids(
    current_user: FinanceModuleUser,
    client_id: int = Query(..., ge=1),
    month: str = Query(..., pattern=MONTH_PATTERN),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _open(db, current_user)
    try:
        return await time_reports.ids_view(db, client_id, month)
    except SettlementError as exc:
        raise _fail(exc) from exc


@router.post("/ids/fill")
async def fill_ids(
    current_user: FinanceModuleUser,
    client_id: int = Query(..., ge=1),
    db: AsyncSession = Depends(get_db),
) -> dict[str, int]:
    """Numery osób i NIDS z faktur do klienta w KSeF."""

    await _open(db, current_user)
    try:
        result = await time_reports.fill_from_ksef(db, client_id, now=local_now())
        await db.commit()
        return result
    except SettlementError as exc:
        await db.rollback()
        raise _fail(exc) from exc


async def _decide(
    db: AsyncSession, id_id: int, user: User, *, approve: bool
) -> dict[str, Any]:
    try:
        row = await time_reports.decide_id(
            db, id_id, approve=approve, actor=user, now=local_now()
        )
        await db.commit()
    except SettlementError as exc:
        await db.rollback()
        raise _fail(exc) from exc
    return {"id": row.id, "state": row.state}


@router.post("/ids/{id_id}/confirm")
async def confirm_id(
    id_id: int, current_user: FinanceModuleUser, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await _open(db, current_user)
    return await _decide(db, id_id, current_user, approve=True)


@router.post("/ids/{id_id}/reject")
async def reject_id(
    id_id: int, current_user: FinanceModuleUser, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await _open(db, current_user)
    return await _decide(db, id_id, current_user, approve=False)


@router.post("/ids")
async def add_id(
    body: ManualIdIn,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _open(db, current_user)
    try:
        row = await time_reports.add_manual_id(
            db,
            body.client_id,
            contract_id=body.contract_id,
            kind=body.kind,
            value=body.value,
            actor=current_user,
            now=local_now(),
        )
        await db.commit()
    except SettlementError as exc:
        await db.rollback()
        raise _fail(exc) from exc
    return {"id": row.id, "state": row.state}
