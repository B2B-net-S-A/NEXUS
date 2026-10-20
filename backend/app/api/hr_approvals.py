"""Zgody na wydatki i premie poza umową (0483, decyzja Artura 20.10.2026).

Prefiks ``/api/hr/approval-requests`` (``app/main.py``, za wyłącznikiem
programu). Bramka ``require_hr_approvals`` — moduł „Zgody” włączony (admin
widzi go zawsze); kto co widzi i o czym decyduje, rozstrzyga serwis
(``services/hr/approvals/service.py``):

* ``GET ""?scope=inbox|mine|decided`` — skrzynka „Do decyzji”, „Moje zgody”,
  historia decyzji,
* ``GET /count`` — liczba zgód czekających na decyzję czytającego,
* ``GET /beneficiaries`` — osoby, dla których czytający może prosić o premię,
* ``POST /preview`` — kto zdecyduje (formularz, bez zapisu),
* ``POST ""`` — wyślij, ``PUT /{id}`` — popraw i wyślij znowu,
  ``POST /{id}/withdraw`` — wycofaj,
* ``GET /{id}`` — szczegół z kontekstem dla decydującego,
* ``POST /{id}/decide`` — „Zatwierdź” / „Odrzuć” / „Dopytaj”,
* ``GET /rules``, ``PUT /rules`` — zasady (admin).
"""

from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Iterator, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.hr_gates import (
    NO_PROFILE_DETAIL,
    require_hr_approvals,
    require_hr_approvals_admin,
)
from app.core.database import get_db
from app.core.scheduling import business_today
from app.models.hr_approval import ApprovalRequest
from app.models.hr_profile import EmployeeProfile
from app.models.user import User, UserRole
from app.services.hr import payroll_access, people
from app.services.hr.approvals import rules as approval_rules
from app.services.hr.approvals import service
from app.services.hr.approvals.payload import names_for, request_payload

router = APIRouter()

ApprovalsUser = Annotated[User, Depends(require_hr_approvals())]
ApprovalsAdmin = Annotated[User, Depends(require_hr_approvals_admin())]


@contextmanager
def _http_errors() -> Iterator[None]:
    try:
        yield
    except service.ApprovalError as exc:
        raise HTTPException(exc.status_code, exc.message) from exc


class RequestIn(BaseModel):
    kind: Literal["bonus", "subscription", "trip", "gift", "training", "other"]
    title: str = Field(max_length=400)
    purpose: str = Field(max_length=4000)
    amount: Decimal
    currency: str = Field(default="PLN", max_length=3)
    amount_basis: Literal["gross", "net"] = "gross"
    recurrence: Literal["once", "monthly", "yearly"] = "once"
    payer: Optional[Literal["company_invoice", "company_card", "reimbursement"]] = None
    link_url: Optional[str] = Field(default=None, max_length=1000)
    needed_by: Optional[date] = None
    starts_on: Optional[date] = None
    ends_on: Optional[date] = None
    beneficiary_user_id: Optional[int] = Field(default=None, ge=1)
    payout_year: Optional[int] = Field(default=None, ge=2020, le=2100)
    payout_month: Optional[int] = Field(default=None, ge=1, le=12)

    def to_input(self) -> service.RequestInput:
        return service.RequestInput(**self.model_dump())


class DecisionIn(BaseModel):
    action: Literal["approve", "reject", "return"]
    amount: Optional[Decimal] = None
    note: Optional[str] = Field(default=None, max_length=2000)


class RulesIn(BaseModel):
    final_approver_user_id: Optional[int] = Field(default=None, ge=1)
    supervisor_limits: dict[str, Optional[int]] = Field(default_factory=dict)


async def _require_requester(db: AsyncSession, user: User) -> None:
    """Prosić może osoba z kartoteką albo admin (zarząd bez kartoteki)."""

    if user.has_role(UserRole.admin):
        return
    if not await people.has_live_profile(db, user.id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, NO_PROFILE_DETAIL)


async def _payloads(
    db: AsyncSession, requests: list[ApprovalRequest], viewer: User
) -> list[dict[str, Any]]:
    rules = await approval_rules.load_rules(db)
    finals_all = await approval_rules.final_approver_ids(db, rules)
    names = await names_for(db, requests, tuple(finals_all))
    out = []
    for request in requests:
        finals = await service.finals_for_request(db, request)
        missing = [uid for uid in finals if uid not in names]
        if missing:
            names.update(await names_for(db, [], tuple(missing)))
        out.append(request_payload(request, names, viewer=viewer, finals=finals))
    return out


@router.get("")
async def list_requests(
    current_user: ApprovalsUser,
    db: AsyncSession = Depends(get_db),
    scope: Literal["inbox", "mine", "decided"] = Query(default="inbox"),
) -> dict[str, Any]:
    if scope == "inbox":
        rows = await service.inbox(db, current_user)
    elif scope == "mine":
        rows = await service.mine(db, current_user)
    else:
        rows = await service.history(db, current_user)
    return {"items": await _payloads(db, rows, current_user)}


