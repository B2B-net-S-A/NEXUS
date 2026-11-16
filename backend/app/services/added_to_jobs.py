"""„Kto ilu dodał” do rekrutacji — jedna liczba dla pulpitu i Insights.

Decyzja Artura z 16.11.2026 (zasady:
``docs/claude/rekrutacja-tablica/kto-ilu-dodal-w-zespole-rekrutacji.md``).
Ta sama reguła co tabela „Kto ilu dodał” na Tablicy rekrutacji, tylko przez
wszystkie rekrutacje naraz:

- **Dodanie** to para (kandydat, rekrutacja), liczona raz — w dniu jej
  pierwszego wpisu etapu (najwcześniejszy ``candidate_stages.moved_at``,
  przy remisie najmniejsze ``id``, jak ``earliest`` w kanbanie).
- **Osoba:** ``moved_by`` tego pierwszego wpisu. Gdy go nie ma, a para nie
  przyszła z silnika „Nowi”, ``recruitment_processes.opened_by_user_id``
  najnowszego procesu pary (ten sam proces, z którego Tablica bierze
  ``entry_source``).
- **Automat „Nowi”** (``entry_source = 'system'``) i wpisy bez osoby nie
  liczą się żadnej osobie — idą osobnymi liczbami, żeby suma się zgadzała.
- Okna to dni kalendarza firmy (``local_day_start_utc``), półotwarte
  ``[since, until)``.
- Dodania nie dają punktów w lidze (Artur: nie).

To co innego niż kolumna „Kandydaci” w Insights (``user_activities.
candidate_added`` — nowo utworzone profile) i niż filtr „Kto dodał” na
Tablicy (osoba karty).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Mapping

from sqlalchemy import and_, case, exists, func, null, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.scheduling import local_day_start_utc
from app.models.job import Job
from app.models.recruitment_pipeline import CandidateStage
from app.models.recruitment_process import RecruitmentProcess
from app.services.candidate_claim import ENTRY_SYSTEM

__all__ = [
    "LAST_DAYS",
    "AddedCounts",
    "added_today_and_last_days",
    "count_added_to_jobs",
]

# „7 dni” = dziś i sześć dni wstecz, jak kolumna na Tablicy.
LAST_DAYS = 7


@dataclass(frozen=True)
class AddedCounts:
    """Dodania w jednym oknie: osoby, automat „Nowi” i wpisy bez osoby."""

    by_user: Mapping[int, int] = field(default_factory=dict)
    system: int = 0
    unattributed: int = 0

    @property
    def by_people(self) -> int:
        return sum(self.by_user.values())

    @property
    def total(self) -> int:
        return self.by_people + self.system + self.unattributed


async def count_added_to_jobs(
    db: AsyncSession,
    *,
    since: datetime,
    until: datetime,
    client_id: int | None = None,
) -> AddedCounts:
    """Dodania par, których pierwszy wpis etapu wypadł w ``[since, until)``."""
    if since.tzinfo is None or until.tzinfo is None:
        # Naiwny czas Postgres wziąłby za UTC i przesunął granicę dnia.
        raise ValueError("count_added_to_jobs: okno wymaga datetime'ów tz-aware")
    stage = aliased(CandidateStage)
    earlier = aliased(CandidateStage)
    # Pierwszy wpis pary = brak wcześniejszego wpisu tej pary (przy remisie
    # czasu wcześniejszy jest mniejszy `id`).
    added = select(stage.candidate_id, stage.job_id, stage.moved_by).where(
        stage.moved_at >= since,
        stage.moved_at < until,
        ~exists().where(
            earlier.candidate_id == stage.candidate_id,
            earlier.job_id == stage.job_id,
            or_(
                earlier.moved_at < stage.moved_at,
                and_(earlier.moved_at == stage.moved_at, earlier.id < stage.id),
            ),
        ),
    )
    if client_id is not None:
        added = added.where(
            stage.job_id.in_(select(Job.id).where(Job.client_id == client_id))
        )
    added = added.cte("added")
    # Najnowszy proces pary — z niego Tablica bierze `entry_source`.
    process = (
        select(RecruitmentProcess.entry_source, RecruitmentProcess.opened_by_user_id)
        .where(
            RecruitmentProcess.candidate_id == added.c.candidate_id,
            RecruitmentProcess.job_id == added.c.job_id,
        )
        .order_by(RecruitmentProcess.attempt_no.desc(), RecruitmentProcess.id.desc())
        .limit(1)
        .lateral("process")
    )
    from_automat = and_(
        added.c.moved_by.is_(None), process.c.entry_source == ENTRY_SYSTEM
    )
    classified = (
        select(
            case(
                (added.c.moved_by.is_not(None), added.c.moved_by),
                (process.c.entry_source == ENTRY_SYSTEM, null()),
                else_=process.c.opened_by_user_id,
            ).label("user_id"),
            func.coalesce(from_automat, False).label("is_system"),
        )
        .select_from(added.outerjoin(process, true()))
        .subquery("classified")
    )
    rows = (
        await db.execute(
            select(classified.c.user_id, classified.c.is_system, func.count()).group_by(
                classified.c.user_id, classified.c.is_system
            )
        )
    ).all()
    by_user: dict[int, int] = {}
    system = 0
    unattributed = 0
    for user_id, is_system, added in rows:
        if user_id is not None:
            by_user[int(user_id)] = by_user.get(int(user_id), 0) + int(added)
        elif is_system:
            system += int(added)
        else:
            unattributed += int(added)
    return AddedCounts(by_user=by_user, system=system, unattributed=unattributed)


async def added_today_and_last_days(
    db: AsyncSession, *, today: date, client_id: int | None = None
) -> tuple[AddedCounts, AddedCounts]:
    """Dodania dziś i w ostatnich ``LAST_DAYS`` dniach (z dziś), kalendarz firmy."""
    until = local_day_start_utc(today + timedelta(days=1))
    day = await count_added_to_jobs(
        db, since=local_day_start_utc(today), until=until, client_id=client_id
    )
    week = await count_added_to_jobs(
        db,
        since=local_day_start_utc(today - timedelta(days=LAST_DAYS - 1)),
        until=until,
        client_id=client_id,
    )
    return day, week
