"""Koszyki „Baza” / „LinkedIn” w zespole rekrutacji (0655, 06.11.2026).

Decyzje Artura 06.11.2026 (wariant B z makiet
https://claude.ai/artifact/Whdf5UxmLqKiUpmbcUYTyk):

* zespół rekrutacji dzieli się na dwa koszyki: ``base`` (szuka w bazie
  NEXUSA) i ``linkedin``. Osoba jest w jednym koszyku albo jeszcze w żadnym;
* do koszyka dołącza sam rekruter (siebie) albo Olaf / Delivery Lead / admin
  (każdego z zespołu, ``user_can_staff_job``). Plan liczby osób w koszyku
  ustawia tylko ta druga grupa;
* rekruter, który dodaje albo przesuwa karty w rekrutacji, nie będąc w zespole,
  NIE jest blokowany („Kanban bez bramek”, 17.09.2026) — ekrany pokazują go
  jako „pracuje bez przypisania” (``unassigned_workers``).

Dlaczego ręcznie, a nie z danych: na kopii produkcji z 06.11 w 60 dniach
13 080 pierwszych dodań dotyczyło osób już będących w bazie, 638 nowych
profili z LinkedIna; wiadomości z LinkedIna do NEXUSA nie trafiają, więc
kto „robi LinkedIna”, wie tylko zespół.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import Activity
from app.models.job import Job
from app.models.job_recruiter_channel import CHANNELS, JobRecruiterChannel
from app.models.recruitment_pipeline import CandidateStage
from app.models.user import User
from app.services.auto_cc_collaborators import operator_clause

# Plan to liczba osób w koszyku; więcej niż 20 to pomyłka przy wpisywaniu.
PLAN_MAX = 20
# Ile dni wstecz ruch karty oznacza „pracuje nad rekrutacją”.
UNASSIGNED_WINDOW_DAYS = 30


@dataclass(frozen=True)
class UnassignedWorker:
    user_id: int
    name: str
    # Ile różnych kandydatów osoba dodała albo przesunęła w oknie.
    cards: int


async def set_channel(
    db: AsyncSession,
    *,
    job: Job,
    user_id: int,
    channel: Optional[str],
    actor_id: int,
) -> bool:
    """Ustaw koszyk osoby przy rekrutacji; ``None`` zdejmuje wybór.

    Zwraca ``True``, gdy coś się zmieniło (wtedy wpis w Historii). Bez commitu.
    """
    if channel is not None and channel not in CHANNELS:
        raise ValueError(f"unknown channel {channel!r}")
    current = await db.scalar(
        select(JobRecruiterChannel.channel).where(
            JobRecruiterChannel.job_id == job.id,
            JobRecruiterChannel.user_id == user_id,
        )
    )
    if current == channel:
        return False
    if channel is None:
        await db.execute(
            delete(JobRecruiterChannel).where(
                JobRecruiterChannel.job_id == job.id,
                JobRecruiterChannel.user_id == user_id,
            )
        )
    else:
        stmt = pg_insert(JobRecruiterChannel).values(
            job_id=job.id, user_id=user_id, channel=channel, set_by=actor_id
        )
        await db.execute(
            stmt.on_conflict_do_update(
                constraint="uq_job_recruiter_channels_job_user",
                set_={"channel": channel, "set_by": actor_id, "set_at": func.now()},
            )
        )
    db.add(
        Activity(
            entity_type="job",
            entity_id=job.id,
            action="recruiter_channel_changed",
            user_id=actor_id,
            details={"user_id": user_id, "from": current, "to": channel},
        )
    )
    await db.flush()
    return True


async def set_plan(
    db: AsyncSession,
    *,
    job: Job,
    base: Optional[int],
    linkedin: Optional[int],
    actor_id: int,
) -> bool:
    """Plan liczby osób w koszykach; ``None`` = bez planu. Bez commitu."""
    for value in (base, linkedin):
        if value is not None and not 0 <= value <= PLAN_MAX:
            raise ValueError("plan out of range")
    before = (job.channel_plan_base, job.channel_plan_linkedin)
    if before == (base, linkedin):
        return False
    job.channel_plan_base = base
    job.channel_plan_linkedin = linkedin
    db.add(
        Activity(
            entity_type="job",
            entity_id=job.id,
            action="channel_plan_changed",
            user_id=actor_id,
            details={
                "from": {"base": before[0], "linkedin": before[1]},
                "to": {"base": base, "linkedin": linkedin},
            },
        )
    )
    await db.flush()
    return True


async def unassigned_workers(
    db: AsyncSession,
    team_by_job: dict[int, Iterable[int]],
    *,
    now: Optional[datetime] = None,
) -> dict[int, list[UnassignedWorker]]:
    """Rekruterzy, którzy w ostatnich 30 dniach dodali albo przesunęli karty
    w rekrutacji, a nie są w jej zespole (``team_by_job`` = osoby pracujące
    z ``job_team.recruiters_for_jobs``). Jedno zapytanie na wszystkie rekrutacje.
    """
    out: dict[int, list[UnassignedWorker]] = {job_id: [] for job_id in team_by_job}
    if not team_by_job:
        return out
    since = (now or datetime.now(timezone.utc)) - timedelta(days=UNASSIGNED_WINDOW_DAYS)
    rows = (
        await db.execute(
            select(
                CandidateStage.job_id,
                User.id,
                User.name,
                func.count(func.distinct(CandidateStage.candidate_id)).label("cards"),
            )
            .join(User, User.id == CandidateStage.moved_by)
            .where(
                CandidateStage.job_id.in_(list(team_by_job)),
                CandidateStage.moved_at >= since,
                User.is_active.is_(True),
                operator_clause(),
            )
            .group_by(CandidateStage.job_id, User.id, User.name)
            .order_by(CandidateStage.job_id, func.count().desc(), User.name)
        )
    ).all()
    team_sets = {job_id: set(ids) for job_id, ids in team_by_job.items()}
    for job_id, user_id, name, cards in rows:
        if user_id in team_sets.get(job_id, set()):
            continue
        out[job_id].append(
            UnassignedWorker(user_id=user_id, name=name, cards=int(cards))
        )
    return out
