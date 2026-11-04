"""„Kandydaci do zamknięcia” — kafelek pulpitu (prośba Olafa, decyzje Artura 20.10.2026).

Osoby, których NAJNOWSZY wiersz pary (kandydat, rekrutacja) stoi w kolumnie
Tablicy „Akceptacja i umowa”: zaakceptowane przez klienta, z wysłaną umową
albo z podpisaną umową — aż do „Zatrudniony”. Ta sama reguła kolumn co Tablica
(`cv_in_transit._place`), więc lista i kolumna mówią to samo.

Zakres według roli (decyzja Artura 20.10.2026):

* admin, Head of Recruitment, Finanse — wszystkie opublikowane rekrutacje,
* Delivery Lead — rekrutacje z jego nazwy albo bez DL-a u jego klienta
  (`board_flow._dl_job_ids`, ta sama reguła co przegląd DL),
* Rekruter i TCM — rekrutacje, w których są Rekruterem, i te, w których
  prowadzą kandydata (właściciel otwartego procesu).

Bez warunku stanu requestu (`work_state`): po akceptacji request bywa już
„Zakończony”, a umowy jeszcze nikt nie zamknął.

Stawki pary czyta `recruitment_rates.for_pairs` (stawka do klienta = przychód,
stawka kandydata = koszt). Stawkę do klienta ukrywa się rolom bez
`user_can_view_client_rate` — marży bez niej nie da się policzyć, więc front
jej wtedy nie pokazuje. Marżę liczy front (`lib/dl-review-margin.ts`), tą
samą regułą co przegląd Delivery Leada.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Literal, Optional

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import Job, JobStatus
from app.models.recruitment_process import ProcessStatus, RecruitmentProcess
from app.models.user import User, UserRole
from app.services import recruitment_rates
from app.services.board_flow import _dl_job_ids, _latest_rows, _name, _Placed
from app.services.board_tasks import _catalog, dl_portfolio_client_ids
from app.services.cv_in_transit import _place
from app.services.interview_slots import default_recruiter_ids
from app.services.job_team import jobs_worked_by_clause

# Kafelek, nie raport — dłuższa lista przestaje być czytana.
MAX_ROWS = 50

CONTRACT_COLUMN = "contract"

Step = Literal["accepted", "sent", "signed"]
STEPS: tuple[Step, ...] = ("accepted", "sent", "signed")

_ALL_JOBS_ROLES = (UserRole.admin, UserRole.head_of_recruitment, UserRole.finance)
_RECRUITING_ROLES = (UserRole.recruiter, UserRole.talent_community_manager)


@dataclass(frozen=True)
class ClosingRow:
    candidate_id: int
    candidate_name: str
    job_id: int
    job_title: Optional[str]
    job_working_title: Optional[str]
    client_name: Optional[str]
    step: Step
    since: datetime
    delivery_lead_name: Optional[str]
    recruiter_name: Optional[str]
    rate: Optional[recruitment_rates.RecruitmentRate]


@dataclass(frozen=True)
class ClosingList:
    rows: list[ClosingRow]
    total: int
    # Ile osób na każdym kroku — ze WSZYSTKICH, nie tylko pokazanych wierszy.
    step_counts: dict[str, int] = field(default_factory=dict)


def step_of(badge: Optional[str]) -> Step:
    """Krok w kolumnie „Akceptacja i umowa” — lustro `contractStepCounts`."""

    if badge == "contract_signed":
        return "signed"
    if badge == "contract_sent":
        return "sent"
    return "accepted"


async def scope_job_ids(db: AsyncSession, user: User) -> list[int]:
    """Opublikowane rekrutacje, których kandydatów osoba widzi na liście."""

    if user.has_any_role(*_ALL_JOBS_ROLES):
        return list(
            (
                await db.scalars(
                    select(Job.id).where(Job.status == JobStatus.published)
                )
            ).all()
        )
    ids: set[int] = set()
    if user.has_role(UserRole.delivery_lead):
        portfolio = await dl_portfolio_client_ids(db, user.id)
        ids.update(await _dl_job_ids(db, user, portfolio))
    if user.has_any_role(*_RECRUITING_ROLES):
        owned = select(RecruitmentProcess.job_id).where(
            RecruitmentProcess.owner_user_id == user.id,
            RecruitmentProcess.status == ProcessStatus.open,
        )
        ids.update(
            (
                await db.scalars(
                    select(Job.id).where(
                        Job.status == JobStatus.published,
                        or_(jobs_worked_by_clause([user.id]), Job.id.in_(owned)),
                    )
                )
            ).all()
        )
    return sorted(ids)


async def _user_names(db: AsyncSession, user_ids: set[int]) -> dict[int, str]:
    if not user_ids:
        return {}
    return dict(
        (
            await db.execute(select(User.id, User.name).where(User.id.in_(user_ids)))
        ).all()
    )


async def load(db: AsyncSession, user: User) -> ClosingList:
    """Lista dla patrzącego — najdłużej czekający na górze."""

    job_ids = await scope_job_ids(db, user)
    if not job_ids:
        return ClosingList(rows=[], total=0, step_counts={s: 0 for s in STEPS})
    catalog = await _catalog(db)
    placed: list[tuple[_Placed, Step]] = []
    for p in await _latest_rows(db, catalog, job_ids):
        if p.column != CONTRACT_COLUMN:
            continue
        r = p.row
        _column, badge = _place(catalog, r.template_id, r.stage_def_id, r.stage)
        placed.append((p, step_of(badge)))
    placed.sort(key=lambda item: (item[0].row.moved_at, item[0].row.id))
    shown = placed[:MAX_ROWS]
    pairs = [(p.row.candidate_id, p.row.job_id) for p, _ in shown]
    rates = await recruitment_rates.for_pairs(db, pairs)
    recruiters = await default_recruiter_ids(db, pairs)
    shown_jobs = sorted({p.row.job_id for p, _ in shown})
    dl_by_job: dict[int, Optional[int]] = (
        dict(
            (
                await db.execute(
                    select(Job.id, Job.delivery_lead_id).where(Job.id.in_(shown_jobs))
                )
            ).all()
        )
        if shown_jobs
        else {}
    )
    names = await _user_names(
        db,
        {i for i in dl_by_job.values() if i} | {i for i in recruiters.values() if i},
    )
    rows = []
    for p, step in shown:
        r = p.row
        pair = (r.candidate_id, r.job_id)
        dl_id = dl_by_job.get(r.job_id)
        recruiter_id = recruiters.get(pair)
        rows.append(
            ClosingRow(
                candidate_id=r.candidate_id,
                candidate_name=_name(r.cname, r.clastname),
                job_id=r.job_id,
                job_title=r.title,
                job_working_title=r.working_title,
                client_name=r.client_name,
                step=step,
                since=r.moved_at,
                delivery_lead_name=names.get(dl_id) if dl_id else None,
                recruiter_name=names.get(recruiter_id) if recruiter_id else None,
                rate=rates.get(pair),
            )
        )
    counts = {step: 0 for step in STEPS}
    for _p, step in placed:
        counts[step] += 1
    return ClosingList(rows=rows, total=len(placed), step_counts=counts)


def rate_fields(
    rate: Optional[recruitment_rates.RecruitmentRate], *, show_client_rate: bool
) -> dict[str, Optional[Decimal | str]]:
    """Stawki wiersza dla API; bez prawa do stawki do klienta — puste."""

    if rate is None:
        return {}
    data = rate.as_dict(show_client_rate=show_client_rate)
    return {
        key: data[key]
        for key in (
            "candidate_rate_value",
            "candidate_rate_unit",
            "candidate_rate_currency",
            "client_rate_value",
            "client_rate_unit",
            "client_rate_currency",
        )
    }
