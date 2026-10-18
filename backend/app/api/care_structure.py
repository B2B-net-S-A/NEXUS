"""Opieka · propozycje struktury u klienta (decyzja Artura 18.10.2026).

„Propozycja automatu + akcept DL”. Trasy pod ``/api/care`` — router dołącza
``app/api/contract_care.py`` (ten sam prefiks). Reguły:
``services/care/structure_rules.py``, dane i zapis:
``services/care/structure_proposals.py``. Bramki z ``app/api/care_gates.py``:

* odczyt (lista klientów i propozycje klienta) — ``PeopleReader`` (D11:
  opiekun, DL klienta, Head of Recruitment, admin); Delivery Lead tylko
  u swoich klientów (cudzy → 403),
* menedżer konsultanta: zatwierdzenie (też „Zatwierdź pewne”), zmiana na inną
  osobę klienta albo nową, „Pomiń” i „Przywróć” — ``ManagerApprover``
  (Delivery Lead klienta z edycją kontraktów albo admin),
* „Podlega pod”: zatwierdzenie i „Pomiń” — ``OrgProposalsEditor`` (krąg D11,
  bo odpowiedź niesie propozycje z konsultantami) i prawo edycji kontaktów klienta, jak
  ręczna zmiana w drzewie
  (``PATCH /clients/{id}/contacts/{contact_id}``).

Nic nie wychodzi do klienta: odczyt niczego nie zapisuje, a zapis zmienia
tylko kontrakt albo kontakt w NEXUSIE.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.care_gates import (
    ManagerApprover,
    OrgProposalsEditor,
    PeopleReader,
    approves_client_managers,
    reads_client_people,
)
from app.core.database import get_db
from app.models.user import User
from app.services.access_scope import resolve_delivery_lead_assigned_client_ids
from app.services.action_permissions import ProductAction, has_permission
from app.services.care import access as care_access
from app.services.care import client_people, tech_map
from app.services.care import structure_proposals as proposals
from app.services.client_access import resolve_client_access
from app.services.contract_care_schema import NAME_MAX, SHORT_TEXT_MAX

router = APIRouter()


async def _can_apply_managers(db: AsyncSession, user: User, client_id: int) -> bool:
    """Lustro ``ManagerApprover`` dla przycisków (serwer i tak sprawdza bramką)."""

    if not approves_client_managers(user) or not has_permission(
        user, ProductAction.contracts_orders_edit
    ):
        return False
    assigned = await resolve_delivery_lead_assigned_client_ids(user, db)
    return assigned is None or client_id in assigned


async def _client_payload(
    db: AsyncSession, client_id: int, user: User
) -> dict[str, Any]:
    datas = await proposals.load(db, client_ids=[client_id])
    access = await resolve_client_access(db, user, client_id)
    payload = await proposals.client_payload(db, datas[client_id])
    return {
        **payload,
        "can_apply_managers": await _can_apply_managers(db, user, client_id),
        "can_apply_org": access.can_edit_contacts and reads_client_people(user),
    }


@router.get("/structure-proposals")
async def structure_summary(
    current_user: User = Depends(PeopleReader),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Klienci z zakresu z licznikami: bez menedżera, pewne, niepewne, bez propozycji."""

    allowed = await care_access.allowed_client_ids(current_user, db)
    datas = await proposals.load(db, client_ids=allowed)
    items = proposals.summary_rows(datas.values())
    return {
        "items": items,
        "totals": {
            key: sum(row[key] for row in items)
            for key in (
                "consultants",
                "without_manager",
                "certain",
                "uncertain",
                "none",
                "open",
                "new_person",
            )
        },
    }


@router.get("/clients/{client_id}/structure-proposals")
async def client_structure_proposals(
    client_id: int,
    current_user: User = Depends(PeopleReader),
    db: AsyncSession = Depends(get_db),
) -> dict:
    client = await care_access.load_client(db, client_id, current_user)
    return await _client_payload(db, client.id, current_user)


class ManagerChoiceBody(BaseModel):
    contract_id: int
    contact_id: Optional[int] = None
    #: „Zmień” na osobę spoza listy — zakłada kontakt klienta (bez duplikatu).
    new_person_name: Optional[str] = Field(default=None, max_length=NAME_MAX)
    new_person_position: Optional[str] = Field(default=None, max_length=SHORT_TEXT_MAX)


class ManagersBody(BaseModel):
    items: list[ManagerChoiceBody] = Field(min_length=1, max_length=proposals.APPLY_MAX)


@router.post("/clients/{client_id}/structure-proposals/managers")
async def apply_managers(
    client_id: int,
    body: ManagersBody,
    current_user: User = Depends(ManagerApprover),
    db: AsyncSession = Depends(get_db),
) -> dict:
    client = await care_access.load_client(db, client_id, current_user)
    result = await proposals.apply_managers(
        db,
        client_id=client.id,
        choices=[
            proposals.ManagerChoice(
                contract_id=item.contract_id,
                contact_id=item.contact_id,
                new_person_name=item.new_person_name,
                new_person_position=item.new_person_position,
            )
            for item in body.items
        ],
        actor_id=current_user.id,
    )
    await tech_map.invalidate([client.id])
    return {**result, "client": await _client_payload(db, client.id, current_user)}


