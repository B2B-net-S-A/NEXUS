"""Porcja na osobę: tylko przypisane rekrutacje, P0 najpierw (decyzje Artura 10.11.2026).

Raport i makiety: https://claude.ai/artifact/SiG22GMDhRFCgShW6281sj. Do 10.11
porcja liczyła się na rekrutację (20 osób dzielonych po równo w zespole), więc
osoby przypisane do P0 dostały z P0 77 z 609 kart (13%), a AML z 12 przypisanymi
dostało 7 kart. Teraz:

* porcja osoby = jej poziom (``review_batch_levels``: 10, potem +10 dziennie do 50);
* tylko rekrutacje, do których osoba jest przypisana (``recruiter_ids_for_jobs``);
* najpierw wszystkie jej P0, potem P1 Pilne, „Bez priorytetu”, „Przyjmujemy
  kandydatów”; w obrębie poziomu rekrutacje na zmianę (``plan_portions``);
* decyzje z dziś zmniejszają to, co jeszcze przychodzi: porcja to porcja dnia.

``plan_portions`` jest czystą funkcją (testy bez bazy), ``load_plan`` zbiera dane.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Collection, Iterable, Mapping, Optional, Sequence

from sqlalchemy import and_, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import Job, JobStatus
from app.models.job_autofill_pool import JobAutofillPool
from app.models.candidate_stage_removal import CandidateStageRemoval
from app.models.recruitment_pipeline import CandidateStage

# Poziomy, z których porcja bierze osoby, od pierwszego.
TIER_P0 = 0
_TIER_BY_LEVEL = {"p1": 1, "p2": 2, "accepting": 3}
TIER_KEYS = {0: "p0", 1: "p1", 2: "p2", 3: "accepting"}


def tier_of(job: Job, now: datetime) -> int:
    """0 = P0, 1 = P1 Pilne, 2 = „Bez priorytetu”, 3 = „Przyjmujemy kandydatów”."""
    from app.services import job_p0
    from app.services.job_priority import level_of

    if job_p0.is_active(job, now):
        return TIER_P0
    return _TIER_BY_LEVEL.get(level_of(job.priority), 2)


def plan_portions(
    *,
    caps: Mapping[int, int],
    teams: Mapping[int, Sequence[int]],
    tiers: Mapping[int, int],
    owned: Mapping[int, Mapping[int, int]],
    free: Mapping[int, int],
) -> dict[int, dict[int, int]]:
    """Ile kart porcji każda osoba ma dziś mieć w każdej rekrutacji.

    ``caps`` = ile kart osoba może jeszcze dostać dziś (poziom minus decyzje
    z dziś), ``teams`` = przypisani do rekrutacji, ``tiers`` = poziom rekrutacji
    (``tier_of``), ``owned`` = czekające karty porcji osoby w rekrutacji,
    ``free`` = ile osób rekrutacja może jeszcze dać (karty bez właściciela
    i wolna pula). Własne karty osoby liczą się najpierw i nie zabierają
    miejsca innym. Poziom po poziomie, osoby na zmianę po jednej karcie, więc
    wspólna pula P0 dzieli się równo między przypisanych.
    """
    jobs_of: dict[int, list[int]] = {
        user: sorted(job for job, team in teams.items() if user in team)
        for user in caps
    }
    want: dict[int, dict[int, int]] = {user: {} for user in caps}
    left = {job: max(0, int(free.get(job, 0))) for job in teams}
    own_left = {
        user: {job: max(0, int(n)) for job, n in (owned.get(user) or {}).items()}
        for user in caps
    }
    remaining = {user: max(0, int(cap)) for user, cap in caps.items()}
    users = sorted(caps)
    for tier in sorted({tiers.get(job, 2) for job in teams}):
        progress = True
        while progress:
            progress = False
            for user in users:
                if remaining[user] <= 0:
                    continue
                options = [
                    job
                    for job in jobs_of[user]
                    if tiers.get(job, 2) == tier
                    and (own_left[user].get(job, 0) > 0 or left[job] > 0)
                ]
                if not options:
                    continue
                job = min(options, key=lambda j: (want[user].get(j, 0), j))
                if own_left[user].get(job, 0) > 0:
                    own_left[user][job] -= 1
                else:
                    left[job] -= 1
                want[user][job] = want[user].get(job, 0) + 1
                remaining[user] -= 1
                progress = True
    return want


@dataclass(frozen=True)
class Plan:
    """Plan porcji na dziś: rekrutacja → osoba → ile kart ma mieć."""

    by_job: dict[int, dict[int, int]]
    tiers: dict[int, int]
    # Ile nowych osób rekrutacja ma dostać z puli (po rozdaniu kart bez właściciela).
    missing: dict[int, int] = field(default_factory=dict)

    def job_order(self) -> list[int]:
        """Rekrutacje do obsłużenia: P0 najpierw, potem niższe, nowsze wcześniej."""
        return sorted(self.by_job, key=lambda job: (self.tiers.get(job, 2), -job))

    def want_for(self, job_id: int) -> dict[int, int]:
        return dict(self.by_job.get(job_id) or {})


def _invert(want: Mapping[int, Mapping[int, int]]) -> dict[int, dict[int, int]]:
    out: dict[int, dict[int, int]] = {}
    for user, jobs in want.items():
        for job, n in jobs.items():
            if n > 0:
                out.setdefault(job, {})[user] = n
    return out


async def _pool_free(
    db: AsyncSession, job_ids: Collection[int], min_score: float
) -> dict[int, int]:
    """Osoby z puli od progu, których jeszcze nie ma w rekrutacji (szacunek: reguły
    dopełniania mogą odrzucić część z nich)."""
    if not job_ids:
        return {}
    pool = JobAutofillPool
    rows = await db.execute(
        select(pool.job_id, func.count())
        .where(
            pool.job_id.in_(sorted(job_ids)),
            pool.score >= min_score,
            ~exists().where(
                and_(
                    CandidateStage.job_id == pool.job_id,
                    CandidateStage.candidate_id == pool.candidate_id,
                )
            ),
            ~exists().where(
                and_(
                    CandidateStageRemoval.job_id == pool.job_id,
                    CandidateStageRemoval.candidate_id == pool.candidate_id,
                )
            ),
        )
        .group_by(pool.job_id)
    )
    return {int(job_id): int(n) for job_id, n in rows.all()}


async def load_plan(
    db: AsyncSession,
    job_ids: Iterable[int],
    *,
    now: datetime,
    exhausted: Collection[int] = (),
) -> Plan:
    """Plan dla rekrutacji w pracy. ``exhausted`` = rekrutacje, w których dziś
    dopełnianie dało mniej, niż planowano: liczą się w nich tylko karty bez
    właściciela, więc osoby dostają resztę z niższych poziomów."""
    from app.services import review_batch as rb
    from app.services import review_batch_levels as levels

    teams = {
        job: users
        for job, users in (await rb.recruiter_ids_for_jobs(db, job_ids)).items()
        if users
    }
    if not teams:
        return Plan(by_job={}, tiers={})
    jobs = (await db.scalars(select(Job).where(Job.id.in_(list(teams))))).all()
    tiers = {
        job.id: tier_of(job, now) for job in jobs if job.status == JobStatus.published
    }
    teams = {job: users for job, users in teams.items() if job in tiers}
    users = sorted({user for team in teams.values() for user in team})
    value = await rb.read_settings(db)
    stored = await levels.read_levels(db)
    since = rb.day_start(now)
    decisions = await rb._decisions(db, users, now=now, since=since)
    done = {
        user: rb.summarize_day(decisions.get(user, []), since).done for user in users
    }
    caps = {
        user: levels.level_of(stored, user, value.minimum) - done[user]
        for user in users
    }
    cards = rb.batch_cards(
        await rb.pending_cards(db, job_ids=list(teams)), now, value.min_score
    )
    owned: dict[int, dict[int, int]] = {}
    unowned: dict[int, int] = {}
    for card in cards:
        if card.owner_id is not None and card.owner_id in teams.get(card.job_id, ()):
            mine = owned.setdefault(card.owner_id, {})
            mine[card.job_id] = mine.get(card.job_id, 0) + 1
        else:
            unowned[card.job_id] = unowned.get(card.job_id, 0) + 1
    pool = await _pool_free(
        db, [job for job in teams if job not in set(exhausted)], value.min_score
    )
    free = {job: unowned.get(job, 0) + pool.get(job, 0) for job in teams}
    want = plan_portions(caps=caps, teams=teams, tiers=tiers, owned=owned, free=free)
    by_job = _invert(want)
    # Rekrutacja z przypisanymi, ale bez kart w planie, też jest w planie:
    # przebieg zdejmuje w niej właścicieli spoza zespołu i nadwyżki.
    for job in teams:
        by_job.setdefault(job, {})
    missing = {}
    for job, people in by_job.items():
        short = sum(
            max(0, n - (owned.get(user) or {}).get(job, 0))
            for user, n in people.items()
        )
        missing[job] = max(0, short - unowned.get(job, 0))
    return Plan(by_job=by_job, tiers=tiers, missing=missing)


async def want_for_job(
    db: AsyncSession, job_id: int, *, now: datetime
) -> dict[int, int]:
    """Plan jednej rekrutacji: liczy porcje jej przypisanych we wszystkich ich
    rekrutacjach w pracy (P0 gdzie indziej zmniejsza to, co przyjdzie tutaj)."""
    from app.services import review_batch as rb
    from app.services.job_team import jobs_worked_by_clause
    from app.services.request_work_state import IN_WORK_STATES

    team = (await rb.recruiter_ids_for_jobs(db, [job_id])).get(job_id, [])
    if not team:
        return {}
    job_ids = set(
        (
            await db.scalars(
                select(Job.id).where(
                    jobs_worked_by_clause(list(team)),
                    Job.status == JobStatus.published,
                    Job.work_state.in_(IN_WORK_STATES),
                )
            )
        ).all()
    )
    job_ids.add(job_id)
    plan = await load_plan(db, job_ids, now=now)
    return plan.want_for(job_id)


def tier_key(tier: Optional[int]) -> str:
    return TIER_KEYS.get(tier if tier is not None else 2, "p2")
