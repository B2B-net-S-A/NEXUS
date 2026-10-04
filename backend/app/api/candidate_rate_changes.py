"""Router zmian stawki kandydata w trakcie procesu — `/api/rate-changes` (0418).

* ``GET /api/rate-changes?candidate_id&job_id`` — bieżąca stawka pary, kolumna
  Tablicy (czy zmiana powiadomi DL i HoR, czy CV jest już u klienta) i sprawy
  zmian. Stawka do klienta tylko dla ról, które ją widzą.
* ``POST /api/rate-changes`` — nowa stawka kandydata w tej rekrutacji
  z powodem i notatką; reguła w ``services/candidate_rate_change.py``.
* ``POST /api/rate-changes/{id}/negotiation`` — DL albo Head of Recruitment
  zleca rozmowę z kandydatem (kto, cel, termin).
* ``POST /api/rate-changes/{id}/outcome`` — wynik negocjacji (niższa stawka,
  kandydat nie ustąpił, rezygnuje).
* ``POST /api/rate-changes/{id}/decision`` — Delivery Lead (albo admin)
  decyduje o stawce do klienta: podnosi ją, zostawia albo wycofuje kandydata.

Dostęp: sekcja Pipeline. Odczyt jak rekrutacja, zapis jak korekta stawki
kandydata (``RecruitmentRateEditAccess`` + członkostwo — każda rola wewnętrzna).
"""

import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Path, Query
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
from app.models.job import Job
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
    # Czy oglądający może zapisać wynik negocjacji tej sprawy.
    can_record_outcome: bool = False


class NegotiatorOption(BaseModel):
    id: int
    name: str
    role_label: str


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
    # Zlecenie negocjacji: DL rekrutacji, Head of Recruitment, admin.
    can_manage: bool = False
    # Decyzja o stawce do klienta: DL rekrutacji albo admin.
    can_decide: bool = False
    negotiator_options: list[NegotiatorOption] = []


class RateChangeCreate(BaseModel):
    candidate_id: int = Field(gt=0)
    job_id: int = Field(gt=0)
    amount: Decimal = Field(gt=0, le=Decimal("1000000"))
    unit: RateUnit = RateUnit.hourly
    currency: str = Field("PLN", min_length=3, max_length=3)
    reason: ReasonCode = "conversation"
    note: Optional[str] = Field(None, max_length=1000)
    negotiable: Optional[NegotiableCode] = None


class NegotiationStart(BaseModel):
    negotiator_id: int = Field(gt=0, le=2_147_483_647)
    target_hourly: Optional[Decimal] = Field(None, gt=0, le=Decimal("100000"))
    due: Optional[date] = None


class OutcomeIn(BaseModel):
    outcome: Literal["lower", "kept", "withdrew"]
    agreed_amount: Optional[Decimal] = Field(None, gt=0, le=Decimal("100000"))
    note: Optional[str] = Field(None, max_length=1000)


class ClientRateIn(BaseModel):
    amount: Decimal = Field(gt=0, le=Decimal("1000000"))
    unit: RateUnit = RateUnit.hourly
    currency: str = Field("PLN", min_length=3, max_length=3)


class DecisionIn(BaseModel):
    decision: Literal["raise_client", "keep_client", "withdraw"]
    client_rate: Optional[ClientRateIn] = None


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


def _out(
    c: CandidateRateChange, names: dict[int, str], *, can_record: bool = False
) -> RateChangeOut:
    return RateChangeOut(
        can_record_outcome=can_record and c.status in ("requested", "negotiating"),
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
    db: AsyncSession,
    changes: list[CandidateRateChange],
    *,
    viewer: Optional[User] = None,
    viewer_manages: bool = False,
) -> list[RateChangeOut]:
    ids: set[int] = set()
    for c in changes:
        ids.update(x for x in (c.created_by, c.negotiator_id, c.decided_by) if x)
    names = await _names(db, ids)
    return [
        _out(
            c,
            names,
            can_record=viewer_manages
            or (viewer is not None and c.negotiator_id == viewer.id),
        )
        for c in changes
    ]


