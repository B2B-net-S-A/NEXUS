"""Insights → Delivery Lead (Body Leasing): ranking, trend, placementy per klient.

Następca `GET /api/reports/delivery-leads` (+ `/{id}/trend`). Tamte trasy
ZOSTAJĄ nietknięte — mają własny, węższy guard (admin + HoR + finance) i
własnego konsumenta (`frontend/src/lib/api.ts:837`). Decyzja D7 otwiera
`/insights`, nie każdą trasę, która akurat liczy to samo.

Sześć decyzji, które trzymają ten moduł uczciwym:

1. **Guard to `CurrentUser` i nic więcej** (D7, plan §0). Kwoty nie są
   redagowane, bo ten moduł ich nie zwraca; ale nawet gdyby zwracał —
   NIE zastępuj tego guardu capability. `VIEW_FINANCE` steruje 40+ innymi
   powierzchniami (`app/analytics/capabilities.py:64-115`), więc jego
   poszerzenie wyciekłoby stawki konsultantów daleko poza Insights.

2. **Placement = definicja D2**: PIERWSZY `hired` per para (kandydat, oferta),
   czyli wiersz widoku `analytics_first_milestones`. Legacy `_compute_dl_metrics`
   (`reports.py:731-758`) liczył KAŻDY wiersz `candidate_stages.stage='hired'`,
   więc para z dwoma podejściami procesowymi wchodziła do rankingu dwa razy.
   Jedna definicja wszędzie — także w mianowniku wolnych wakatów.

3. **Trend: każdy miesiąc ma WŁASNE okno półotwarte [start, end).**
   `report_delivery_lead_trend` (`reports.py:898-945`) liczy koniec miesiąca
   i **wyrzuca go** (dwa nagie `datetime(...)` bez przypisania, `:911-915`),
   więc każdy „miesiąc" jest skumulowanym ogonem do dziś. Wykres wychodzi
   monotonicznie malejący i czyta się jak zapaść wydajności DL. Granice
   miesięcy liczy tu `resolve_period` — jedyna przetestowana arytmetyka okien
   w repo (DST, rok przestępny). Świadomie NIE `generate_series(... '1 month')`
   po stronie Postgresa: krok miesięczny na `timestamptz` liczy się w strefie
   SESJI (u nas UTC), więc od marca w górę rozjeżdża się o godziny DST.

4. **Zerowy mianownik to `None`, nigdy `0.0`** — i `target_achieved` też jest
   wtedy `None`, nie `False`. Legacy `_safe_pct` zwracało 0.0, więc DL z pięcioma
   placementami i zerem nowych zapytań w oknie renderował się jako „poniżej
   progu". Pod D7 taki wiersz widzi cała firma. Procentów NIE przycinamy do
   100: hit ratio > 100% znaczy, że placementy pochodzą z zapytań spoza okna,
   i ma to być widoczne, nie schowane.

5. **Placementy bez rozpoznanego DL idą do `unattributed` OBOK rankingu**,
   nigdy do czyjegoś wiersza (wzorzec `app/services/kpi_team.py:117,196-204`).
   Bez tego suma wierszy po cichu nie zgadza się z lejkiem i nikt nie wie dlaczego.

6. **Nie filtrujemy po `users.is_active`.** Konta DL w NEXUSIE bywają nieaktywne
   (plan §1.3), więc filtr zwróciłby pusty ranking. Wiersz niesie `is_active`
   jako flagę — historia firmy nie może się zmieniać od przestawienia flagi konta.

Ograniczenie do świadomego przeczytania, nie do ukrycia: **hit ratio miesza
kohorty**. Licznik to placementy OSIĄGNIĘTE w oknie, mianownik to zapytania
UTWORZONE w oknie — placement zwykle domyka zapytanie starsze niż okno. Tak
liczył oryginał (InfraReporter) i tak zostaje, żeby liczby dały się porównać
z historią; koperta niesie `hit_ratio_is_cross_cohort`, żeby konsument mógł
to napisać przy kaflu.
"""

