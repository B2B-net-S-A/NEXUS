"""Finanse → Rozliczenia → E-faktury Peppol (plan Nordei N2).

Moduł Finanse (``FinanceModuleUser``) i sekcja Finanse, jak reszta rozliczeń;
wyłączony moduł ``client_settlements`` = 404 (admin widzi zawsze). Stan
e-faktury przy każdej fakturze do odbiorcy Peppol, „Wyślij” pojedynczo i dla
zaznaczonych, pobranie pliku UBL, ustawienia (tryb test/produkcja,
automatyczna wysyłka, adresy odbiorców).
"""

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import FinanceModuleUser
from app.api.section_access import FINANCE_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.core.http_headers import content_disposition
from app.models.user import User
from app.services.client_settlements import settings as module_settings
from app.services.peppol import providers, service
from app.services.peppol import settings as peppol_settings

router = APIRouter(dependencies=FINANCE_SECTION_DEPENDENCIES)

MONTH_PATTERN = r"^[0-9]{4}-(0[1-9]|1[0-2])$"


class SendIn(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=service.SEND_BATCH_MAX)


class ReceiverIn(BaseModel):
    key: str = Field(max_length=34)
    name: str = Field(default="", max_length=peppol_settings.NAME_MAX)
    peppol_id: Optional[str] = Field(default=None, max_length=64)
    test_peppol_id: Optional[str] = Field(default=None, max_length=64)
    legal_id: Optional[str] = Field(default=None, max_length=64)
    legal_id_scheme: Optional[str] = Field(default=None, max_length=4)


class SettingsIn(BaseModel):
    mode: Optional[str] = Field(default=None, pattern=r"^(test|production)$")
    auto_send: Optional[bool] = None
    since: Optional[str] = Field(default=None, pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
    receivers: Optional[list[ReceiverIn]] = Field(default=None, max_length=peppol_settings.MAX_RECEIVERS)


async def _open(db: AsyncSession, user: User) -> None:
    enabled = await module_settings.is_enabled(db)
    if not module_settings.open_for(user, enabled):
        raise HTTPException(status.HTTP_404_NOT_FOUND, module_settings.MODULE_DISABLED_DETAIL)


def _fail(exc: service.EinvoiceError) -> HTTPException:
    return HTTPException(exc.status, str(exc))


@router.get("/clients")
async def clients(current_user: FinanceModuleUser, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Klienci z e-fakturami — przy nich ekran pokazuje zakładkę."""

    await _open(db, current_user)
    return {"client_ids": await service.client_ids(db)}


@router.get("")
async def list_einvoices(
    current_user: FinanceModuleUser,
    client_id: int = Query(..., ge=1),
    month: Optional[str] = Query(None, pattern=MONTH_PATTERN),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _open(db, current_user)
    return await service.list_view(db, client_id=client_id, month=month)


@router.post("/send")
async def send(body: SendIn, current_user: FinanceModuleUser, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    await _open(db, current_user)
    try:
        return await service.send(db, list(dict.fromkeys(body.ids)), actor=current_user)
    except service.EinvoiceError as exc:
        raise _fail(exc) from exc


@router.post("/refresh")
async def refresh(current_user: FinanceModuleUser, db: AsyncSession = Depends(get_db)) -> dict[str, int]:
    """Nowe faktury w zakresie, ponowne sprawdzenie i statusy doręczenia."""

    await _open(db, current_user)
    created = await service.scan(db)
    await db.commit()
    checked = await service.recheck(db)
    refreshed = await service.refresh(db)
    return {"created": created, "checked": checked, "refreshed": refreshed}


@router.get("/{einvoice_id}/ubl")
async def download(
    einvoice_id: int, current_user: FinanceModuleUser, db: AsyncSession = Depends(get_db)
) -> Response:
    await _open(db, current_user)
    try:
        content, filename = await service.document(db, einvoice_id)
    except service.EinvoiceError as exc:
        raise _fail(exc) from exc
    return Response(
        content=content,
        media_type="application/xml",
        headers={"Content-Disposition": content_disposition(filename)},
    )


@router.get("/settings")
async def get_settings(current_user: FinanceModuleUser, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    await _open(db, current_user)
    value = await peppol_settings.load(db)
    provider = providers.load_config()
    return {**value, "provider": provider.name, "provider_ready": provider.enabled, "provider_detail": provider.disabled_reason}


@router.put("/settings")
async def put_settings(
    body: SettingsIn, current_user: FinanceModuleUser, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await _open(db, current_user)
    patch = body.model_dump(exclude_none=True)
    if body.receivers is not None:
        patch["receivers"] = [entry.model_dump() for entry in body.receivers]
    try:
        value = peppol_settings.validate_update(await peppol_settings.load(db), patch)
    except peppol_settings.SettingsError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    await peppol_settings.save(db, value, actor=current_user)
    await db.commit()
    await service.recheck(db)
    return value
