"""„Szczegóły administracyjne” podpisanego kontraktu — replacement, „za kogo”
i „kandydat wskazany przez klienta” (decyzje Artura 06.11.2026).

Prefiks ``/api/hr/payroll`` (wpięty w ``app/main.py`` za przełącznikiem
programu „Ludzie”, jak reszta Płac). W Generatorze te pola wpisuje się przed
umową i kopiują się fill-only przy podpisie; tu Płace poprawiają je na
kontraktach podpisanych wcześniej, bo od nich zależą premie z placementu
(gwarancja DL, brak premii za kandydata od klienta, cel premii 200%).

* Kto: uprawnienie „Płace” albo „Umowy B2B: oznaczanie jako podpisane”;
  konto rządzone portfelem Delivery Leada tylko u swoich klientów, TCM
  u wszystkich (ten sam zakres co „Oznacz jako podpisaną”). Poza Płacami
  nikt nie zmienia kontraktu, z którego sam dostaje premię (rekruter, DL,
  dodatkowy DL, odbiorca wiersza z arkusza) — 403.
* Zmiana z obowiązkowym powodem: wpis ``admin_details_changed`` w historii
  kontraktu i ``hr_audit_events`` (``sensitivity='payroll'``).
* Po zapisie automat premii uzgadnia kontrakt od razu (bez czekania na noc).
"""

from __future__ import annotations

from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.contract_access import assert_contract_legal_client_access
from app.api.deps import require_any_permission
from app.api.hr_gates import ensure_module
from app.core.database import get_db
from app.models.activity import Activity
from app.models.contract import Contract
from app.models.hr_payroll import HrBonus
from app.models.user import User, UserRole
from app.services.access_scope import is_delivery_lead_governed
from app.services.action_permissions import ProductAction
from app.services.b2b_contract_generator import admin_details
from app.services.hr import audit, placement_bonuses
from app.services.hr.bonus_rules import load_rules
from app.services.hr.modules import HrModule
from app.services.hr.payroll_access import is_payroll

router = APIRouter()

ACTIVITY_ACTION = "admin_details_changed"


def require_contract_admin_editor():
    """Płace albo oznaczanie podpisu umów B2B (zakres klientów w handlerze)."""

    async def _check(
        current_user: User = Depends(
            require_any_permission(
                ProductAction.payroll, ProductAction.b2b_signature_confirmation
            )
        ),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        await ensure_module(db, current_user, HrModule.payroll)
        return current_user

    return _check


ContractAdminEditor = Annotated[User, Depends(require_contract_admin_editor())]


class ContractAdminDetailsIn(BaseModel):
    """Komplet trzech pól (PUT) i powód zmiany."""

    is_replacement: Optional[bool] = None
    replaced_contract_id: Optional[int] = Field(None, ge=1, le=2_147_483_647)
    is_client_referral: Optional[bool] = None
    reason: str = Field(max_length=500)

    @field_validator("reason")
    @classmethod
    def _reason_given(cls, v: str) -> str:
        cleaned = v.strip()
        if len(cleaned) < 3:
            raise ValueError("Podaj powód zmiany (co najmniej 3 znaki).")
        return cleaned


async def _load_contract(
    db: AsyncSession, user: User, contract_id: int, *, for_update: bool
) -> Contract:
    stmt = select(Contract).where(Contract.id == contract_id)
    if for_update:
        stmt = stmt.with_for_update()
    contract = await db.scalar(stmt)
    if contract is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie ma takiego kontraktu.")
    # Płace i TCM działają u wszystkich klientów; Delivery Lead u swoich.
    if (
        not is_payroll(user)
        and not user.has_role(UserRole.talent_community_manager)
        and is_delivery_lead_governed(user)
    ):
        await assert_contract_legal_client_access(
            db, user, contract.client_id, write=for_update, purpose="org"
        )
    if (
        for_update
        and not is_payroll(user)
        and user.id in await _bonus_people(db, contract)
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, OWN_BONUS_DETAIL)
    return contract


OWN_BONUS_DETAIL = (
    "Od tych pól zależy Twoja premia z tego kontraktu — zmianę wprowadzają Płace."
)


async def _bonus_people(db: AsyncSession, contract: Contract) -> set[int]:
    """Odbiorcy premii z placementu tego kontraktu: z reguły automatu
    (rekruter, DL, dodatkowy DL) i z każdego wiersza premii (też z arkusza)."""

    rules = await load_rules(db)
    dl_id, recruiter_id, _source = (
        await placement_bonuses.load_context(db, [contract])
    ).people(contract)
    people = {pid for pid in (dl_id, recruiter_id) if pid is not None}
    people |= {
        rule.recipient_user_id for rule in rules.extra_dl if rule.dl_user_id == dl_id
    }
    people |= set(
        await db.scalars(
            select(HrBonus.recipient_user_id).where(
                HrBonus.source == placement_bonuses.SOURCE,
                HrBonus.contract_id == contract.id,
            )
        )
    )
    return people


async def _payload(db: AsyncSession, contract: Contract) -> dict[str, Any]:
    replaced = None
    if contract.replaced_contract_id is not None:
        found = await admin_details.replaceable_contracts(
            db, contract_ids=[contract.replaced_contract_id], limit=1
        )
        replaced = admin_details.replaceable_payload(found[0]) if found else None
    return {
        "contract_id": contract.id,
        "candidate_id": contract.candidate_id,
        "client_id": contract.client_id,
        "is_replacement": contract.is_replacement,
        "replaced_contract_id": contract.replaced_contract_id,
        "replaced": replaced,
        "is_client_referral": contract.is_client_referral,
    }


@router.get("/contracts/{contract_id}/admin-details")
async def get_contract_admin_details(
    contract_id: int,
    current_user: ContractAdminEditor,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    contract = await _load_contract(db, current_user, contract_id, for_update=False)
    return await _payload(db, contract)


@router.put("/contracts/{contract_id}/admin-details")
async def put_contract_admin_details(
    contract_id: int,
    payload: ContractAdminDetailsIn,
    current_user: ContractAdminEditor,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    contract = await _load_contract(db, current_user, contract_id, for_update=True)
    changed = await admin_details.update_contract_admin_details(
        db,
        contract,
        is_replacement=payload.is_replacement,
        replaced_contract_id=payload.replaced_contract_id,
        is_client_referral=payload.is_client_referral,
    )
    bonuses: dict[str, Any] = {}
    if changed:
        # Płasko: oś czasu kontraktu pokazuje każde pole jako „przed → po”.
        details = {**changed, "reason": payload.reason}
        db.add(
            Activity(
                entity_type="contract",
                entity_id=contract.id,
                action=ACTIVITY_ACTION,
                user_id=current_user.id,
                details=details,
            )
        )
        audit.record(
            db,
            actor_user_id=current_user.id,
            subject_user_id=None,
            entity_type="contract",
            entity_id=contract.id,
            action=ACTIVITY_ACTION,
            sensitivity="payroll",
            details=details,
        )
        await db.flush()
        # Gwarancja DL i „kandydat od klienta” działają od razu, nie w nocy.
        bonuses = await placement_bonuses.on_admin_details_changed(db, contract)
    return {
        **(await _payload(db, contract)),
        "changed": sorted(changed),
        "bonuses": bonuses,
    }
