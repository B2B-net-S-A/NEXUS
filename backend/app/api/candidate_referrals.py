"""Polecenia inżynierów ze strony B2B Network (0806, decyzje Artura 28.11.2026).

Prefiks ``/api/candidate-referrals``. Polecenie przychodzi z formularza
„Poleć inżyniera” (``services/website_referrals``) razem z kandydatem i wpisem
w kolejce „Zgłoszenia”. Tu rekruter prowadzi je dalej:

* ``GET  /api/candidate-referrals`` — lista (sekcja Sourcing, jak kolejka),
* ``PATCH /api/candidate-referrals/{id}`` — status (nowe → rozmowa → zaczął
  projekt / odrzucone), kwota premii 1–5 tys. zł, notatka,
* ``POST /api/candidate-referrals/{id}/paid`` — „Wypłacona”, tylko moduł Finanse
  (osobny router za sekcją Finanse): to wypłata pieniędzy, nie praca rekrutera.

Dane polecającego i polecanego to dane osobowe z formularza publicznego,
dlatego lista ma tę samą bramkę co kolejka zgłoszeń (``CandidateWriteAccess``,
bez roli „Automatyzacje”).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.candidate_access import CandidateWriteAccess
from app.api.deps import FinanceModuleUser
from app.api.section_access import (
    FINANCE_SECTION_DEPENDENCIES,
    SOURCING_SECTION_DEPENDENCIES,
)
from app.core.database import get_db
from app.models.activity import Activity
from app.models.website_intake import CandidateReferral
from app.services import website_referrals as referrals
from app.services.website_intake_schema import NOTE_MAX

router = APIRouter(dependencies=SOURCING_SECTION_DEPENDENCIES)
finance_router = APIRouter(dependencies=FINANCE_SECTION_DEPENDENCIES)

ReferralStatus = Literal["new", "contacted", "started", "paid", "rejected"]
RecruiterStatus = Literal["new", "contacted", "started", "rejected"]


class ReferralUpdate(BaseModel):
    status: Optional[RecruiterStatus] = None
    bonus_amount: Optional[Decimal] = Field(
        default=None, max_digits=10, decimal_places=2
    )
    note: Optional[str] = Field(default=None, max_length=NOTE_MAX)


def _activity(
    row: CandidateReferral, *, action: str, user_id: int
) -> Optional[Activity]:
    if row.candidate_id is None:
        return None
    return Activity(
        entity_type="candidate",
        entity_id=row.candidate_id,
        action=action,
        user_id=user_id,
        details={"referral_id": row.id, "status": row.status},
    )


def _http(exc: referrals.ReferralChangeError) -> HTTPException:
    return HTTPException(exc.status_code, exc.message)


@router.get("")
async def list_candidate_referrals(
    current_user: CandidateWriteAccess,
    db: AsyncSession = Depends(get_db),
    status_filter: Optional[ReferralStatus] = Query(default=None, alias="status"),
) -> dict:
    return {"referrals": await referrals.list_referrals(db, status=status_filter)}


@router.patch("/{referral_id}")
async def update_candidate_referral(
    referral_id: int,
    body: ReferralUpdate,
    current_user: CandidateWriteAccess,
    db: AsyncSession = Depends(get_db),
) -> dict:
    changes = body.model_dump(exclude_unset=True)
    if "note" in changes and changes["note"] is not None:
        changes["note"] = changes["note"].strip()
    try:
        row = await referrals.update_referral(
            db, referral_id, changes=changes, actor_user_id=current_user.id
        )
    except referrals.ReferralChangeError as exc:
        raise _http(exc) from exc
    activity = _activity(row, action="referral_updated", user_id=current_user.id)
    if activity is not None:
        db.add(activity)
    await db.commit()
    return {"referral": referrals.serialize(row)}


@finance_router.post("/{referral_id}/paid")
async def mark_candidate_referral_paid(
    referral_id: int,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        row = await referrals.mark_paid(db, referral_id, actor_user_id=current_user.id)
    except referrals.ReferralChangeError as exc:
        raise _http(exc) from exc
    activity = _activity(row, action="referral_paid", user_id=current_user.id)
    if activity is not None:
        db.add(activity)
    await db.commit()
    return {"referral": referrals.serialize(row)}
