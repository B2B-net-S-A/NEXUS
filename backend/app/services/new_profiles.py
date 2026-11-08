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
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import bindparam, text
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
        WHERE cs.job_id IN :job_ids
        GROUP BY cs.candidate_id, cs.job_id
        HAVING min(cs.moved_at) >= :since
    )
    SELECT pair.job_id,
           count(*) AS added,
           count(*) FILTER (WHERE pair.reached_cv) AS reached_cv
    FROM pair
    JOIN candidates c ON c.id = pair.candidate_id
    WHERE pair.first_by IS NOT NULL
      AND NOT pair.posting
      AND c.created_at >= pair.first_at - interval '1 day'
      AND COALESCE(c.source, '') NOT IN :excluded_sources
      AND NOT EXISTS (
          SELECT 1
          FROM candidate_source_events e
          WHERE e.candidate_id = pair.candidate_id
            AND (
                e.channel::text = 'referral'
                OR (
                    (e.channel::text = 'posting' OR e.utm_source IN :portal_utm)
                    AND e.captured_at
                        BETWEEN pair.first_at - interval '3 days'
                            AND pair.first_at + interval '1 day'
                )
            )
      )
    GROUP BY pair.job_id
    """
).bindparams(
    bindparam("job_ids", expanding=True),
    bindparam("excluded_sources", expanding=True),
    bindparam("portal_utm", expanding=True),
)


@dataclass(frozen=True)
class NewProfiles:
    added: int = 0
    reached_cv: int = 0


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
                "job_ids": ids,
                "since": window_start(today or business_today()),
                "excluded_sources": ("referral", *PORTAL_SOURCES),
                "portal_utm": PORTAL_UTM_SOURCES,
            },
        )
    ).all()
    return {
        job_id: NewProfiles(added=int(added), reached_cv=int(reached_cv))
        for job_id, added, reached_cv in rows
    }
