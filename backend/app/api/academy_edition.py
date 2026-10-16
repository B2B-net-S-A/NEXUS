"""Edycja Akademii od strony recepcji — check lista, hotel i bilet, zestawy.

Prefiks ``/api/academy`` (obok ``app/api/academy.py``, bez kolizji ścieżek):
``GET /editions`` i ``/programs/{program_id}/editions/{yyyy-mm}/…``. Edycja =
program i miesiąc startu (``cohort_month``). Logika:
``services/academy_edition.py``.

Bramki (moduł „Sprzęt” wyłączony = 404, admin przechodzi):

* odczyt i zapis check listy oraz logistyki — uprawnienie „Sprzęt” (recepcja)
  albo dostęp do Akademii (ten sam co ``/api/academy``: sekcja Pipeline
  i rola z ``RecruiterPlus``),
* hurtowe wydanie zestawów — wyłącznie „Sprzęt”.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_onboarded_user
from app.api.equipment import _ensure_module, require_hr_equipment
from app.core.database import get_db
from app.core.scheduling import business_today
from app.models.user import User, UserRole
from app.services import academy_edition as edition
from app.services.action_permissions import ProductAction, has_permission
from app.services.equipment import issuing
from app.services.equipment.registry import EquipmentError
from app.services.request_semantics import is_read_only_http_request
from app.services.section_permissions import (
    ProductSection,
    SectionAccess,
    section_access_for_user,
)

router = APIRouter()

#: Role z ``RecruiterPlus`` (``app/api/deps.py``) — te same osoby pracują w Akademii.
ACADEMY_ROLES = (
    UserRole.admin,
    UserRole.head_of_recruitment,
    UserRole.delivery_lead,
    UserRole.talent_community_manager,
    UserRole.recruiter,
    UserRole.finance,
)
DENIED_DETAIL = (
    "Edycję Akademii prowadzi recepcja (uprawnienie „Sprzęt”) albo osoba "
    "z dostępem do Akademii."
)

#: Miesiąc edycji w adresie: ``2026-11``.
Month = Annotated[str, Path(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")]
EDITION = "/programs/{program_id}/editions/{month}"

LogisticsStatus = Literal[
    "nie_dotyczy", "do_zrobienia", "zrobione", "do_anulowania", "anulowane"
]


def academy_access(user: User, request: Request) -> bool:
    """Dostęp do Akademii jak w ``/api/academy``: rola rekrutera i sekcja Pipeline."""
    if not user.has_any_role(*ACADEMY_ROLES):
        return False
    required = (
        SectionAccess.read
        if is_read_only_http_request(request.method, request.url.path)
        else SectionAccess.write
    )
    return section_access_for_user(user, ProductSection.pipeline) >= required


def require_hr_academy_edition():
    """Moduł „Sprzęt” włączony i: uprawnienie „Sprzęt” albo dostęp do Akademii."""

    async def _check(
        request: Request,
        current_user: User = Depends(require_onboarded_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        await _ensure_module(db, current_user)
        if has_permission(current_user, ProductAction.equipment):
            return current_user
        if academy_access(current_user, request):
            return current_user
        raise HTTPException(status.HTTP_403_FORBIDDEN, DENIED_DETAIL)

    return _check


_edition = require_hr_academy_edition()
_issuer = require_hr_equipment(ProductAction.equipment)


def _http(exc: EquipmentError) -> HTTPException:
    return HTTPException(exc.status, exc.message)


def _cohort(month: str) -> date:
    year, number = (int(part) for part in month.split("-"))
    return date(year, number, 1)


class ChecklistPatch(BaseModel):
    done: Optional[bool] = None
    note: Optional[str] = Field(default=None, max_length=edition.NOTE_MAX)


class LogisticsPatch(BaseModel):
    hotel: Optional[LogisticsStatus] = None
    ticket: Optional[LogisticsStatus] = None
    note: Optional[str] = Field(default=None, max_length=edition.NOTE_MAX)


class KitLineIn(BaseModel):
    item_id: int
    unit_value: Optional[Decimal] = Field(default=None, ge=0, le=Decimal("9999999"))
    accessories: Optional[str] = Field(default=None, max_length=200)


class KitIn(BaseModel):
    application_id: int
    lines: list[KitLineIn] = Field(min_length=1, max_length=40)


class BulkIssueIn(BaseModel):
    protocol_date: Optional[date] = None
    send_link: bool = False
    participants: list[KitIn] = Field(min_length=1, max_length=60)


@router.get("/editions")
async def list_editions(
    program_id: Optional[int] = Query(default=None),
    _: User = Depends(_edition),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Edycje z uczestnikami (wybór edycji w recepcji i w Akademii)."""
    return {"items": await edition.list_editions(db, program_id=program_id)}


@router.get(EDITION)
async def get_edition(
    program_id: int,
    month: Month,
    current_user: User = Depends(_edition),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        return await edition.edition_view(
            db,
            program_id,
            _cohort(month),
            can_issue=has_permission(current_user, ProductAction.equipment),
        )
    except EquipmentError as exc:
        raise _http(exc) from exc


@router.patch(EDITION + "/checklist/{item_id}")
async def update_checklist_item(
    program_id: int,
    month: Month,
    item_id: int,
    payload: ChecklistPatch,
    current_user: User = Depends(_edition),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        return await edition.set_checklist_item(
            db,
            program_id,
            _cohort(month),
            item_id,
            payload.model_dump(exclude_unset=True),
            actor=current_user,
        )
    except EquipmentError as exc:
        raise _http(exc) from exc


@router.patch(EDITION + "/participants/{application_id}")
async def update_participant_logistics(
    program_id: int,
    month: Month,
    application_id: int,
    payload: LogisticsPatch,
    current_user: User = Depends(_edition),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        return await edition.set_logistics(
            db,
            program_id,
            _cohort(month),
            application_id,
            payload.model_dump(exclude_unset=True),
            actor=current_user,
        )
    except EquipmentError as exc:
        raise _http(exc) from exc


@router.post(EDITION + "/issue")
async def issue_edition_kits(
    program_id: int,
    month: Month,
    payload: BulkIssueIn,
    current_user: User = Depends(_issuer),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Ten sam zestaw kilku uczestnikom; raport per osoba (osobne protokoły)."""
    try:
        return await edition.issue_kits(
            db,
            program_id,
            _cohort(month),
            [
                edition.Kit(
                    application_id=kit.application_id,
                    lines=[
                        issuing.IssueLine(
                            item_id=line.item_id,
                            unit_value=line.unit_value,
                            accessories=line.accessories,
                        )
                        for line in kit.lines
                    ],
                )
                for kit in payload.participants
            ],
            protocol_date=payload.protocol_date or business_today(),
            actor=current_user,
            with_link=payload.send_link,
        )
    except EquipmentError as exc:
        raise _http(exc) from exc
