"""Router zmian stawki kandydata w trakcie procesu — `/api/rate-changes` (0418).

* ``GET /api/rate-changes?candidate_id&job_id`` — bieżąca stawka pary, kolumna
  Tablicy (czy zmiana powiadomi DL i HoR, czy CV jest już u klienta) i sprawy
  zmian. Stawka do klienta tylko dla ról, które ją widzą.
* ``POST /api/rate-changes`` — nowa stawka kandydata w tej rekrutacji
  z powodem i notatką; reguła w ``services/candidate_rate_change.py``.

Dostęp: sekcja Pipeline. Odczyt jak rekrutacja, zapis jak korekta stawki
kandydata (``RecruitmentRateEditAccess`` + członkostwo — każda rola wewnętrzna).
"""

import logging
from datetime import datetime
from decimal import Decimal
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.candidate_access import user_can_view_client_rate
from app.api.recruitment_access import (
    RecruitmentRateEditAccess,
    RecruitmentReadAccess,
    ensure_job_membership,
    ensure_job_read_access,
)
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.models.candidate_rate_change import CandidateRateChange
from app.models.contract import RateUnit
from app.models.recruitment_pipeline import CandidateStage
from app.models.user import User
from app.services import candidate_rate_change as rate_change

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=PIPELINE_SECTION_DEPENDENCIES)

ReasonCode = Literal["conversation", "email", "typo", "other"]
NegotiableCode = Literal["no", "maybe", "unknown"]


class RateValue(BaseModel):
    amount: Decimal
    unit: Optional[str] = None
    currency: str = "PLN"
    hourly: Optional[Decimal] = None
    label: str


class RateChangeOut(BaseModel):
    id: int
    status: str
    requires_decision: bool
    board_column: Optional[str] = None
    previous: Optional[RateValue] = None
    requested: RateValue
    agreed: Optional[RateValue] = None
    source: str
    source_label: str
    reason: str
    reason_label: str
    note: Optional[str] = None
    negotiable: Optional[str] = None
    created_at: datetime
    created_by_name: Optional[str] = None
    negotiator_id: Optional[int] = None
    negotiator_name: Optional[str] = None
    negotiation_target_hourly: Optional[Decimal] = None
    negotiation_due: Optional[str] = None
    outcome: Optional[str] = None
    outcome_note: Optional[str] = None
    decision: Optional[str] = None
    decided_at: Optional[datetime] = None
    decided_by_name: Optional[str] = None


class RateChangesView(BaseModel):
    candidate_id: int
    job_id: int
    current: Optional[RateValue] = None
    board_column: Optional[str] = None
    # Zmiana od „Zweryfikowany” powiadomi DL i Head of Recruitment.
    notifies: bool
    # CV jest już u klienta — wzrost stawki to zadanie DL.
    cv_at_client: bool
    client_rate: Optional[RateValue] = None
    changes: list[RateChangeOut]


class RateChangeCreate(BaseModel):
    candidate_id: int = Field(gt=0)
    job_id: int = Field(gt=0)
    amount: Decimal = Field(gt=0, le=Decimal("1000000"))
    unit: RateUnit = RateUnit.hourly
    currency: str = Field("PLN", min_length=3, max_length=3)
    reason: ReasonCode = "conversation"
    note: Optional[str] = Field(None, max_length=1000)
    negotiable: Optional[NegotiableCode] = None


class RateChangeCreated(BaseModel):
    unchanged: bool
    change: Optional[RateChangeOut] = None


def _rate(
    amount: object, unit: Optional[str], currency: Optional[str]
) -> Optional[RateValue]:
    if amount is None:
        return None
    return RateValue(
        amount=Decimal(str(amount)),
        unit=unit,
        currency=(currency or "PLN").upper(),
        hourly=rate_change._hourly(amount, unit, currency),
        label=rate_change.format_rate(Decimal(str(amount)), unit, currency),
    )


async def _names(db: AsyncSession, ids: set[int]) -> dict[int, str]:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    rows = await db.execute(select(User.id, User.name).where(User.id.in_(ids)))
    return {uid: name for uid, name in rows.all()}


