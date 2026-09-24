"""Przepięcie kontraktu na innego klienta — podgląd i wykonanie (tylko admin).

``GET  /api/contracts/{id}/client-reassign-preview?client_id=`` — plan z odciskiem.
``POST /api/contracts/{id}/client-reassign`` — ``{client_id, fingerprint}``.

Logika i powody: ``app.services.contract_client_reassign``. ``ContractUpdate``
świadomie nie ma ``client_id`` — to jest JEDYNA droga zmiany klienta kontraktu.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminUser
from app.api.section_access import DELIVERY_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.models.contract import Contract
from app.services import critical_events
from app.services.contract_client_reassign import (
    BLOCKER_OFFBOARDING_PENDING,
    BLOCKER_ORDER_EXECUTIVE,
    BLOCKER_ORDER_FRAMEWORK,
    BLOCKER_ORDER_GROUP_LINE,
    BLOCKER_ORDER_OTHER_CLIENT,
    BLOCKER_PM_CONTACT,
    EVENT_TYPE,
    FingerprintMismatch,
    ReassignBlocked,
    ReassignError,
    ReassignPlan,
    build_plan,
    execute_reassign,
)

router = APIRouter(dependencies=DELIVERY_SECTION_DEPENDENCIES)

_BLOCKER_AUDIT_LABELS: dict[str, str] = {
    BLOCKER_ORDER_FRAMEWORK: "zamówienie pod umową ramową starego klienta",
    BLOCKER_ORDER_EXECUTIVE: "zamówienie pod umową wykonawczą starego klienta",
    BLOCKER_ORDER_GROUP_LINE: "linia zamówienia MD / kosztowego",
    BLOCKER_ORDER_OTHER_CLIENT: "zamówienie u jeszcze innego klienta",
    BLOCKER_PM_CONTACT: "PM klienta z innej firmy",
    BLOCKER_OFFBOARDING_PENDING: "czeka decyzja po zakończeniu współpracy",
}


class ClientReassignRequest(BaseModel):
    client_id: int = Field(..., gt=0)
    fingerprint: str = Field(..., min_length=64, max_length=64)


def _error(exc: ReassignError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": exc.message},
    )


def _audit_details(plan: ReassignPlan) -> dict[str, Any]:
    """Szczegóły wpisu Historii zdarzeń — same numery i nazwy firm, bez osób."""

    return {
        "from_client_id": plan.from_client["id"],
        "from_client_name": plan.from_client["name"],
        "to_client_id": plan.to_client["id"],
        "to_client_name": plan.to_client["name"],
        "moved_orders": len(
            [o for o in plan.orders if o["client_id"] == plan.from_client["id"]]
        ),
        "moved_b2b_documents": len(plan.b2b_documents),
        "moved_open_gaps": len(plan.open_gaps),
        "closed_dl_alerts": len(plan.alerts),
        "blocker_codes": [b["code"] for b in plan.blockers],
    }


@router.get("/{contract_id}/client-reassign-preview")
async def client_reassign_preview(
    contract_id: int,
    current_user: AdminUser,
    client_id: int = Query(..., gt=0),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Co zostanie przeniesione i co blokuje przepięcie. Niczego nie zapisuje."""

    contract = await db.get(Contract, contract_id)
    if contract is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "contract_not_found",
                "message": "Nie znaleziono kontraktu.",
            },
        )
    try:
        plan = await build_plan(db, contract, client_id)
    except ReassignError as exc:
        raise _error(exc) from exc
    return plan.as_dict()


@router.post("/{contract_id}/client-reassign")
async def client_reassign(
    contract_id: int,
    body: ClientReassignRequest,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Przepnij kontrakt (i to, co z nim związane) na klienta ``client_id``."""

    label = f"Kontrakt #{contract_id}"
    try:
        plan = await execute_reassign(
            db,
            contract_id=contract_id,
            target_client_id=body.client_id,
            fingerprint=body.fingerprint,
            user_id=current_user.id,
        )
    except ReassignError as exc:
        raise _error(exc) from exc
    except FingerprintMismatch as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "fingerprint_mismatch",
                "message": (
                    "Od podglądu coś się zmieniło (zamówienia, umowy albo alerty "
                    "tego kontraktu). Sprawdź podgląd jeszcze raz."
                ),
                "plan": exc.plan.as_dict(),
            },
        ) from exc
    except ReassignBlocked as exc:
        await critical_events.record_blocked(
            actor=current_user,
            event_type=EVENT_TYPE,
            entity_type="contract",
            entity_id=contract_id,
            entity_label=label,
            client_id=exc.plan.from_client["id"],
            client_name=exc.plan.from_client["name"],
            reason_code="blocked",
            # Kody, nie komunikaty: komunikaty cytują tytuły zamówień, a te
            # bywają „Imię Nazwisko — rekrutacja” (Historia bez nazwisk osób).
            reason=", ".join(
                _BLOCKER_AUDIT_LABELS.get(b["code"], b["code"])
                for b in exc.plan.blockers
            ),
            details=_audit_details(exc.plan),
        )
        raise HTTPException(
            status_code=409,
            detail={
                "code": "contract_client_reassign_blocked",
                "message": "Przepięcie kontraktu jest zablokowane.",
                "blockers": exc.plan.blockers,
                "plan": exc.plan.as_dict(),
            },
        ) from exc

    await critical_events.record_executed(
        db,
        actor=current_user,
        event_type=EVENT_TYPE,
        entity_type="contract",
        entity_id=contract_id,
        entity_label=label,
        client_id=plan.to_client["id"],
        client_name=plan.to_client["name"],
        reason=(
            f"Przepięto z klienta „{plan.from_client['name']}” "
            f"na „{plan.to_client['name']}”."
        ),
        details=_audit_details(plan),
    )
    await db.commit()
    return plan.as_dict()
