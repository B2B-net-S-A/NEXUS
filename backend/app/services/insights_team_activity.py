"""Ranking aktywności zespołu — jedna implementacja dla dwóch powierzchni.

Moduł powstał, bo `/api/activities/leaderboard` (capability
``VIEW_RECRUITMENT_RANKING``) i nowy `/api/insights/recruitment/team-activity`
(D7: każdy zalogowany) muszą pokazywać TE SAME liczby. Jedynym sposobem na to
jest jedno zapytanie, nie dwa podobne — kopia SQL rozjeżdża się cicho, bo obie
odpowiedzi wyglądają wiarygodnie i nikt ich obok siebie nie kładzie.

Trzy rzeczy, które ten moduł ŚWIADOMIE zostawia routerom:

1. **Guard.** ``capabilities.py`` steruje 40+ innymi powierzchniami; jego
   poszerzenie otworzyłoby imienne rankingi wszędzie tam, gdzie nikt na to nie
   dawał zgody. Dlatego bramka zostaje w routerze, a tutaj jest wyłącznie
   liczenie.

2. **Górna granica okna.** ``until=None`` odtwarza kroczące okno legacy
   (``now - 30 dni`` BEZ sufitu), a ``until=period.end`` daje półotwarte
   ``[start, end)`` z ``resolve_period``. Gdyby serwis narzucił jedną z tych
   semantyk, druga powierzchnia zmieniłaby liczby bez zmiany kodu u siebie.

3. **Procenty.** Legacy liczy je ``_safe_pct`` (zero przy zerowym mianowniku),
   Insights ``_ratio`` (``None``). Serwis zwraca WYŁĄCZNIE surowe liczniki,
   więc żadna z tych konwencji nie wycieka do drugiej powierzchni.

Skąd biorą się kolumny (runda 10, R10-N2-1). Do 27.09.2026 cztery kolumny
sumowały typy ``user_activities`` (``screening_done``, ``interview_scheduled``,
``placement_closed``, ``call_made``), których NIC w kodzie nie zapisywało —
tabela pokazywała stałe zera, a wiersz kont administracyjnych mówił
„0 placementów” obok tabeli Zespołu z trzydziestoma. Teraz każda kolumna
czyta swoje prawdziwe źródło:

- **Kandydaci** — ``user_activities.candidate_added`` (to jest zapisywane),
- **Screeningi** — zapisane arkusze screeningu (``activities.action =
  'screening_answered'``, jeden etap = jeden screening, ponowny zapis tego
  samego arkusza się nie dubluje),
- **Rozmowy** — rozmowy u klienta: pierwsze wejście pary na etap
  ``client_interview`` przypisane osobie, która je przesunęła
  (``analytics_first_milestones.first_moved_by``) — ta sama reguła co
  kolumna „Rozmowy u klienta” w „Performance per osoba” (``insights_team``),
- **Placementy** — D2: pierwsze ``hired`` pary po ``first_moved_by``,
  identycznie jak „Performance per osoba” obok (wykluczone placementy
  odpadają w widoku),
- **Telefony** — wiersze ``calls`` osoby (czas rozmowy, a bez niego zapisu).

**Razem** = czynności wykonane w NEXUSIE: wiersze ``user_activities``
(kandydaci, ruchy etapów, notatki, CV, czat) + zapisane screeningi +
telefony. Rozmowy i placementy NIE wchodzą do sumy: ruch wykonany w NEXUSIE
jest już policzony jako ``stage_changed``, a ruch z importu Traffita nie jest
czynnością w NEXUSIE.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

__all__ = ["TeamActivityRow", "compute_team_activity"]


@dataclass(frozen=True)
class TeamActivityRow:
    """Jeden wiersz rankingu — liczniki bez żadnej pochodnej."""

    user_id: int
    user_name: str
    candidates_added: int
    screenings: int
    interviews: int
    placements: int
    calls: int
    total_actions: int


def _window(column: str, *, bounded: bool) -> str:
    clause = f"{column} >= :since"
    if bounded:
        clause += f" AND {column} < :until"
    return clause


async def compute_team_activity(
    db: AsyncSession,
    *,
    since: datetime,
    until: datetime | None = None,
    limit: int,
) -> list[TeamActivityRow]:
    """Ranking aktywności per użytkownik, malejąco po sumie akcji.

    Args:
        since: dolna granica okna (włącznie).
        until: górna granica WYŁĄCZNIE (półotwarte ``[since, until)``).
            ``None`` = brak sufitu, czyli kroczące okno legacy. To NIE jest
            szczegół techniczny: bez górnej granicy „poprzedni miesiąc" znaczy
            w praktyce „od poprzedniego miesiąca do dziś".
        limit: ilu użytkowników zwrócić.
    """
    bounded = until is not None
    sql = f"""
        WITH ua AS (
            SELECT user_id,
                   count(*) FILTER (
                       WHERE action_type::text = 'candidate_added'
                   ) AS candidates_added,
                   count(*) AS ua_total
            FROM user_activities
            WHERE {_window("created_at", bounded=bounded)}
            GROUP BY user_id
        ),
        scr AS (
            SELECT user_id, count(DISTINCT entity_id) AS screenings
            FROM activities
            WHERE action = 'screening_answered'
              AND entity_type = 'candidate_stage'
              AND user_id IS NOT NULL
              AND {_window("created_at", bounded=bounded)}
            GROUP BY user_id
        ),
        ms AS (
            SELECT first_moved_by AS user_id,
                   count(*) FILTER (
                       WHERE stage::text = 'client_interview'
                   ) AS interviews,
                   count(*) FILTER (WHERE stage::text = 'hired') AS placements
            FROM analytics_first_milestones
            WHERE first_moved_by IS NOT NULL
              AND stage::text IN ('client_interview', 'hired')
              AND {_window("first_reached_at", bounded=bounded)}
            GROUP BY first_moved_by
        ),
        cl AS (
            SELECT user_id, count(*) AS calls
            FROM calls
            WHERE user_id IS NOT NULL
              AND {_window("COALESCE(started_at, created_at)", bounded=bounded)}
            GROUP BY user_id
        ),
        ids AS (
            SELECT user_id FROM ua
            UNION SELECT user_id FROM scr
            UNION SELECT user_id FROM ms
            UNION SELECT user_id FROM cl
        )
        SELECT u.id,
               u.name,
               COALESCE(ua.candidates_added, 0) AS candidates_added,
               COALESCE(scr.screenings, 0)      AS screenings,
               COALESCE(ms.interviews, 0)       AS interviews,
               COALESCE(ms.placements, 0)       AS placements,
               COALESCE(cl.calls, 0)            AS calls,
               COALESCE(ua.ua_total, 0)
                 + COALESCE(scr.screenings, 0)
                 + COALESCE(cl.calls, 0)        AS total_actions
        FROM ids
        JOIN users u ON u.id = ids.user_id
        LEFT JOIN ua  ON ua.user_id  = ids.user_id
        LEFT JOIN scr ON scr.user_id = ids.user_id
        LEFT JOIN ms  ON ms.user_id  = ids.user_id
        LEFT JOIN cl  ON cl.user_id  = ids.user_id
        ORDER BY total_actions DESC,
                 COALESCE(ms.placements, 0) DESC,
                 u.id
        LIMIT :limit
    """
    params: dict = {"since": since, "limit": limit}
    if bounded:
        params["until"] = until

    rows = (await db.execute(text(sql), params)).mappings().all()

    return [
        TeamActivityRow(
            user_id=int(r["id"]),
            user_name=r["name"],
            candidates_added=int(r["candidates_added"] or 0),
            screenings=int(r["screenings"] or 0),
            interviews=int(r["interviews"] or 0),
            placements=int(r["placements"] or 0),
            calls=int(r["calls"] or 0),
            total_actions=int(r["total_actions"] or 0),
        )
        for r in rows
    ]