@router.get("/count")
async def inbox_count(
    current_user: ApprovalsUser, db: AsyncSession = Depends(get_db)
) -> dict[str, int]:
    return {"inbox": await service.pending_count(db, current_user)}


@router.get("/beneficiaries")
async def beneficiaries(
    current_user: ApprovalsUser, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Osoby z kartoteką, dla których czytający prosi o premię (Płace: wszyscy,
    przełożony: bezpośredni podwładni) — nigdy on sam."""

    viewer = await payroll_access.load_viewer(db, current_user)
    stmt = (
        select(User.id, User.name)
        .join(EmployeeProfile, EmployeeProfile.user_id == User.id)
        .where(
            EmployeeProfile.employment_status != "exited",
            User.id != current_user.id,
        )
        .order_by(User.name)
    )
    if not viewer.payroll:
        if not viewer.report_ids:
            return {"items": []}
        stmt = stmt.where(User.id.in_(viewer.report_ids))
    rows = await db.execute(stmt)
    return {"items": [{"user_id": uid, "name": name} for uid, name in rows.all()]}


@router.post("/preview")
async def preview_route(
    payload: RequestIn, current_user: ApprovalsUser, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """„Kto zdecyduje” w formularzu — ta sama droga co przy wysłaniu, bez zapisu."""

    with _http_errors():
        data = service.clean_input(payload.to_input(), today=business_today())
        rules = await approval_rules.load_rules(db)
        parties = {current_user.id}
        if data.beneficiary_user_id:
            parties.add(data.beneficiary_user_id)
        finals = [
            uid
            for uid in await approval_rules.final_approver_ids(db, rules)
            if uid not in parties
        ]
        planned = await service.route(
            db, data, requester_id=current_user.id, rules=rules, finals=finals
        )
    ids = tuple(uid for uid in (planned.supervisor_user_id, *finals) if uid is not None)
    names = await names_for(db, [], ids)
    return {
        "supervisor_name": names.get(planned.supervisor_user_id)
        if planned.supervisor_user_id
        else None,
        "supervisor_decides_alone": planned.supervisor_user_id is not None
        and not planned.needs_final,
        "final_approver_names": [names[uid] for uid in finals if uid in names],
        "supervisor_limit": rules.limit_for(data.kind),
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def submit_request(
    payload: RequestIn, current_user: ApprovalsUser, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await _require_requester(db, current_user)
    with _http_errors():
        request = await service.submit(
            db, current_user, payload.to_input(), today=business_today()
        )
    (out,) = await _payloads(db, [request], current_user)
    return out


@router.get("/rules")
async def get_rules(
    current_user: ApprovalsAdmin, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    rules = await approval_rules.load_rules(db)
    finals = await approval_rules.final_approver_ids(db, rules)
    names = await names_for(db, [], tuple(finals))
    return {
        **rules.as_dict(),
        "defaults": approval_rules.DEFAULT_LIMITS,
        "effective_final_approver_names": [
            names[uid] for uid in finals if uid in names
        ],
    }


@router.put("/rules")
async def put_rules(
    payload: RulesIn, current_user: ApprovalsAdmin, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    try:
        rules = approval_rules.parse_update(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    if rules.final_approver_user_id is not None:
        approver = await db.get(User, rules.final_approver_user_id)
        if approver is None or not approver.is_active:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Zatwierdzający musi mieć aktywne konto.",
            )
    await approval_rules.save_rules(db, rules, actor=current_user)
    return await get_rules(current_user, db)


@router.get("/{request_id}")
async def get_request(
    request_id: int, current_user: ApprovalsUser, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    with _http_errors():
        request = await service.get_visible(db, current_user, request_id)
    (out,) = await _payloads(db, [request], current_user)
    finals = await service.finals_for_request(db, request)
    deciding = (
        service.can_decide(current_user.id, request, finals)
        or current_user.id in finals
        or current_user.has_role(UserRole.admin)
    )
    out["context"] = (
        await service.context_for(db, request, today=business_today())
        if deciding
        else None
    )
    return out


@router.put("/{request_id}")
async def resubmit_request(
    request_id: int,
    payload: RequestIn,
    current_user: ApprovalsUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    with _http_errors():
        request = await service.resubmit(
            db, current_user, request_id, payload.to_input(), today=business_today()
        )
    (out,) = await _payloads(db, [request], current_user)
    return out


@router.post("/{request_id}/withdraw")
async def withdraw_request(
    request_id: int, current_user: ApprovalsUser, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    with _http_errors():
        request = await service.withdraw(db, current_user, request_id)
    (out,) = await _payloads(db, [request], current_user)
    return out


@router.post("/{request_id}/decide")
async def decide_request(
    request_id: int,
    payload: DecisionIn,
    current_user: ApprovalsUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    with _http_errors():
        request = await service.decide(
            db,
            current_user,
            request_id,
            action=payload.action,
            amount=payload.amount,
            note=payload.note,
        )
    (out,) = await _payloads(db, [request], current_user)
    return out
