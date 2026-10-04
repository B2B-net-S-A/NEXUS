"""Grupa „Zmiany stawki” w „Czeka na Ciebie” (0418, decyzje Artura 04.10.2026).

Sprawy ze ``candidate_rate_changes``, liczone przy odczycie:

* „Twój ruch”
  - Delivery Lead rekrutacji — wzrost po wysłaniu CV czeka na decyzję
    o stawce do klienta (``requested`` albo ``agreed`` z ``requires_decision``);
  - osoba wskazana do negocjacji — rozmowa z kandydatem (``negotiating``).
* „U innych”
  - Head of Recruitment — sprawy czekające na DL dłużej niż
    ``HOR_OVERDUE_BUSINESS_DAYS`` dni roboczych;
  - autor zmiany — jego zgłoszenie czeka na kogoś innego.

Delivery Lead rekrutacji = ``jobs.delivery_lead_id`` (aktywne konto), a bez
niego DL z portfelem klienta — lustro ``stage_handoff_recipients._dl_reviewers``.
Nic tu nie zapisuje.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.candidate_rate_change import CandidateRateChange
from app.models.client import Client
from app.models.job import Job
from app.models.user import User, UserRole
from app.services.candidate_followups import add_business_days, local_date
from app.services.candidate_rate_change import format_rate
from app.services.candidate_rate_change_schema import OPEN_STATUSES

logger = logging.getLogger(__name__)

HOR_OVERDUE_BUSINESS_DAYS = 2
MAX_ROWS = 30

REASON_DECIDE = "decide"
REASON_NEGOTIATE = "negotiate"
REASON_WAITING = "waiting"


@dataclass(frozen=True)
class RateChangeTask:
    change_id: int
    reason: str
    status: str
    candidate_id: int
    candidate_name: str
    job_id: int
    job_title: str
    client_name: Optional[str]
    previous_label: Optional[str]
    requested_label: str
    agreed_label: Optional[str]
    negotiator_name: Optional[str]
    negotiation_due: Optional[date]
    since: datetime
    # Na kogo czeka sprawa (dla „U innych”): „Delivery Lead”, imię negocjatora.
    waiting_on: Optional[str] = None


@dataclass
class RateChangeTasks:
    mine: list[RateChangeTask] = field(default_factory=list)
    by_others: list[RateChangeTask] = field(default_factory=list)


def _label(amount, unit, currency) -> Optional[str]:  # noqa: ANN001
    return format_rate(amount, unit, currency) if amount is not None else None


async def _job_dl_ids(db: AsyncSession, jobs: list[Job]) -> dict[int, set[int]]:
    """DL każdej rekrutacji — jedna reguła z dzwonkami (``_dl_reviewers``)."""

    from app.services.stage_handoff_recipients import (  # noqa: PLC0415
        _dl_reviewers,
    )

    return {job.id: set(await _dl_reviewers(db, job)) for job in jobs}


async def load_for_user(
    db: AsyncSession, user: User, *, now: datetime
) -> RateChangeTasks:
    rows = (
        await db.execute(
            select(CandidateRateChange, Candidate, Job, Client.name)
            .join(Candidate, Candidate.id == CandidateRateChange.candidate_id)
            .join(Job, Job.id == CandidateRateChange.job_id)
            .outerjoin(Client, Client.id == Job.client_id)
            .where(CandidateRateChange.status.in_(OPEN_STATUSES))
            .order_by(CandidateRateChange.created_at)
        )
    ).all()
    if not rows:
        return RateChangeTasks()
    jobs = list({job.id: job for _, _, job, _ in rows}.values())
    dls = await _job_dl_ids(db, jobs)
    negotiator_ids = {c.negotiator_id for c, *_ in rows if c.negotiator_id}
    names: dict[int, str] = {}
    if negotiator_ids:
        names = {
            uid: (name or email)
            for uid, name, email in (
                await db.execute(
                    select(User.id, User.name, User.email).where(
                        User.id.in_(negotiator_ids)
                    )
                )
            ).all()
        }
    is_hor = user.has_any_role(UserRole.head_of_recruitment)
    today = local_date(now)
    out = RateChangeTasks()
    from app.services.candidate_rate_change import (  # noqa: PLC0415
        change_still_active,
    )

    for change, candidate, job, client_name in rows:
        if not await change_still_active(db, change):
            continue
        waits_on_dl = change.requires_decision and change.status in (
            "requested",
            "agreed",
        )
        negotiating = change.status == "negotiating"
        task_reason: Optional[str] = None
        if waits_on_dl and user.id in dls.get(job.id, set()):
            task_reason = REASON_DECIDE
        elif negotiating and change.negotiator_id == user.id:
            task_reason = REASON_NEGOTIATE
        waiting_on = (
            names.get(change.negotiator_id)
            if negotiating and change.negotiator_id
            else "Delivery Lead"
            if waits_on_dl
            else None
        )
        task = RateChangeTask(
            change_id=change.id,
            reason=task_reason or REASON_WAITING,
            status=change.status,
            candidate_id=candidate.id,
            candidate_name=" ".join(
                p for p in (candidate.name, candidate.lastname) if p
            ).strip()
            or f"Kandydat #{candidate.id}",
            job_id=job.id,
            job_title=job.working_title or job.title,
            client_name=client_name,
            previous_label=_label(
                change.previous_amount, change.previous_unit, change.previous_currency
            ),
            requested_label=format_rate(
                change.requested_amount,
                change.requested_unit,
                change.requested_currency,
            ),
            agreed_label=_label(
                change.agreed_amount, change.agreed_unit, change.agreed_currency
            ),
            negotiator_name=names.get(change.negotiator_id)
            if change.negotiator_id
            else None,
            negotiation_due=change.negotiation_due,
            since=change.created_at,
            waiting_on=waiting_on,
        )
        if task_reason is not None:
            out.mine.append(task)
            continue
        if waiting_on is None:
            continue
        overdue = (
            add_business_days(change.created_at, HOR_OVERDUE_BUSINESS_DAYS) <= today
        )
        if change.created_by == user.id or (is_hor and overdue):
            out.by_others.append(task)
    out.mine = out.mine[:MAX_ROWS]
    out.by_others = out.by_others[:MAX_ROWS]
    return out


async def load_safely(
    db: AsyncSession, user: User, *, now: datetime
) -> Optional[RateChangeTasks]:
    """Dla pulpitu: awaria = ``None`` (savepoint — sesja żądania jedzie dalej)."""

    try:
        async with db.begin_nested():
            return await load_for_user(db, user, now=now)
    except Exception:  # noqa: BLE001
        logger.exception("rate_change_tasks: nie udało się policzyć listy")
        return None