import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.periods import Period, PeriodError, resolve_period
from app.api.deps import CurrentUser
from app.api.section_access import INSIGHTS_SECTION_DEPENDENCIES
from app.core.cache import cache_get, cache_set
from app.core.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=INSIGHTS_SECTION_DEPENDENCIES)

# Nazwa klienta i widocznosc — LUSTRO `app/services/client_identity.py`
# w surowym SQL-u (te zapytania sa tekstowe, wiec nie moga wolac helperow ORM).
#
# Bez tego ten sam klient wystepowalby na jednym ekranie pod DWIEMA nazwami:
# zakladka Klienci uzywa `client_display_name_expression()` (czyli recznej
# korekty nazwy z Traffita), a Delivery Lead pokazywalby surowe `clients.name`.
# Gorzej z `merged_into_client_id`: klient wchloniety w innego wciaz ma wlasne
# wiersze `jobs`, wiec renderowalby sie jako osobny kawalek donuta, podczas gdy
# Klienci juz go zwineli — dwoch sum nie dalo by sie uzgodnic wzrokiem.
_CLIENT_DISPLAY_NAME_SQL = "COALESCE(NULLIF(BTRIM(c.display_name), ''), c.name)"
_CLIENT_VISIBLE_SQL = (
    "c.hidden IS FALSE AND c.archived_at IS NULL AND c.merged_into_client_id IS NULL"
)


CACHE_TTL_SECONDS = 300

# Próg wejścia do „Ligi Mistrzów DL" (InfraReporter). Ta sama wartość co
# `reports.HIT_RATIO_TARGET_PCT` — powielona świadomie, bo import z `reports`
# wciągnąłby tamten moduł (z jego guardami) w zależności /insights.
HIT_RATIO_TARGET_PCT = 30.0

# Ranking DL dotyczy WYŁĄCZNIE ofert body_leasing — `sales_project` i `tender`
# mają inny cykl życia i nie mają Delivery Leada. Konsekwencja: liczby nie
# zsumują się do lejka org-level, który typu nie filtruje. Koperta to mówi.
RECRUITMENT_TYPE = "body_leasing"

# Rozwiązanie DL dla oferty: własny `delivery_lead_id`, a gdy pusty — główny
# opiekun klienta (`is_head`). Jedno źródło dla wszystkich trzech zapytań.
_DL_HEAD_CTE = """
    dl_head AS (
        SELECT client_id, delivery_lead_user_id
        FROM delivery_lead_client_assignments
        WHERE is_head IS TRUE
    )
"""

_JOBS_SCOPED_CTE = f"""
    jobs_scoped AS (
        SELECT j.id,
               j.created_at,
               j.status,
               j.client_id,
               COALESCE(j.headcount, 1) AS headcount,
               COALESCE(j.delivery_lead_id, h.delivery_lead_user_id) AS dl_id
        FROM jobs j
        LEFT JOIN dl_head h ON h.client_id = j.client_id
        WHERE j.recruitment_type = '{RECRUITMENT_TYPE}'
    )
"""


def _ratio(numerator: int, denominator: int) -> float | None:
    """Udział procentowy albo ``None`` przy zerowym mianowniku.

    NIE zwraca 0.0 — konsument musi móc odróżnić „policzone, wyszło zero" od
    „nie było czego dzielić". Bez przycinania do 100%: wynik powyżej stu
    procent jest realnym sygnałem (placementy z zapytań spoza okna).
    """
    if denominator <= 0:
        return None
    return round(numerator / denominator * 100, 1)


def _resolve(kind: str, offset: int, anchor: date | None, date_from, date_to) -> Period:
    try:
        return resolve_period(
            kind, offset=offset, anchor=anchor, date_from=date_from, date_to=date_to
        )
    except PeriodError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


