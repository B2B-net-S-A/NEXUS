"""Historia stawek kandydata i „Stawka od” (0414).

* ``GET /api/candidates/{id}/rate-overview`` — „Stawka od”, ostatnio podana,
  każda obserwacja z rekrutacją, klientem, autorem i powodem, dla którego
  liczy się (albo nie) do minimum; obok stawki z umów (co płaciliśmy) —
  kwoty tylko dla osób z dostępem do finansów klienta.
* ``PUT /api/candidates/{id}/rate-observations/{key}`` — „Nie licz jako
  minimum” / „Przywróć”. Bramka jak edycja faktów profilu.

„Ustaw minimum” to istniejący ``PATCH …/profile-rate`` z ``is_minimum``.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.candidate_access import (
    CandidateProfileFactsReadAccess,
    CandidateProfileFactsWriteAccess,
)
from app.api.financial_access import can_read_client_finance
from app.api.recruitment_access import job_read_scope_clause
from app.api.section_access import SOURCING_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.core.scheduling import business_today
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus, RateUnit
from app.models.job import Job
from app.models.rate_history import RateHistory
from app.models.user import User
from app.services import candidate_rate_from as rate_from
from app.services.access_scope import resolve_delivery_lead_finance_client_ids
from app.services.candidate_rate_observations import RateObservation, collect
from app.services.contract_rates import RATE_SCHEDULE_LOADS, effective_rate_fields
from app.services.job_working_title import job_display_title_expr

router = APIRouter(dependencies=SOURCING_SECTION_DEPENDENCIES)

_PAID_STATUSES = (ContractStatus.active, ContractStatus.ending, ContractStatus.ended)
_KEY_PATTERN = r"^(card|stage|profile|apply):[0-9]+$|^profile-current$"


class RateObservationOut(BaseModel):
    key: str
    amount_hourly: Optional[Decimal]
    raw: Optional[str]
    at: Optional[datetime]
    source: str
    job_id: Optional[int]
    job_title: Optional[str]
    client_name: Optional[str]
    author_name: Optional[str]
    explicit_minimum: bool
    reason: str
    excluded_by_name: Optional[str] = None


class PaidRateOut(BaseModel):
    kind: Literal["contract", "legacy"]
    client_name: Optional[str]
    start_date: Optional[date]
    end_date: Optional[date]
    amount_hourly: Optional[Decimal]
    redacted: bool


class RateFromOut(BaseModel):
    amount: Decimal
    at: Optional[datetime]
    source: Optional[str]
    stale: bool
    key: Optional[str]
    job_id: Optional[int]
    job_title: Optional[str]
    client_name: Optional[str]


class RateOverviewResponse(BaseModel):
    candidate_id: int
    enabled: bool
    window_start: date
    rate_from: Optional[RateFromOut]
    latest_amount: Optional[Decimal]
    latest_at: Optional[datetime]
    count: int
    observations: list[RateObservationOut]
    paid: list[PaidRateOut]


class RateDecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Optional[Literal["exclude"]]


def _contract_hourly(contract: Contract, on: date) -> Optional[Decimal]:
    fields = effective_rate_fields(contract, on)
    if str(fields.get("rate_candidate_currency") or "PLN").upper() != "PLN":
        return None
    rate = fields.get("rate_candidate")
    if rate is None:
        return None
    rate = Decimal(str(rate))
    unit = contract.rate_unit
    if unit == RateUnit.hourly:
        return rate.quantize(Decimal("0.01"))
    if unit == RateUnit.daily:
        return (rate / Decimal(8)).quantize(Decimal("0.01"))
    hours = Decimal(contract.billing_hours_per_month or 168)
    return (rate / hours).quantize(Decimal("0.01"))


async def _job_labels(
    db: AsyncSession, user: User, job_ids: set[int]
) -> dict[int, tuple[Optional[str], Optional[str]]]:
    if not job_ids:
        return {}
    rows = await db.execute(
        select(Job.id, job_display_title_expr(), Client.name)
        .outerjoin(Client, Client.id == Job.client_id)
        .where(Job.id.in_(sorted(job_ids)), job_read_scope_clause(user, Job.id))
    )
    return {jid: (title, client) for jid, title, client in rows.all()}


async def _user_names(db: AsyncSession, user_ids: set[int]) -> dict[int, str]:
    if not user_ids:
        return {}
    rows = await db.execute(
        select(User.id, User.name).where(User.id.in_(sorted(user_ids)))
    )
    return {uid: name for uid, name in rows.all() if name}


async def _paid_rates(
    db: AsyncSession, user: User, candidate_id: int, today: date
) -> list[PaidRateOut]:
    contracts = (
        (
            await db.execute(
                select(Contract)
                .options(*RATE_SCHEDULE_LOADS)
                .where(
                    Contract.candidate_id == candidate_id,
                    Contract.status.in_(_PAID_STATUSES),
                )
            )
        )
        .scalars()
        .all()
    )
    legacy = (
        (
            await db.execute(
                select(RateHistory).where(RateHistory.candidate_id == candidate_id)
            )
        )
        .scalars()
        .all()
    )
    client_ids = {c.client_id for c in contracts if c.client_id} | {
        r.client_id for r in legacy if r.client_id
    }
    names: dict[int, str] = {}
    if client_ids:
        rows = await db.execute(
            select(Client.id, Client.name).where(Client.id.in_(sorted(client_ids)))
        )
        names = dict(rows.all())
    boundary = await resolve_delivery_lead_finance_client_ids(user, db)

    def visible(client_id: Optional[int]) -> bool:
        if client_id is None:
            return False
        return can_read_client_finance(
            user, client_id=client_id, delivery_lead_finance_client_ids=boundary
        )

    out: list[PaidRateOut] = []
    for contract in contracts:
        on = min(contract.end_date, today) if contract.end_date else today
        shown = visible(contract.client_id)
        out.append(
            PaidRateOut(
                kind="contract",
                client_name=names.get(contract.client_id),
                start_date=contract.start_date,
                end_date=contract.end_date,
                amount_hourly=_contract_hourly(contract, on) if shown else None,
                redacted=not shown,
            )
        )
    for row in legacy:
        shown = visible(row.client_id)
        amount = (
            Decimal(str(row.rate)).quantize(Decimal("0.01"))
            if shown and str(row.currency or "PLN").upper() == "PLN"
            else None
        )
        out.append(
            PaidRateOut(
                kind="legacy",
                client_name=names.get(row.client_id),
                start_date=row.start_date,
                end_date=row.end_date,
                amount_hourly=amount,
                redacted=not shown,
            )
        )
    out.sort(key=lambda p: p.start_date or date.min, reverse=True)
    return out


async def _excluded_by(db: AsyncSession, candidate_id: int) -> dict[str, Optional[int]]:
    rows = await db.execute(
        text(
            "SELECT observation_key, decided_by FROM candidate_rate_decisions "
            "WHERE candidate_id = :cid AND decision = 'exclude'"
        ),
        {"cid": candidate_id},
    )
    return {key: by for key, by in rows.all()}


@router.get(
    "/{candidate_id}/rate-overview",
    response_model=RateOverviewResponse,
)
async def get_rate_overview(
    candidate_id: int,
    current_user: CandidateProfileFactsReadAccess,
    db: AsyncSession = Depends(get_db),
) -> RateOverviewResponse:
    exists = await db.scalar(select(Candidate.id).where(Candidate.id == candidate_id))
    if exists is None:
        raise HTTPException(status_code=404, detail="Nie znaleziono kandydata.")
    today = business_today()
    observations: list[RateObservation] = (await collect(db, [candidate_id]))[
        candidate_id
    ]
    excluded = await _excluded_by(db, candidate_id)
    result = rate_from.compute(observations, set(excluded), today)

    jobs = await _job_labels(
        db, current_user, {o.job_id for o in observations if o.job_id}
    )
    authors = await _user_names(
        db,
        {o.author_id for o in observations if isinstance(o.author_id, int)}
        | {by for by in excluded.values() if by},
    )

    def label(job_id: Optional[int]) -> tuple[Optional[str], Optional[str]]:
        return jobs.get(job_id, (None, None)) if job_id else (None, None)

    items = sorted(
        observations,
        key=lambda o: (o.at is not None, o.at or datetime.min),
        reverse=True,
    )
    out_items = [
        RateObservationOut(
            key=o.key,
            amount_hourly=o.amount_hourly,
            raw=o.raw,
            at=o.at,
            source=o.source,
            job_id=o.job_id,
            job_title=label(o.job_id)[0],
            client_name=label(o.job_id)[1],
            author_name=authors.get(o.author_id)
            if isinstance(o.author_id, int)
            else None,
            explicit_minimum=o.explicit_minimum,
            reason=result.reasons.get(o.key, rate_from.REASON_NOT_COMPARABLE),
            excluded_by_name=authors.get(excluded.get(o.key) or -1),
        )
        for o in items
    ]
    rate_from_out = None
    if result.amount is not None:
        title, client = label(result.job_id)
        rate_from_out = RateFromOut(
            amount=result.amount,
            at=result.at,
            source=result.source,
            stale=result.stale,
            key=result.key,
            job_id=result.job_id,
            job_title=title,
            client_name=client,
        )
    return RateOverviewResponse(
        candidate_id=candidate_id,
        enabled=rate_from.enabled(),
        window_start=rate_from.window_start(today),
        rate_from=rate_from_out,
        latest_amount=result.latest_amount,
        latest_at=result.latest_at,
        count=result.count,
        observations=out_items,
        paid=await _paid_rates(db, current_user, candidate_id, today),
    )


@router.put("/{candidate_id}/rate-observations/{key}")
async def put_rate_decision(
    candidate_id: int,
    payload: RateDecisionIn,
    current_user: CandidateProfileFactsWriteAccess,
    key: str = Path(..., pattern=_KEY_PATTERN, max_length=80),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    candidate = await db.scalar(
        select(Candidate).where(Candidate.id == candidate_id).with_for_update()
    )
    if candidate is None:
        raise HTTPException(status_code=404, detail="Nie znaleziono kandydata.")
    known = {o.key for o in (await collect(db, [candidate_id]))[candidate_id]}
    if key not in known:
        raise HTTPException(
            status_code=404, detail="Tej stawki nie ma już w historii kandydata."
        )
    if payload.decision == "exclude":
        await db.execute(
            text(
                "INSERT INTO candidate_rate_decisions "
                "(candidate_id, observation_key, decision, decided_by) "
                "VALUES (:cid, :key, 'exclude', :uid) "
                "ON CONFLICT (candidate_id, observation_key) DO UPDATE SET "
                "decision = 'exclude', decided_by = :uid, decided_at = now()"
            ),
            {"cid": candidate_id, "key": key, "uid": current_user.id},
        )
    else:
        await db.execute(
            text(
                "DELETE FROM candidate_rate_decisions "
                "WHERE candidate_id = :cid AND observation_key = :key"
            ),
            {"cid": candidate_id, "key": key},
        )
    db.add(
        Activity(
            entity_type="candidate",
            entity_id=candidate_id,
            action="rate_observation_decided",
            user_id=current_user.id,
            details={"observation_key": key, "decision": payload.decision},
        )
    )
    await rate_from.recompute(db, [candidate_id])
    await db.commit()
    return {"candidate_id": candidate_id, "key": key, "decision": payload.decision}
