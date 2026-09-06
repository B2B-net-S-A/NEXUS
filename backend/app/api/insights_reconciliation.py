"""Insights → uzgodnienie placementów: JEDEN wiersz na placement, obie rodziny.

PO CO
-----
Za rok 2026 aplikacja podaje cztery różne liczby placementów (Insights 213 ·
kafle 228 · nagłówek raportu 317 · suma wierszy TEGO SAMEGO raportu 332), a
Compass — z którego wypłacane są premie — ma ich 85. Dopóki nikt nie potrafi
pokazać, KTÓRE wiersze się różnią, każda rozmowa o premiach jest rozmową
o liczbach bez pokrycia.

Ten endpoint nie usuwa rozjazdu i nie ma tego robić. **Ma go wytłumaczyć** —
wiersz po wierszu, z jawną flagą przynależności do każdej rodziny.

DWIE RODZINY ISTNIEJĄ CELOWO
----------------------------
To nie jest jeden defekt, tylko dwa zjawiska, i tylko jedno z nich jest błędem.

* ``first_hired_per_candidate_job`` — widok ``analytics_first_milestones``,
  ZERO filtrów, atrybucja = ``first_moved_by`` (Insights, Hall of Fame).
* ``verifier_anchored_milestones`` — ``VERIFIER_ANCHORED_CTE``, filtry
  ``kpi_eligible``/``origin_kind``, atrybucja = ``credit_user_id``
  (kafle, raporty, wyścigi — czyli ta rodzina, która niesie pieniądze).

``dashboard_v2`` mówi o tej różnicy wprost: „to dwa różne pytania, nie rozjazd
do naprawy". Dlatego raport pokazuje OBIE i nie próbuje ich pogodzić.

CZTERY DECYZJE, KTÓRE TRZYMAJĄ TEN RAPORT UCZCIWYM
--------------------------------------------------
1. **FULL OUTER JOIN, nie INNER.** Cała wartość raportu siedzi w wierszach,
   które są w jednej rodzinie i nie ma ich w drugiej. INNER JOIN pokazałby
   wyłącznie część wspólną, czyli dokładnie to, o co nikt nie pyta.

2. **LEFT JOIN na ``jobs``/``clients``/``candidates``.** Placement pary, której
   oferta zniknęła z bazy, nadal jest placementem. ``/api/reports/recruitment``
   ma tu ``JOIN jobs`` i przez to gubi sieroty z OBU swoich liczb — a to jedna
   z przyczyn rozjazdu, którą ten raport ma pokazać, nie powtórzyć.

3. **Nie liczymy niczego na nowo.** Żadnego nowego kodu definicji, żadnej
   trzeciej reguły. Raport czyta te same dwa źródła co ekrany i podpisuje każdy
   wiersz kodem definicji z ``metric_definitions``. Nowa reguła zamieniłaby
   narzędzie do uzgadniania w piąty rozjeżdżający się wynik.

4. **Zero zapisu.** Ten moduł nie mutuje niczego. ``VERIFIER_ANCHORED_CTE``
   i ``_rank_recruiters_by_stage`` to jedyne dwie ścieżki, którymi ta praca
   mogłaby dotknąć pieniędzy — obie zostają nietknięte.
"""

import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.periods import PeriodError, resolve_period
from app.api.deps import CurrentUser
from app.api.section_access import INSIGHTS_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.services.kpi_panel import VERIFIER_ANCHORED_CTE
from app.services.metric_definitions import (
    FIRST_HIRED_PER_CANDIDATE_JOB,
    VERIFIER_ANCHORED_MILESTONES,
)

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=INSIGHTS_SECTION_DEPENDENCIES)

# Sufit wierszy. Rok 2026 ma ich ~330, więc 5000 mieści kilka lat z zapasem,
# a jednocześnie nie pozwala jednym żądaniem przeciągnąć całej historii.
_MAX_ROWS = 5000


# Obie rodziny sprowadzone do (candidate_id, job_id, reached_at, credit) i
# złączone FULL OUTER. `first_hired` czyta widok bez filtrów; `credited`
# pochodzi z CTE, więc niesie już własne filtry eligibility.
_RECONCILE_SQL = text(
    VERIFIER_ANCHORED_CTE
    + """
    , fh AS (
        SELECT fm.candidate_id, fm.job_id,
               fm.first_reached_at AS reached_at,
               fm.first_moved_by   AS actor_id
        FROM analytics_first_milestones fm
        WHERE fm.stage = 'hired'
          AND fm.first_reached_at >= :start
          AND fm.first_reached_at <  :end
    ), va AS (
        SELECT c.candidate_id, c.job_id,
               c.reached_at,
               c.credit_user AS actor_id
        FROM credited c
        WHERE c.stage = 'hired'
          AND c.reached_at >= :start
          AND c.reached_at <  :end
    ), joined AS (
        SELECT
            COALESCE(fh.candidate_id, va.candidate_id) AS candidate_id,
            COALESCE(fh.job_id, va.job_id)             AS job_id,
            (fh.candidate_id IS NOT NULL)              AS in_first_hired,
            (va.candidate_id IS NOT NULL)              AS in_verifier_anchored,
            fh.reached_at                              AS fh_reached_at,
            va.reached_at                              AS va_reached_at,
            fh.actor_id                                AS fh_actor_id,
            va.actor_id                                AS va_actor_id
        FROM fh
        FULL OUTER JOIN va
          ON va.candidate_id = fh.candidate_id
         AND va.job_id       = fh.job_id
    )
    SELECT
        j.candidate_id,
        j.job_id,
        j.in_first_hired,
        j.in_verifier_anchored,
        j.fh_reached_at,
        j.va_reached_at,
        j.fh_actor_id,
        j.va_actor_id,
        trim(concat_ws(' ', cand.name, cand.lastname)) AS candidate_name,
        job.title                                      AS job_title,
        cl.id                                          AS client_id,
        COALESCE(NULLIF(cl.display_name, ''), NULLIF(cl.name, '')) AS client_name,
        fhu.name                                       AS fh_actor_name,
        vau.name                                       AS va_actor_name
    FROM joined j
    LEFT JOIN candidates cand ON cand.id = j.candidate_id
    LEFT JOIN jobs job        ON job.id  = j.job_id
    LEFT JOIN clients cl      ON cl.id   = job.client_id
    LEFT JOIN users fhu       ON fhu.id  = j.fh_actor_id
    LEFT JOIN users vau       ON vau.id  = j.va_actor_id
    ORDER BY COALESCE(j.fh_reached_at, j.va_reached_at) DESC,
             j.candidate_id, j.job_id
    LIMIT :limit
    """
)


