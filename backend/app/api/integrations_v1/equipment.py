"""Sprzęt w API v1: wydanie egzemplarza (odczyt).

Scope ``equipment:read``. Zdarzenia ``equipment.issued`` i ``equipment.returned``
(``services/integration_events``) niosą ``assignment_id`` — szczegóły daje
``GET /equipment/assignments/{id}``: egzemplarz (kategoria, model, numer
ewidencyjny), posiadacz i daty. Nie wychodzą: wartość z cennika i z protokołu,
numer seryjny, IMEI, ICCID, numer telefonu ani karty dostępu (integracje nie
potrzebują identyfikatorów sprzętu), notatki ani uwagi przy zwrocie.
Wyłączony moduł „Sprzęt” = 404 ``module_disabled``, jak na ekranach.

Moduł NIE MOŻE mieć ``from __future__ import annotations`` (slowapi #579).
"""

from datetime import datetime
from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Caller, require_service_scope
from app.api.integrations_v1.absences import require_module
from app.api.integrations_v1.common import (
    IdPath,
    IntegrationRoute,
    principal_rate_key,
    read_rate_limit,
)
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.models.academy import AcademyApplication
from app.models.candidate import Candidate
from app.models.contract import Contract
from app.models.equipment import (
    EquipmentAssignment,
    EquipmentExternalPerson,
    EquipmentItem,
    EquipmentModel,
)
from app.models.service_account import ServiceScope
from app.models.user import User

router = APIRouter(route_class=IntegrationRoute)

MODULE = "equipment"

EquipmentRead = Annotated[
    Caller,
    Depends(require_service_scope(ServiceScope.equipment_read, allow_admin_jwt=False)),
]

HolderKind = Literal["user", "contract", "external", "academy_application"]


# ── Modele odpowiedzi ────────────────────────────────────────────────────────


class EquipmentItemSummaryOut(BaseModel):
    item_id: int
    category: str = Field(
        description="laptop · telefon · monitor · karta_sim · karta_dostepu · "
        "akcesorium · inne"
    )
    model: str
    manufacturer: Optional[str]
    inventory_number: Optional[str]
    ownership: str = Field(description="nasz · klienta")


class EquipmentHolderRefOut(BaseModel):
    kind: HolderKind = Field(
        description="user — konto NEXUSA, contract — kontrakt konsultanta, "
        "external — osoba spoza NEXUSA, academy_application — uczestnik Akademii"
    )
    id: int
    name: Optional[str]


class EquipmentAssignmentOut(BaseModel):
    assignment_id: int
    item: EquipmentItemSummaryOut
    holder: EquipmentHolderRefOut
    issued_at: datetime
    returned_at: Optional[datetime] = Field(description="null — sprzęt u posiadacza.")
    return_condition: Optional[str] = Field(
        description="sprawny · uszkodzony · niekompletny · zgubiony"
    )


# ── Posiadacz ────────────────────────────────────────────────────────────────


def _candidate_name(first: Optional[str], last: Optional[str]) -> Optional[str]:
    return " ".join(part for part in (first, last) if part) or None


async def _holder(db: AsyncSession, row: EquipmentAssignment) -> EquipmentHolderRefOut:
    """Rodzaj, id i nazwa posiadacza (CHECK bazy: dokładnie jeden z czterech)."""
    if row.user_id is not None:
        name = await db.scalar(select(User.name).where(User.id == row.user_id))
        return EquipmentHolderRefOut(kind="user", id=row.user_id, name=name)
    if row.contract_id is not None:
        names = (
            await db.execute(
                select(Candidate.name, Candidate.lastname)
                .join(Contract, Contract.candidate_id == Candidate.id)
                .where(Contract.id == row.contract_id)
            )
        ).first()
        return EquipmentHolderRefOut(
            kind="contract",
            id=row.contract_id,
            name=_candidate_name(*names) if names else None,
        )
    if row.external_person_id is not None:
        name = await db.scalar(
            select(EquipmentExternalPerson.full_name).where(
                EquipmentExternalPerson.id == row.external_person_id
            )
        )
        return EquipmentHolderRefOut(
            kind="external", id=row.external_person_id, name=name
        )
    names = (
        await db.execute(
            select(Candidate.name, Candidate.lastname)
            .join(AcademyApplication, AcademyApplication.candidate_id == Candidate.id)
            .where(AcademyApplication.id == row.academy_application_id)
        )
    ).first()
    return EquipmentHolderRefOut(
        kind="academy_application",
        id=int(row.academy_application_id or 0),
        name=_candidate_name(*names) if names else None,
    )


# ── Trasy ────────────────────────────────────────────────────────────────────


@router.get(
    "/equipment/assignments/{assignment_id}",
    response_model=EquipmentAssignmentOut,
    summary="Wydanie sprzętu: egzemplarz, posiadacz, daty",
)
@limiter.limit(read_rate_limit, key_func=principal_rate_key)
async def get_assignment(
    request: Request,
    assignment_id: IdPath,
    _caller: EquipmentRead,
    db: AsyncSession = Depends(get_db),
) -> EquipmentAssignmentOut:
    """Egzemplarz (kategoria, model, numer ewidencyjny), posiadacz (rodzaj, id,
    imię i nazwisko) oraz daty wydania i zwrotu. Bez wartości sprzętu i bez
    numerów seryjnych, IMEI, ICCID, telefonu i karty dostępu."""
    await require_module(db, MODULE)
    found = (
        await db.execute(
            select(EquipmentAssignment, EquipmentItem, EquipmentModel)
            .join(EquipmentItem, EquipmentItem.id == EquipmentAssignment.item_id)
            .join(EquipmentModel, EquipmentModel.id == EquipmentItem.model_id)
            .where(EquipmentAssignment.id == assignment_id)
        )
    ).first()
    if found is None:
        raise HTTPException(404, detail="Wydanie nie istnieje.")
    assignment, item, model = found
    return EquipmentAssignmentOut(
        assignment_id=assignment.id,
        item=EquipmentItemSummaryOut(
            item_id=item.id,
            category=model.category,
            model=model.name,
            manufacturer=model.manufacturer,
            inventory_number=item.inventory_number,
            ownership=item.ownership,
        ),
        holder=await _holder(db, assignment),
        issued_at=assignment.issued_at,
        returned_at=assignment.returned_at,
        return_condition=assignment.return_condition,
    )
