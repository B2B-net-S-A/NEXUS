"""Wypowiedzenia z poczty na karcie back office (decyzje Artura z 23.11.2026).

``/api/back-office/notices/*`` — za tą samą bramką co kolejka back office
(moduł ``back_office`` i członek zespołu albo kierownik). Odczyt propozycji
i zapis decyzji; zmiany w kontrakcie i zamówieniu robią istniejące trasy
z własnymi uprawnieniami, które karta woła przed decyzją.
"""

from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.back_office import BackOfficeMember
from app.core.database import get_db
from app.models.admin_case import AdminCase
from app.models.notice_mail import NoticeMailProposal
from app.services.admin_cases import notice_view
from app.services.admin_cases import service as cases

router = APIRouter()

NOT_FOUND = "Nie ma takiej propozycji."


class NoticeDecision(BaseModel):
    decision: Literal["confirmed", "rejected"]
    contract_id: Optional[int] = Field(default=None, ge=1)
    remember_sender: bool = False
    #: Co karta zrobiła przed decyzją (data końca, wybór przy zamówieniu) — do śladu.
    applied: dict[str, Any] = Field(default_factory=dict)
    note: Optional[str] = Field(default=None, max_length=500)


async def _proposal(
    db: AsyncSession, proposal_id: int, user: Any
) -> NoticeMailProposal:
    proposal = await db.get(NoticeMailProposal, proposal_id)
    if proposal is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND)
    case = await db.get(AdminCase, proposal.case_id)
    # Ta sama zasada co przy karcie sprawy: kto nie czyta sprawy, nie widzi maila.
    if case is None or not cases.may_read(user, case):
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND)
    return proposal


@router.get("/notices/{proposal_id}")
async def get_notice(
    proposal_id: int,
    current_user: BackOfficeMember,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    proposal = await _proposal(db, proposal_id, current_user)
    return await notice_view.proposal_detail(db, proposal)


@router.post("/notices/{proposal_id}/decision")
async def decide_notice(
    proposal_id: int,
    payload: NoticeDecision,
    current_user: BackOfficeMember,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    proposal = await _proposal(db, proposal_id, current_user)
    try:
        await notice_view.decide(
            db,
            proposal,
            actor=current_user,
            decision=payload.decision,
            contract_id=payload.contract_id,
            remember_sender=payload.remember_sender,
            applied=payload.applied,
            note=payload.note,
        )
    except notice_view.NoticeError as exc:
        raise HTTPException(
            exc.status_code, {"message": str(exc), "code": exc.code}
        ) from exc
    except cases.CaseError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    await db.commit()
    await db.refresh(proposal)
    return await notice_view.proposal_detail(db, proposal)
