"""Nowe profile dodane do rekrutacji i ile z nich doszło do CV (teza B6, 08.11.2026).

„Danych o pracy na LinkedInie w NEXUSIE nie ma”, ale liczbę profili założonych
przez rekrutera pod daną rekrutację da się policzyć. Definicja z pomiaru audytu
(karty od 12.10: nowe profile 62% do CV, karty z bazy dodane przez człowieka
11,5%, portale 28%). Karta jest nowym profilem, gdy:

* pierwszy wiersz pary (kandydat, rekrutacja) dodał człowiek (``moved_by``),
* kandydat powstał najwyżej dzień przed pierwszą kartą,
* to nie zgłoszenie z ogłoszenia ani z portalu (etap ``posting``, źródło
  ``pracuj``/``jjit``, zdarzenie źródła w okolicy karty) i nie polecenie.

„Doszło do CV” = para ma etap „CV wysłane”, także gdy poszło dalej lub odpadła.
Ostrożnie przy czytaniu: rekruter zakłada profil zwykle po dobrej rozmowie,
więc część odsetka to efekt doboru, a nie kanału.

Podział na osoby (16.11.2026, Daily): liczba idzie do osoby z pierwszego wiersza
pary (``first_by``), tej samej, która decyduje, że karta w ogóle się liczy, więc
suma osób równa się liczbie rekrutacji. Zasady:
docs/claude/rekrutacja-tablica/kto-ilu-dodal-w-zespole-rekrutacji.md
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_today, local_day_start_utc

# Dziś i sześć poprzednich dni: tydzień kalendarzowy w poniedziałek rano na
# Daily dawałby same zera.
NEW_PROFILES_WINDOW_DAYS = 7
PORTAL_SOURCES = ("pracuj", "jjit")
PORTAL_UTM_SOURCES = ("pracuj", "pracuj_pl", "jjit", "justjoinit", "rocketjobs")

_SQL = text(
    """
    WITH pair AS (
        SELECT cs.candidate_id,
               cs.job_id,
               min(cs.moved_at) AS first_at,
               (array_agg(cs.moved_by ORDER BY cs.moved_at, cs.id))[1] AS first_by,
               bool_or(cs.stage::text = 'posting') AS posting,
               bool_or(cs.stage::text = 'cv_sent') AS reached_cv
        FROM candidate_stages cs
        WHERE cs.job_id = ANY(CAST(:job_ids AS integer[]))
        GROUP BY cs.candidate_id, cs.job_id
        HAVING min(cs.moved_at) >= :since
    )
    SELECT pair.job_id,
           pair.first_by,
           u.name,
           count(*) AS added,
           count(*) FILTER (WHERE pair.reached_cv) AS reached_cv
    FROM pair
    JOIN candidates c ON c.id = pair.candidate_id
    LEFT JOIN users u ON u.id = pair.first_by
    WHERE pair.first_by IS NOT NULL
      AND NOT pair.posting
      AND c.created_at >= pair.first_at - interval '1 day'
      AND COALESCE(c.source, '') <> ALL(CAST(:excluded_sources AS text[]))
      AND NOT EXISTS (
          SELECT 1
          FROM candidate_source_events e
          WHERE e.candidate_id = pair.candidate_id
            AND (
                e.channel::text = 'referral'
                OR (
                    (e.channel::text = 'posting' OR e.utm_source = ANY(CAST(:portal_utm AS text[])))
                    AND e.captured_at
                        BETWEEN pair.first_at - interval '3 days'
                            AND pair.first_at + interval '1 day'
                )
            )
      )
    GROUP BY pair.job_id, pair.first_by, u.name
    """
)


@dataclass(frozen=True)
class NewProfilesBy:
    user_id: int
    name: str | None
    added: int
    reached_cv: int


@dataclass(frozen=True)
class NewProfiles:
    added: int = 0
    reached_cv: int = 0
    # Od największej liczby; suma ``added`` równa się ``added`` rekrutacji.
    by_user: tuple[NewProfilesBy, ...] = ()


def window_start(today: date) -> datetime:
    return local_day_start_utc(today - timedelta(days=NEW_PROFILES_WINDOW_DAYS - 1))


async def new_profiles_by_job(
    db: AsyncSession, job_ids: Iterable[int], *, today: date | None = None
) -> dict[int, NewProfiles]:
    ids: Sequence[int] = sorted(set(job_ids))
    if not ids:
        return {}
    rows = (
        await db.execute(
            _SQL,
            {
                "job_ids": list(ids),
                "since": window_start(today or business_today()),
                "excluded_sources": ["referral", *PORTAL_SOURCES],
                "portal_utm": list(PORTAL_UTM_SOURCES),
            },
        )
    ).all()
    people: dict[int, list[NewProfilesBy]] = {}
    for job_id, user_id, name, added, reached_cv in rows:
        people.setdefault(job_id, []).append(
            NewProfilesBy(
                user_id=int(user_id),
                name=name,
                added=int(added),
                reached_cv=int(reached_cv),
            )
        )
    return {
        job_id: NewProfiles(
            added=sum(p.added for p in found),
            reached_cv=sum(p.reached_cv for p in found),
            by_user=tuple(
                sorted(
                    found, key=lambda p: (-p.added, (p.name or "").lower(), p.user_id)
                )
            ),
        )
        for job_id, found in people.items()
    }