async def _negotiator_options(
    db: AsyncSession, *, job: Job, candidate_id: int
) -> list[NegotiatorOption]:
    from app.services.notification_triggers import _hor_user_ids
    from app.services.stage_handoff_recipients import pair_recruiter_id

    options: list[tuple[int, str]] = [
        (uid, "Delivery Lead") for uid in await rate_change.job_delivery_leads(db, job)
    ]
    options += [(uid, "Head of Recruitment") for uid in await _hor_user_ids(db)]
    recruiter = await pair_recruiter_id(db, candidate_id=candidate_id, job_id=job.id)
    if recruiter is not None:
        options.append((recruiter, "Rekruter kandydata"))
    seen: set[int] = set()
    unique = [
        (uid, label) for uid, label in options if not (uid in seen or seen.add(uid))
    ]
    names = await _names(db, {uid for uid, _ in unique})
    return [
        NegotiatorOption(id=uid, name=names[uid], role_label=label)
        for uid, label in unique
        if uid in names
    ]


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
    job = await db.get(Job, job_id)
    manages = bool(job) and await rate_change.can_manage(db, current_user, job)
    decides = bool(job) and await rate_change.can_decide(db, current_user, job)
    return RateChangesView(
        can_manage=manages,
        can_decide=decides,
        negotiator_options=(
            await _negotiator_options(db, job=job, candidate_id=candidate_id)
            if manages and job is not None
            else []
        ),
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
        changes=await outs_for(
            db, changes, viewer=current_user, viewer_manages=manages
        ),
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


async def _finish(
    db: AsyncSession, result: rate_change.RateChangeResult, current_user: User
) -> RateChangeOut:
    change = result.change
    await db.commit()
    await rate_change.send_pending_emails(result.emails)
    await db.refresh(change)
    job = await db.get(Job, change.job_id)
    manages = bool(job) and await rate_change.can_manage(db, current_user, job)
    return (await outs_for(db, [change], viewer=current_user, viewer_manages=manages))[
        0
    ]


@router.post("/rate-changes/{change_id}/negotiation", response_model=RateChangeOut)
async def start_negotiation(
    body: NegotiationStart,
    current_user: RecruitmentRateEditAccess,
    change_id: int = Path(gt=0, le=2_147_483_647),
    db: AsyncSession = Depends(get_db),
) -> RateChangeOut:
    change = await rate_change.lock_change(db, change_id)
    await ensure_job_read_access(db, current_user, change.job_id)
    result = await rate_change.start_negotiation(
        db,
        change=change,
        negotiator_id=body.negotiator_id,
        target_hourly=body.target_hourly,
        due=body.due,
        actor=current_user,
    )
    return await _finish(db, result, current_user)


@router.post("/rate-changes/{change_id}/outcome", response_model=RateChangeOut)
async def record_outcome(
    body: OutcomeIn,
    current_user: RecruitmentRateEditAccess,
    change_id: int = Path(gt=0, le=2_147_483_647),
    db: AsyncSession = Depends(get_db),
) -> RateChangeOut:
    change = await rate_change.lock_change(db, change_id)
    await ensure_job_read_access(db, current_user, change.job_id)
    result = await rate_change.record_outcome(
        db,
        change=change,
        outcome=body.outcome,
        agreed_amount=body.agreed_amount,
        note=body.note,
        actor=current_user,
    )
    return await _finish(db, result, current_user)


@router.post("/rate-changes/{change_id}/decision", response_model=RateChangeOut)
async def decide(
    body: DecisionIn,
    current_user: RecruitmentRateEditAccess,
    change_id: int = Path(gt=0, le=2_147_483_647),
    db: AsyncSession = Depends(get_db),
) -> RateChangeOut:
    change = await rate_change.lock_change(db, change_id)
    await ensure_job_read_access(db, current_user, change.job_id)
    result = await rate_change.decide(
        db,
        change=change,
        decision=body.decision,
        client_rate_amount=body.client_rate.amount if body.client_rate else None,
        client_rate_unit=body.client_rate.unit.value if body.client_rate else None,
        client_rate_currency=body.client_rate.currency if body.client_rate else None,
        actor=current_user,
    )
    return await _finish(db, result, current_user)