def _out(c: CandidateRateChange, names: dict[int, str]) -> RateChangeOut:
    return RateChangeOut(
        id=c.id,
        status=c.status,
        requires_decision=c.requires_decision,
        board_column=c.board_column,
        previous=_rate(c.previous_amount, c.previous_unit, c.previous_currency),
        requested=_rate(c.requested_amount, c.requested_unit, c.requested_currency),
        agreed=_rate(c.agreed_amount, c.agreed_unit, c.agreed_currency),
        source=c.source,
        source_label=rate_change.SOURCE_LABELS.get(c.source, c.source),
        reason=c.reason,
        reason_label=rate_change.REASON_LABELS.get(c.reason, c.reason),
        note=c.note,
        negotiable=c.negotiable,
        created_at=c.created_at,
        created_by_name=names.get(c.created_by or 0),
        negotiator_id=c.negotiator_id,
        negotiator_name=names.get(c.negotiator_id or 0),
        negotiation_target_hourly=c.negotiation_target_hourly,
        negotiation_due=c.negotiation_due.isoformat() if c.negotiation_due else None,
        outcome=c.outcome,
        outcome_note=c.outcome_note,
        decision=c.decision,
        decided_at=c.decided_at,
        decided_by_name=names.get(c.decided_by or 0),
    )


async def outs_for(
    db: AsyncSession, changes: list[CandidateRateChange]
) -> list[RateChangeOut]:
    ids: set[int] = set()
    for c in changes:
        ids.update(x for x in (c.created_by, c.negotiator_id, c.decided_by) if x)
    names = await _names(db, ids)
    return [_out(c, names) for c in changes]


@router.get("/rate-changes", response_model=RateChangesView)
async def get_rate_changes(
    current_user: RecruitmentReadAccess,
    candidate_id: int = Query(gt=0, le=2_147_483_647),
    job_id: int = Query(gt=0, le=2_147_483_647),
    db: AsyncSession = Depends(get_db),
) -> RateChangesView:
    await ensure_job_read_access(db, current_user, job_id)
    rates = await rate_change.pair_rates(db, candidate_id=candidate_id, job_id=job_id)
    latest = await db.scalar(
        select(CandidateStage)
        .where(
            CandidateStage.candidate_id == candidate_id,
            CandidateStage.job_id == job_id,
        )
        .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
        .limit(1)
    )
    column = await rate_change._stage_column(db, latest) if latest else None
    changes = list(
        (
            await db.scalars(
                select(CandidateRateChange)
                .where(
                    CandidateRateChange.candidate_id == candidate_id,
                    CandidateRateChange.job_id == job_id,
                )
                .order_by(
                    CandidateRateChange.created_at.desc(), CandidateRateChange.id.desc()
                )
                .limit(20)
            )
        ).all()
    )
    show_client = user_can_view_client_rate(current_user)
    return RateChangesView(
        candidate_id=candidate_id,
        job_id=job_id,
        current=_rate(rates["amount"], rates["unit"], rates["currency"]),
        board_column=column,
        notifies=column in rate_change.NOTIFY_COLUMNS,
        cv_at_client=column in rate_change.DECISION_COLUMNS,
        client_rate=(
            _rate(
                rates["client_amount"], rates["client_unit"], rates["client_currency"]
            )
            if show_client
            else None
        ),
        changes=await outs_for(db, changes),
    )


@router.post("/rate-changes", response_model=RateChangeCreated)
async def create_rate_change(
    body: RateChangeCreate,
    current_user: RecruitmentRateEditAccess,
    db: AsyncSession = Depends(get_db),
) -> RateChangeCreated:
    await ensure_job_membership(db, current_user, body.job_id)
    result = await rate_change.change_rate(
        db,
        candidate_id=body.candidate_id,
        job_id=body.job_id,
        amount=body.amount,
        unit=body.unit.value,
        currency=body.currency,
        source="manual",
        reason=body.reason,
        note=body.note,
        negotiable=body.negotiable,
        actor=current_user,
    )
    change = result.change
    await db.commit()
    await rate_change.send_pending_emails(result.emails)
    if change is None:
        return RateChangeCreated(unchanged=True)
    await db.refresh(change)
    return RateChangeCreated(unchanged=False, change=(await outs_for(db, [change]))[0])
