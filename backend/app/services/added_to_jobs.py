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

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import local_day_start_utc
from app.services.team_filters import client_job_filter

__all__ = [
    "LAST_DAYS",
    "AddedCounts",
    "added_today_and_last_days",
    "count_added_to_jobs",
]

# „7 dni” = dziś i sześć dni wstecz, jak kolumna na Tablicy.
LAST_DAYS = 7

_SQL = f"""
    WITH added AS (
        SELECT cs.candidate_id, cs.job_id, cs.moved_by
        FROM candidate_stages cs
        WHERE cs.moved_at >= :since
          AND cs.moved_at < :until
          AND {client_job_filter("cs.job_id")}
          AND NOT EXISTS (
              SELECT 1
              FROM candidate_stages earlier
              WHERE earlier.candidate_id = cs.candidate_id
                AND earlier.job_id = cs.job_id
                AND (
                    earlier.moved_at < cs.moved_at
                    OR (earlier.moved_at = cs.moved_at AND earlier.id < cs.id)
                )
          )
    ),
    classified AS (
        SELECT
            CASE
                WHEN a.moved_by IS NOT NULL THEN a.moved_by
                WHEN rp.entry_source = 'system' THEN NULL
                ELSE rp.opened_by_user_id
            END AS user_id,
            (a.moved_by IS NULL AND rp.entry_source = 'system') AS is_system
        FROM added a
        LEFT JOIN LATERAL (
            SELECT p.entry_source, p.opened_by_user_id
            FROM recruitment_processes p
            WHERE p.candidate_id = a.candidate_id AND p.job_id = a.job_id
            ORDER BY p.attempt_no DESC, p.id DESC
            LIMIT 1
        ) rp ON TRUE
    )
    SELECT user_id, COALESCE(is_system, FALSE) AS is_system, count(*) AS added
    FROM classified
    GROUP BY 1, 2
"""


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
    rows = (
        await db.execute(
            text(_SQL), {"since": since, "until": until, "client_id": client_id}
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
