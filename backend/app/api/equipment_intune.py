"""Sprzęt ↔ Intune (etap 4, D9) — stan odczytu, rozjazdy i decyzje recepcji.

Prefiks ``/api/equipment/intune`` (wpięty w ``app/main.py``). Bramki jak
w ``app/api/equipment.py``: moduł „Sprzęt” włączony (admin przechodzi zawsze)
i uprawnienie „Sprzęt”; ręczny przebieg tylko admin. Odczyt z Microsoftu
i rozjazdy liczy ``app/services/equipment/intune.py``.
"""

from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_onboarded_user
from app.api.equipment import require_hr_equipment
from app.api.hr_gates import MODULE_DISABLED_DETAIL
from app.core.database import get_db
from app.models.user import User, UserRole
from app.services.action_permissions import ProductAction
from app.services.equipment import intune, intune_graph
from app.services.equipment.registry import EquipmentError
from app.services.hr import modules as hr_modules

router = APIRouter()

MODE_OFF_DETAIL = (
    "Odczyt z Intune jest wyłączony — czeka na zgodę administratora Microsoft 365 "
    "i przełączenie trybu."
)
RUNNING_DETAIL = "Odczyt z Intune właśnie trwa. Odśwież za chwilę."
ADMIN_ONLY_DETAIL = "Ręczny odczyt z Intune uruchamia administrator."

_manager = require_hr_equipment(ProductAction.equipment)


def require_hr_equipment_admin():
    """Admin; moduł „Sprzęt” go nie zatrzymuje (przygotowanie przełączenia)."""

    async def _check(
        current_user: User = Depends(require_onboarded_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        loaded = await hr_modules.load_modules(db)
        if not hr_modules.module_open_for(current_user, loaded, "equipment"):
            raise HTTPException(status.HTTP_404_NOT_FOUND, MODULE_DISABLED_DETAIL)
        if not current_user.has_role(UserRole.admin):
            raise HTTPException(status.HTTP_403_FORBIDDEN, ADMIN_ONLY_DETAIL)
        return current_user

    return _check


_admin = require_hr_equipment_admin()


def _http(exc: EquipmentError) -> HTTPException:
    return HTTPException(exc.status, exc.message)


class ResolveIn(BaseModel):
    resolution: Literal["wyjasnione", "pominiete"]
    note: Optional[str] = Field(default=None, max_length=intune.NOTE_MAX)


class LinkIn(BaseModel):
    item_id: int = Field(ge=1)


@router.get("/status")
async def intune_status(
    _: User = Depends(_manager), db: AsyncSession = Depends(get_db)
) -> dict:
    return await intune.sync_status(db)


@router.get("/discrepancies")
async def intune_discrepancies(
    _: User = Depends(_manager), db: AsyncSession = Depends(get_db)
) -> dict:
    return await intune.discrepancies(db)


@router.post("/devices/{device_id}/resolve")
async def resolve_device(
    device_id: int,
    payload: ResolveIn,
    current_user: User = Depends(_manager),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        return await intune.resolve(
            db, device_id, payload.resolution, payload.note, current_user
        )
    except EquipmentError as exc:
        raise _http(exc) from exc


@router.post("/devices/{device_id}/link")
async def link_device(
    device_id: int,
    payload: LinkIn,
    current_user: User = Depends(_manager),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        return await intune.link_item(db, device_id, payload.item_id, current_user)
    except EquipmentError as exc:
        raise _http(exc) from exc


@router.post("/sync")
async def sync_now(
    _: User = Depends(_admin), db: AsyncSession = Depends(get_db)
) -> dict:
    if intune_graph.current_mode() == "off":
        raise HTTPException(status.HTTP_409_CONFLICT, MODE_OFF_DETAIL)
    result = await intune.run_once(db, manual=True)
    if result.get("status") == "skipped":
        raise HTTPException(status.HTTP_409_CONFLICT, RUNNING_DETAIL)
    if result.get("status") == "disabled":
        raise HTTPException(status.HTTP_409_CONFLICT, MODE_OFF_DETAIL)
    return {**result, "error_text": intune.error_text(result.get("error"))}