@router.get("/placements")
async def insights_placement_reconciliation(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    period: str = Query("year", pattern="^(day|week|month|quarter|year|custom)$"),
    offset: int = Query(0, description="0 = bieżący okres, -1 = poprzedni zamknięty"),
    anchor: date | None = Query(None, description="dowolny dzień wewnątrz okresu"),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
):
    """Lista placementów okna w obu rodzinach atrybucji, wiersz po wierszu.

    Każdy wiersz niesie ``in_first_hired`` i ``in_verifier_anchored``, więc
    trzy kubełki („w obu" / „tylko widok" / „tylko CTE") wychodzą z jednego
    przebiegu. Podsumowanie liczy też wiersze-sieroty — bez oferty, bez klienta
    i bez atrybucji — bo to one tłumaczą różnicę między nagłówkiem raportu
    a sumą jego własnych wierszy.
    """
    try:
        resolved = resolve_period(
            period,
            offset=offset,
            anchor=anchor,
            date_from=date_from,
            date_to=date_to,
        )
    except PeriodError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    rows = (
        (
            await db.execute(
                _RECONCILE_SQL,
                {
                    "start": resolved.start,
                    "end": resolved.end,
                    "limit": _MAX_ROWS,
                },
            )
        )
        .mappings()
        .all()
    )

    items = [
        {
            "candidate_id": r["candidate_id"],
            "candidate_name": r["candidate_name"] or None,
            "job_id": r["job_id"],
            "job_title": r["job_title"],
            "client_id": r["client_id"],
            "client_name": r["client_name"],
            "in_first_hired": bool(r["in_first_hired"]),
            "in_verifier_anchored": bool(r["in_verifier_anchored"]),
            "first_hired": {
                "reached_at": r["fh_reached_at"],
                "actor_id": r["fh_actor_id"],
                "actor_name": r["fh_actor_name"],
            },
            "verifier_anchored": {
                "reached_at": r["va_reached_at"],
                "actor_id": r["va_actor_id"],
                "actor_name": r["va_actor_name"],
            },
        }
        for r in rows
    ]

    both = sum(1 for i in items if i["in_first_hired"] and i["in_verifier_anchored"])
    only_fh = sum(
        1 for i in items if i["in_first_hired"] and not i["in_verifier_anchored"]
    )
    only_va = sum(
        1 for i in items if i["in_verifier_anchored"] and not i["in_first_hired"]
    )

    return {
        "period": {
            "period": period,
            "start": resolved.start,
            "end": resolved.end,
        },
        # Kody definicji SĄ tymi samymi stringami co na ekranach liczących
        # te rodziny. Własny wariant dałby maszynowo „inna reguła" tam, gdzie
        # reguła jest identyczna — czyli odwrotność tego, do czego to pole służy.
        "definitions": {
            "first_hired": FIRST_HIRED_PER_CANDIDATE_JOB,
            "verifier_anchored": VERIFIER_ANCHORED_MILESTONES,
        },
        "totals": {
            "first_hired": both + only_fh,
            "verifier_anchored": both + only_va,
            "in_both": both,
            "only_first_hired": only_fh,
            "only_verifier_anchored": only_va,
            # Sieroty liczone OSOBNO, bo to one tłumaczą, dlaczego nagłówek
            # raportu i suma jego wierszy się nie zgadzają.
            "without_job": sum(1 for i in items if i["job_id"] is None),
            "without_client": sum(1 for i in items if i["client_id"] is None),
            "without_actor_first_hired": sum(
                1
                for i in items
                if i["in_first_hired"] and i["first_hired"]["actor_id"] is None
            ),
            "without_actor_verifier_anchored": sum(
                1
                for i in items
                if i["in_verifier_anchored"]
                and i["verifier_anchored"]["actor_id"] is None
            ),
        },
        # Sufit osiągnięty = lista jest ucięta. Bez tej flagi obcięty raport
        # czyta się jak komplet, a raport do uzgadniania, który cicho gubi
        # wiersze, jest gorszy niż jego brak.
        "truncated": len(items) >= _MAX_ROWS,
        "items": items,
    }