@router.get("")
async def insights_delivery_leads(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    period: str = Query("month", pattern="^(day|week|month|quarter|year|custom)$"),
    offset: int = Query(0, description="0 = bieżący okres, -1 = poprzedni zamknięty"),
    anchor: date | None = Query(None, description="dowolny dzień wewnątrz okresu"),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
):
    """Ranking Delivery Leadów w oknie: zapytania, wakaty, placementy, hit ratio.

    Dostępne dla KAŻDEGO zalogowanego (decyzja D7). Zero redakcji.
    """
    resolved = _resolve(period, offset, anchor, date_from, date_to)

    # Klucz NIESIE OKNO. Bez tego liczby jednego okresu wyszłyby pod etykietą
    # drugiego — i nikt by się nie dowiedział, bo obie są wiarygodne.
    cache_key = f"insights:delivery-leads:v1:{resolved.cache_suffix}"
    cached = await cache_get(cache_key)
    if cached is not None:
        return cached

    params = {"start": resolved.start, "end": resolved.end}

    # 1. Zapytania i wakaty — oferty body_leasing UTWORZONE w oknie.
    demand_rows = (
        (
            await db.execute(
                text(
                    f"""
                WITH {_DL_HEAD_CTE}, {_JOBS_SCOPED_CTE}
                SELECT js.dl_id AS dl_id,
                       count(*) AS requests,
                       COALESCE(SUM(js.headcount), 0) AS vacancies,
                       ARRAY_REMOVE(
                           ARRAY_AGG(DISTINCT {_CLIENT_DISPLAY_NAME_SQL}), NULL
                       ) AS clients
                FROM jobs_scoped js
                LEFT JOIN clients c
                  ON c.id = js.client_id AND {_CLIENT_VISIBLE_SQL}
                WHERE js.created_at >= :start AND js.created_at < :end
                GROUP BY js.dl_id
                """
                ),
                params,
            )
        )
        .mappings()
        .all()
    )

    # 2. Placementy — D2: pierwszy `hired` per (kandydat, oferta). JOIN na
    #    `jobs` jest tu KONIECZNY (typ rekrutacji + atrybucja DL siedzą na
    #    ofercie), więc placement oferty skasowanej wypada z rankingu w całości
    #    — także z `unattributed`. Skasowanie oferty jest w NEXUSIE rzadkie
    #    i nieodwracalne; alternatywy (osobne zapytanie bez JOIN-a) nie ma,
    #    bo bez oferty nie da się orzec, czy to w ogóle było body leasing.
    placement_rows = (
        (
            await db.execute(
                text(
                    f"""
                WITH {_DL_HEAD_CTE}, {_JOBS_SCOPED_CTE}
                SELECT js.dl_id AS dl_id, count(*) AS placements
                FROM analytics_first_milestones fm
                JOIN jobs_scoped js ON js.id = fm.job_id
                WHERE fm.stage = 'hired'
                  AND fm.first_reached_at >= :start
                  AND fm.first_reached_at < :end
                GROUP BY js.dl_id
                """
                ),
                params,
            )
        )
        .mappings()
        .all()
    )

    # 3. Otwarty pipeline — SNAPSHOT „na teraz", świadomie BEZ filtra okna.
    #    Otwarte zapytanie nie ma daty zamknięcia, więc przycięcie go do okna
    #    dałoby liczbę, która niczego nie opisuje. Koperta oznacza to jawnie.
    #    Skutek do świadomego przyjęcia: DL, który ma tylko otwarte oferty,
    #    pojawia się w KAŻDYM oknie z zerami w kolumnach okresu. Dlatego jego
    #    `hit_ratio` i `target_achieved` są `None`, a nie 0.0/False — wiersz ma
    #    czytać się „nie ma czego oceniać", nie „nic nie dowiózł".
    open_rows = (
        (
            await db.execute(
                text(
                    f"""
                WITH {_DL_HEAD_CTE}, {_JOBS_SCOPED_CTE},
                open_jobs AS (
                    SELECT js.id, js.dl_id, js.headcount
                    FROM jobs_scoped js
                    WHERE js.status IN ('draft', 'published')
                ),
                filled AS (
                    SELECT fm.job_id, count(*) AS cnt
                    FROM analytics_first_milestones fm
                    JOIN open_jobs oj ON oj.id = fm.job_id
                    WHERE fm.stage = 'hired'
                    GROUP BY fm.job_id
                )
                SELECT oj.dl_id AS dl_id,
                       count(*) AS open_requests,
                       COALESCE(
                           SUM(GREATEST(oj.headcount - COALESCE(f.cnt, 0), 0)), 0
                       ) AS open_vacancies
                FROM open_jobs oj
                LEFT JOIN filled f ON f.job_id = oj.id
                GROUP BY oj.dl_id
                """
                )
            )
        )
        .mappings()
        .all()
    )

    demand = {r["dl_id"]: r for r in demand_rows}
    placements = {r["dl_id"]: int(r["placements"]) for r in placement_rows}
    open_pipeline = {r["dl_id"]: r for r in open_rows}

    dl_ids = {
        key
        for key in (set(demand) | set(placements) | set(open_pipeline))
        if key is not None
    }

    # Nazwy i flaga aktywności. NIE filtrujemy po `is_active` — konta DL bywają
    # nieaktywne, a filtr zwróciłby pusty ranking (plan §1.3).
    name_map: dict[int, dict] = {}
    if dl_ids:
        user_rows = (
            (
                await db.execute(
                    text(
                        """
                    SELECT u.id, u.name, u.is_active
                    FROM users u
                    WHERE u.id = ANY(CAST(:ids AS integer[]))
                    """
                    ),
                    {"ids": sorted(dl_ids)},
                )
            )
            .mappings()
            .all()
        )
        name_map = {int(r["id"]): dict(r) for r in user_rows}

    per_dl: list[dict] = []
    for dl_id in dl_ids:
        d = demand.get(dl_id)
        requests = int(d["requests"]) if d else 0
        vacancies = int(d["vacancies"] or 0) if d else 0
        placed = placements.get(dl_id, 0)
        op = open_pipeline.get(dl_id)
        hit_ratio = _ratio(placed, requests)
        user = name_map.get(dl_id)
        per_dl.append(
            {
                "user_id": dl_id,
                "name": (user or {}).get("name") or f"User {dl_id}",
                "is_active": bool((user or {}).get("is_active", False)),
                "total_requests": requests,
                "total_vacancies": vacancies,
                "placements": placed,
                "hit_ratio": hit_ratio,
                "fill_rate": _ratio(placed, vacancies),
                "avg_vacancies_per_request": (
                    round(vacancies / requests, 2) if requests else None
                ),
                "open_requests": int(op["open_requests"]) if op else 0,
                "open_vacancies": int(op["open_vacancies"] or 0) if op else 0,
                # None, nie False — „nie da się ocenić" to co innego niż
                # „oceniono i nie osiągnął". Pod D7 widzi to cała firma.
                "target_achieved": (
                    None if hit_ratio is None else hit_ratio >= HIT_RATIO_TARGET_PCT
                ),
                "clients": sorted(list(d["clients"]) if d and d["clients"] else []),
            }
        )

    per_dl.sort(
        key=lambda row: (-row["placements"], -row["total_requests"], row["name"])
    )

    total_requests = sum(r["total_requests"] for r in per_dl)
    total_vacancies = sum(r["total_vacancies"] for r in per_dl)
    total_placements = sum(r["placements"] for r in per_dl)
    assessable = [r["hit_ratio"] for r in per_dl if r["hit_ratio"] is not None]

    result = {
        "period": resolved.as_payload(),
        "recruitment_type": RECRUITMENT_TYPE,
        "hit_ratio_target_pct": HIT_RATIO_TARGET_PCT,
        # Otwarty pipeline nie jest liczony w oknie — patrz zapytanie 3.
        "open_pipeline_scope": "snapshot_now",
        # Licznik i mianownik hit ratio pochodzą z różnych kohort — do napisania
        # przy kaflu, nie do przemilczenia.
        "hit_ratio_is_cross_cohort": True,
        "per_dl": per_dl,
        "overall": {
            "dl_count": len(per_dl),
            "total_requests": total_requests,
            "total_vacancies": total_vacancies,
            "total_placements": total_placements,
            "total_open_requests": sum(r["open_requests"] for r in per_dl),
            "total_open_vacancies": sum(r["open_vacancies"] for r in per_dl),
            # Agregat (suma/suma) — odporny na paradoks Simpsona.
            "hit_ratio": _ratio(total_placements, total_requests),
            "fill_rate": _ratio(total_placements, total_vacancies),
            # Średnia z wierszy, liczona TYLKO po tych, które mają mianownik.
            "avg_hit_ratio": (
                round(sum(assessable) / len(assessable), 1) if assessable else None
            ),
            "dl_with_hit_ratio": len(assessable),
            "not_assessable_count": len(per_dl) - len(assessable),
            "target_count": sum(1 for r in per_dl if r["target_achieved"]),
        },
        # Org-level, NIGDY w czyimś wierszu: oferta bez `delivery_lead_id`,
        # której klient nie ma głównego opiekuna.
        "unattributed": {
            "requests": int(demand[None]["requests"]) if None in demand else 0,
            "vacancies": (int(demand[None]["vacancies"] or 0) if None in demand else 0),
            "placements": placements.get(None, 0),
            "open_requests": (
                int(open_pipeline[None]["open_requests"])
                if None in open_pipeline
                else 0
            ),
        },
    }
    await cache_set(cache_key, result, ttl_seconds=CACHE_TTL_SECONDS)
    return result