class SkipBody(BaseModel):
    #: Osoba, którą automat proponował (``None`` = pozycja bez propozycji).
    proposed_contact_id: Optional[int] = None


@router.put("/clients/{client_id}/structure-proposals/managers/{contract_id}/skip")
async def skip_manager(
    client_id: int,
    contract_id: int,
    body: SkipBody,
    current_user: User = Depends(ManagerApprover),
    db: AsyncSession = Depends(get_db),
) -> dict:
    client = await care_access.load_client(db, client_id, current_user)
    await proposals.set_skip(
        db,
        client_id=client.id,
        kind="manager",
        subject_id=contract_id,
        proposed_contact_id=body.proposed_contact_id,
        actor_id=current_user.id,
    )
    return await _client_payload(db, client.id, current_user)


@router.delete("/clients/{client_id}/structure-proposals/managers/{contract_id}/skip")
async def restore_manager(
    client_id: int,
    contract_id: int,
    current_user: User = Depends(ManagerApprover),
    db: AsyncSession = Depends(get_db),
) -> dict:
    client = await care_access.load_client(db, client_id, current_user)
    await proposals.clear_skip(
        db, client_id=client.id, kind="manager", subject_id=contract_id
    )
    return await _client_payload(db, client.id, current_user)


async def _org_editor_client(db: AsyncSession, client_id: int, user: User):
    client = await care_access.load_client(db, client_id, user)
    access = await resolve_client_access(db, user, client.id)
    if not access.can_edit_contacts:
        raise access.edit_denial(
            "edycja struktury u klienta wymaga prawa edycji kontaktów klienta"
        )
    return client


class ReportsToChoiceBody(BaseModel):
    contact_id: int
    reports_to_contact_id: int


class ReportsToBody(BaseModel):
    items: list[ReportsToChoiceBody] = Field(
        min_length=1, max_length=proposals.APPLY_MAX
    )


@router.post("/clients/{client_id}/structure-proposals/reports-to")
async def apply_reports_to(
    client_id: int,
    body: ReportsToBody,
    current_user: User = Depends(OrgProposalsEditor),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """„Podlega pod” z propozycji — ta sama reguła co ręczna zmiana w drzewie.

    Pozycja, która zamknęłaby pętlę albo wskazuje osobę innego klienta,
    wraca w ``rejected`` z powodem; reszta się zapisuje. Osoba, której ktoś
    w międzyczasie wpisał przełożonego, zostaje bez zmian (``conflicts``).
    """

    client = await _org_editor_client(db, client_id, current_user)
    current = {
        person.id: person.reports_to_id
        for person in (await proposals.load(db, client_ids=[client.id]))[
            client.id
        ].people
    }
    applied: list[int] = []
    conflicts: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for item in body.items:
        if current.get(item.contact_id) not in (None, item.reports_to_contact_id):
            conflicts.append(
                {"contact_id": item.contact_id, "reason": "reports_to_set"}
            )
            continue
        try:
            await client_people.update_contact_org(
                db,
                client_id=client.id,
                contact_id=item.contact_id,
                changes={"reports_to_contact_id": item.reports_to_contact_id},
                actor_id=current_user.id,
            )
        except HTTPException as exc:
            # Walidacja pada przed zapisem — reszta pozycji idzie dalej.
            if exc.status_code not in (
                status.HTTP_404_NOT_FOUND,
                status.HTTP_422_UNPROCESSABLE_ENTITY,
            ):
                raise
            rejected.append({"contact_id": item.contact_id, "detail": exc.detail})
            continue
        current[item.contact_id] = item.reports_to_contact_id
        applied.append(item.contact_id)
        await proposals.clear_skip(
            db, client_id=client.id, kind="reports_to", subject_id=item.contact_id
        )
    await tech_map.invalidate([client.id])
    return {
        "applied": applied,
        "conflicts": conflicts,
        "rejected": rejected,
        "client": await _client_payload(db, client.id, current_user),
    }


@router.put("/clients/{client_id}/structure-proposals/reports-to/{contact_id}/skip")
async def skip_reports_to(
    client_id: int,
    contact_id: int,
    body: SkipBody,
    current_user: User = Depends(OrgProposalsEditor),
    db: AsyncSession = Depends(get_db),
) -> dict:
    client = await _org_editor_client(db, client_id, current_user)
    await proposals.set_skip(
        db,
        client_id=client.id,
        kind="reports_to",
        subject_id=contact_id,
        proposed_contact_id=body.proposed_contact_id,
        actor_id=current_user.id,
    )
    return await _client_payload(db, client.id, current_user)


@router.delete("/clients/{client_id}/structure-proposals/reports-to/{contact_id}/skip")
async def restore_reports_to(
    client_id: int,
    contact_id: int,
    current_user: User = Depends(OrgProposalsEditor),
    db: AsyncSession = Depends(get_db),
) -> dict:
    client = await _org_editor_client(db, client_id, current_user)
    await proposals.clear_skip(
        db, client_id=client.id, kind="reports_to", subject_id=contact_id
    )
    return await _client_payload(db, client.id, current_user)