@router.get("/placements-by-client")
async def insights_dl_placements_by_client(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    period: str = Query("month", pattern="^(day|week|month|quarter|year|custom)$"),
    offset: int = Query(0),
    anchor: date | None = Query(None),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
):
    """Placementy per klient w oknie — źródło donuta na zakładce Delivery Lead.

    Świadomie NIE czytamy `/api/reports/clients`: tam placement to KAŻDY wiersz
    `hired` i tylko dla ofert zamkniętych (`reports.py:1080-1098`), czyli inna
    definicja niż D2. Dwie definicje na jednym ekranie dają dwie różne sumy pod
    tą samą etykietą.
    """
    resolved = _resolve(period, offset, anchor, date_from, date_to)

    cache_key = f"insights:delivery-leads-by-client:v1:{resolved.cache_suffix}"
    cached = await cache_get(cache_key)
    if cached is not None:
        return cached

    rows = (
        (
            await db.execute(
                text(
                    f"""
                SELECT j.client_id AS client_id,
                       {_CLIENT_DISPLAY_NAME_SQL} AS client_name,
                       count(*) AS placements
                FROM analytics_first_milestones fm
                JOIN jobs j ON j.id = fm.job_id
                LEFT JOIN clients c
                  ON c.id = j.client_id AND {_CLIENT_VISIBLE_SQL}
                WHERE fm.stage = 'hired'
                  AND fm.first_reached_at >= :start
                  AND fm.first_reached_at < :end
                  AND j.recruitment_type = '{RECRUITMENT_TYPE}'
                GROUP BY j.client_id, {_CLIENT_DISPLAY_NAME_SQL}
                ORDER BY placements DESC, {_CLIENT_DISPLAY_NAME_SQL} ASC
                """
                ),
                {"start": resolved.start, "end": resolved.end},
            )
        )
        .mappings()
        .all()
    )

    total = sum(int(r["placements"]) for r in rows)
    result = {
        "period": resolved.as_payload(),
        "recruitment_type": RECRUITMENT_TYPE,
        "total_placements": total,
        "clients": [
            {
                "client_id": r["client_id"],
                # Brak nazwy renderujemy jawnie — pusty podpis w donucie
                # czyta się jak błąd wykresu, nie jak lukę w danych.
                "client_name": r["client_name"] or "(bez klienta)",
                "placements": int(r["placements"]),
                "share_pct": _ratio(int(r["placements"]), total),
            }
            for r in rows
        ],
    }
    await cache_set(cache_key, result, ttl_seconds=CACHE_TTL_SECONDS)
    return result


@router.get("/{dl_id}/trend")
async def insights_delivery_lead_trend(
    dl_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    months: int = Query(6, ge=1, le=24),
    anchor: date | None = Query(
        None, description="dowolny dzień OSTATNIEGO miesiąca serii (domyślnie dziś)"
    ),
):
    """Trend miesiąc po miesiącu dla jednego DL — każdy miesiąc W SWOIM oknie.

    To jest naprawa `reports.py:898-945`, gdzie górna granica miesiąca była
    liczona i wyrzucana, przez co seria była KUMULATYWNA (każdy punkt = ogon
    do dziś) i z definicji malejąca. Tutaj granice miesięcy pochodzą
    z `resolve_period`, a SQL filtruje `>= m_start AND < m_end`.
    """
    try:
        windows = [
            resolve_period("month", offset=-i, anchor=anchor)
            for i in range(months - 1, -1, -1)
        ]
    except PeriodError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    # Klucz niesie CAŁĄ rozpiętość serii: pierwsze i ostatnie okno. Sam `months`
    # nie wystarcza — dwie serie o tej samej długości i różnej kotwicy dzieliłyby
    # klucz i jedna wyszłaby pod etykietą drugiej.
    cache_key = (
        f"insights:delivery-lead-trend:v1:{dl_id}:"
        f"{windows[0].cache_suffix}:{windows[-1].cache_suffix}"
    )
    cached = await cache_get(cache_key)
    if cached is not None:
        return cached

    # Bind params generujemy sami (indeks pętli), więc nie ma tu wejścia
    # użytkownika w treści SQL — `months` jest ograniczone przez Query(le=24).
    months_sql = " UNION ALL ".join(
        f"SELECT {i} AS idx, CAST(:s{i} AS timestamptz) AS m_start, "
        f"CAST(:e{i} AS timestamptz) AS m_end"
        for i in range(len(windows))
    )
    params: dict = {"dl_id": dl_id}
    for i, window in enumerate(windows):
        params[f"s{i}"] = window.start
        params[f"e{i}"] = window.end

    rows = (
        (
            await db.execute(
                text(
                    f"""
                WITH {_DL_HEAD_CTE}, {_JOBS_SCOPED_CTE},
                months AS ({months_sql})
                SELECT m.idx AS idx, d.requests, d.vacancies, p.placements
                FROM months m
                LEFT JOIN LATERAL (
                    SELECT count(*) AS requests,
                           COALESCE(SUM(js.headcount), 0) AS vacancies
                    FROM jobs_scoped js
                    WHERE js.dl_id = :dl_id
                      AND js.created_at >= m.m_start
                      AND js.created_at < m.m_end
                ) d ON TRUE
                LEFT JOIN LATERAL (
                    SELECT count(*) AS placements
                    FROM analytics_first_milestones fm
                    JOIN jobs_scoped js ON js.id = fm.job_id
                    WHERE js.dl_id = :dl_id
                      AND fm.stage = 'hired'
                      AND fm.first_reached_at >= m.m_start
                      AND fm.first_reached_at < m.m_end
                ) p ON TRUE
                ORDER BY m.idx
                """
                ),
                params,
            )
        )
        .mappings()
        .all()
    )
    by_idx = {int(r["idx"]): r for r in rows}

    trend = []
    for i, window in enumerate(windows):
        row = by_idx.get(i)
        requests = int(row["requests"]) if row else 0
        vacancies = int(row["vacancies"] or 0) if row else 0
        placed = int(row["placements"]) if row else 0
        trend.append(
            {
                "month": window.start.strftime("%Y-%m"),
                "period": window.as_payload(),
                "requests": requests,
                "vacancies": vacancies,
                "placements": placed,
                "hit_ratio": _ratio(placed, requests),
                "fill_rate": _ratio(placed, vacancies),
            }
        )

    user_row = (
        (
            await db.execute(
                text("SELECT u.id, u.name, u.is_active FROM users u WHERE u.id = :id"),
                {"id": dl_id},
            )
        )
        .mappings()
        .first()
    )
    if user_row is None:
        # 404, nie pusta seria: sześć zer pod nazwiskiem, którego nie ma,
        # czyta się jak „ten DL nic nie dowiózł".
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Nie znaleziono użytkownika o id={dl_id}",
        )

    result = {
        "dl_id": dl_id,
        "name": user_row["name"],
        "is_active": bool(user_row["is_active"]),
        "months": months,
        "recruitment_type": RECRUITMENT_TYPE,
        # Seria NIE jest kumulatywna — każdy punkt to osobne okno [start, end).
        "cumulative": False,
        "trend": trend,
    }
    await cache_set(cache_key, result, ttl_seconds=CACHE_TTL_SECONDS)
    return result
