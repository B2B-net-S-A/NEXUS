"""Portfel Delivery Leada: wiersz rankingu DL rozbity na klientów.

Zasila ``GET /api/insights/delivery-leads/portfolio`` (zakładka Delivery Lead).
Niezmiennik, na którym stoi ten ekran: dla każdego DL suma wierszy klientów
(zapytania, wakaty, placementy) równa się nagłówkowi DL, a nagłówek równa się
wierszowi ``GET /api/insights/delivery-leads`` dla tego samego okna. Dlatego:

* Zapytania i placementy liczymy RAZ na parę (DL, klient) — nagłówek to suma
  wierszy, nie osobne zapytanie, które mogłoby się rozjechać.
* Fragmenty SQL (rozwiązanie DL per oferta, placement
  D2 = pierwsze ``hired`` z ``analytics_first_milestones``) pochodzą z
  ``insights_dl_scope`` — tego samego modułu, z którego czyta ranking.
* Klient schowany / zarchiwizowany / scalony NIE znika z portfela: jego oferty
  liczą się w rankingu, więc wycięcie wiersza rozjechałoby sumy. Dostaje
  jedynie zastępczą nazwę (ranking też bierze nazwę tylko z klienta widocznego).

Hit ratio = placementy w oknie / zapytania OTWARTE w oknie — ta sama
(celowo międzykohortowa) definicja co ranking. Zerowy mianownik → ``None``.
"""

from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.periods import Period, PeriodKind, resolve_period
from app.services.insights_dl_scope import (
    CLIENT_DISPLAY_NAME_SQL,
    CLIENT_VISIBLE_SQL,
    DL_HEAD_CTE,
    HIT_RATIO_TARGET_PCT,
    JOBS_SCOPED_CTE,
    ratio_pct,
)

# Ile miesięcy ma seria placementów przy każdym kliencie (jak trend DL).
MONTHLY_SERIES_LENGTH = 6

# Alert „hit ratio spada": spadek o co najmniej tyle punktów procentowych
# względem poprzedniego okna, przy co najmniej tylu zapytaniach w OBU oknach.
# Bez progu wolumenu jedno zapytanie mniej zamienia 100% w 0% i alarmuje.
ALERT_DROP_PP = -20.0
ALERT_MIN_REQUESTS = 3

NO_CLIENT_NAME = "(bez klienta)"
HIDDEN_CLIENT_NAME = "(klient ukryty lub scalony)"


def previous_period(period: Period) -> Period:
    """Okno bezpośrednio poprzedzające — ta sama granulacja.

    Lustro ``insights_board._previous_period``: okresy kalendarzowe cofamy
    arytmetyką z ``periods.py`` (luty ≠ 30 dni), ``custom`` o dokładną długość.
    """
    if period.kind is PeriodKind.custom:
        span = period.end - period.start
        return Period(kind=period.kind, start=period.start - span, end=period.start)
    return resolve_period(period.kind, anchor=period.start.date(), offset=-1)


def monthly_windows(period: Period) -> list[Period]:
    """Sześć miesięcy kończących się miesiącem zawierającym ostatni dzień okna."""
    last_day = (period.end - timedelta(microseconds=1)).date()
    return [
        resolve_period("month", offset=-i, anchor=last_day)
        for i in range(MONTHLY_SERIES_LENGTH - 1, -1, -1)
    ]


@dataclass
class _Cell:
    requests: int = 0
    vacancies: int = 0
    placements: int = 0
    open_requests: int = 0
    open_jobs: int = 0
    client_name: str | None = None
    prev_requests: int = 0
    prev_placements: int = 0
    monthly: dict[int, int] = field(default_factory=dict)
    top_hm: dict | None = None


async def _demand_and_placements(
    db: AsyncSession, start, end
) -> list[tuple[int | None, int | None, str, int]]:
    """(dl_id, client_id, metryka, wartość) — zapytania/wakaty/placementy okna."""
    params = {"start": start, "end": end}
    demand = (
        (
            await db.execute(
                text(
                    f"""
                WITH {DL_HEAD_CTE}, {JOBS_SCOPED_CTE}
                SELECT js.dl_id AS dl_id,
                       js.client_id AS client_id,
                       count(*) AS requests,
                       COALESCE(SUM(js.headcount), 0) AS vacancies
                FROM jobs_scoped js
                WHERE js.opened_at >= :start AND js.opened_at < :end
                GROUP BY js.dl_id, js.client_id
                """
                ),
                params,
            )
        )
        .mappings()
        .all()
    )
    placements = (
        (
            await db.execute(
                text(
                    f"""
                WITH {DL_HEAD_CTE}, {JOBS_SCOPED_CTE}
                SELECT js.dl_id AS dl_id,
                       js.client_id AS client_id,
                       count(*) AS placements
                FROM analytics_first_milestones fm
                JOIN jobs_scoped js ON js.id = fm.job_id
                WHERE fm.stage = 'hired'
                  AND fm.first_reached_at >= :start
                  AND fm.first_reached_at < :end
                GROUP BY js.dl_id, js.client_id
                """
                ),
                params,
            )
        )
        .mappings()
        .all()
    )
    out: list[tuple[int | None, int | None, str, int]] = []
    for r in demand:
        out.append((r["dl_id"], r["client_id"], "requests", int(r["requests"])))
        out.append((r["dl_id"], r["client_id"], "vacancies", int(r["vacancies"] or 0)))
    for r in placements:
        out.append((r["dl_id"], r["client_id"], "placements", int(r["placements"])))
    return out


async def _open_pipeline(db: AsyncSession) -> list:
    """Migawka „na teraz" per (DL, klient) — bez okna, jak w rankingu.

    ``open_requests`` = oferty ``draft``+``published`` (definicja rankingu),
    ``open_jobs`` = wyłącznie opublikowane (to widzi DL jako „otwarte teraz").
    """
    return (
        (
            await db.execute(
                text(
                    f"""
                WITH {DL_HEAD_CTE}, {JOBS_SCOPED_CTE}
                SELECT js.dl_id AS dl_id,
                       js.client_id AS client_id,
                       count(*) AS open_requests,
                       count(*) FILTER (WHERE js.status = 'published') AS open_jobs
                FROM jobs_scoped js
                WHERE js.status IN ('draft', 'published')
                GROUP BY js.dl_id, js.client_id
                """
                )
            )
        )
        .mappings()
        .all()
    )


async def _monthly_placements(db: AsyncSession, windows: list[Period]) -> list:
    """Placementy per (DL, klient, miesiąc) — każdy miesiąc we WŁASNYM oknie.

    Granice miesięcy liczy ``resolve_period`` (DST), a nie
    ``generate_series`` po stronie Postgresa — ten sam powód co w trendzie DL.
    """
    months_sql = " UNION ALL ".join(
        f"SELECT {i} AS idx, CAST(:s{i} AS timestamptz) AS m_start, "
        f"CAST(:e{i} AS timestamptz) AS m_end"
        for i in range(len(windows))
    )
    params: dict = {}
    for i, window in enumerate(windows):
        params[f"s{i}"] = window.start
        params[f"e{i}"] = window.end
    return (
        (
            await db.execute(
                text(
                    f"""
                WITH {DL_HEAD_CTE}, {JOBS_SCOPED_CTE},
                months AS ({months_sql})
                SELECT m.idx AS idx,
                       js.dl_id AS dl_id,
                       js.client_id AS client_id,
                       count(*) AS placements
                FROM months m
                JOIN analytics_first_milestones fm
                  ON fm.first_reached_at >= m.m_start
                 AND fm.first_reached_at < m.m_end
                JOIN jobs_scoped js ON js.id = fm.job_id
                WHERE fm.stage = 'hired'
                GROUP BY m.idx, js.dl_id, js.client_id
                """
                ),
                params,
            )
        )
        .mappings()
        .all()
    )


async def _top_hiring_managers(db: AsyncSession, start, end) -> list:
    """Hiring manager z największą liczbą zapytań okna per (DL, klient).

    Liczymy te same oferty co kolumna „Zapytania" (otwarte w oknie), żeby
    „HM: 4 rekrutacje" dało się zestawić z liczbą obok. Remis rozstrzyga
    nazwa, potem id — kolejność ma być stabilna między odświeżeniami.
    """
    return (
        (
            await db.execute(
                text(
                    f"""
                WITH {DL_HEAD_CTE}, {JOBS_SCOPED_CTE},
                per_hm AS (
                    SELECT js.dl_id,
                           js.client_id,
                           j.hiring_manager_contact_id AS contact_id,
                           count(*) AS jobs
                    FROM jobs_scoped js
                    JOIN jobs j ON j.id = js.id
                    WHERE js.opened_at >= :start AND js.opened_at < :end
                      AND j.hiring_manager_contact_id IS NOT NULL
                    GROUP BY js.dl_id, js.client_id, j.hiring_manager_contact_id
                ),
                ranked AS (
                    SELECT p.*, ct.name, ct.position,
                           ROW_NUMBER() OVER (
                               PARTITION BY p.dl_id, p.client_id
                               ORDER BY p.jobs DESC, ct.name ASC, p.contact_id ASC
                           ) AS rn
                    FROM per_hm p
                    JOIN contacts ct ON ct.id = p.contact_id
                )
                SELECT dl_id, client_id, contact_id, name, position, jobs
                FROM ranked
                WHERE rn = 1
                """
                ),
                {"start": start, "end": end},
            )
        )
        .mappings()
        .all()
    )


async def _client_names(db: AsyncSession, client_ids: set[int]) -> dict[int, str]:
    if not client_ids:
        return {}
    rows = (
        (
            await db.execute(
                text(
                    f"""
                SELECT c.id AS id, {CLIENT_DISPLAY_NAME_SQL} AS name
                FROM clients c
                WHERE c.id = ANY(CAST(:ids AS integer[]))
                  AND {CLIENT_VISIBLE_SQL}
                """
                ),
                {"ids": sorted(client_ids)},
            )
        )
        .mappings()
        .all()
    )
    return {int(r["id"]): r["name"] for r in rows}


async def _users(db: AsyncSession, ids: set[int]) -> dict[int, dict]:
    if not ids:
        return {}
    rows = (
        (
            await db.execute(
                text(
                    """
                SELECT u.id, u.name, u.is_active
                FROM users u
                WHERE u.id = ANY(CAST(:ids AS integer[]))
                """
                ),
                {"ids": sorted(ids)},
            )
        )
        .mappings()
        .all()
    )
    return {int(r["id"]): dict(r) for r in rows}


def _alert(
    hit_ratio: float | None,
    prev_hit_ratio: float | None,
    requests: int,
    prev_requests: int,
) -> tuple[float | None, str | None]:
    if hit_ratio is None or prev_hit_ratio is None:
        return None, None
    delta_pp = round(hit_ratio - prev_hit_ratio, 1)
    if (
        delta_pp <= ALERT_DROP_PP
        and requests >= ALERT_MIN_REQUESTS
        and prev_requests >= ALERT_MIN_REQUESTS
    ):
        return delta_pp, "hit_ratio_drop"
    return delta_pp, None


async def compute_dl_portfolio(db: AsyncSession, period: Period) -> dict:
    """Portfel DL w oknie ``period`` — kształt opisany w docstringu trasy."""
    previous = previous_period(period)
    windows = monthly_windows(period)

    cells: dict[tuple[int | None, int | None], _Cell] = {}

    def cell(dl_id, client_id) -> _Cell:
        return cells.setdefault((dl_id, client_id), _Cell())

    for dl_id, client_id, metric, value in await _demand_and_placements(
        db, period.start, period.end
    ):
        setattr(cell(dl_id, client_id), metric, value)

    for r in await _open_pipeline(db):
        c = cell(r["dl_id"], r["client_id"])
        c.open_requests = int(r["open_requests"])
        c.open_jobs = int(r["open_jobs"])

    # Poprzednie okno i seria miesięczna WZBOGACAJĄ istniejące wiersze, ale ich
    # nie tworzą: klient z samą historią sprzed okna nie jest częścią portfela
    # w tym oknie (nagłówek rankingu też go nie liczy).
    prev: dict[tuple, dict[str, int]] = {}
    for dl_id, client_id, metric, value in await _demand_and_placements(
        db, previous.start, previous.end
    ):
        prev.setdefault((dl_id, client_id), {})[metric] = value
    for key, values in prev.items():
        if key in cells:
            cells[key].prev_requests = values.get("requests", 0)
            cells[key].prev_placements = values.get("placements", 0)

    for r in await _monthly_placements(db, windows):
        key = (r["dl_id"], r["client_id"])
        if key in cells:
            cells[key].monthly[int(r["idx"])] = int(r["placements"])

    for r in await _top_hiring_managers(db, period.start, period.end):
        key = (r["dl_id"], r["client_id"])
        if key in cells:
            cells[key].top_hm = {
                "contact_id": int(r["contact_id"]),
                "name": r["name"],
                "title": r["position"],
                "jobs": int(r["jobs"]),
            }

    client_ids = {cid for (_, cid) in cells if cid is not None}
    names = await _client_names(db, client_ids)
    dl_ids = {dl for (dl, _) in cells if dl is not None}
    users = await _users(db, dl_ids)

    leads: list[dict] = []
    for dl_id in dl_ids:
        rows: list[dict] = []
        for (row_dl, client_id), c in cells.items():
            if row_dl != dl_id:
                continue
            # Wiersz bez czegokolwiek do pokazania w oknie ani w migawce nie
            # powstaje (setdefault tworzy komórki tylko z realnych danych).
            hit_ratio = ratio_pct(c.placements, c.requests)
            prev_hit_ratio = ratio_pct(c.prev_placements, c.prev_requests)
            delta_pp, alert = _alert(
                hit_ratio, prev_hit_ratio, c.requests, c.prev_requests
            )
            if client_id is None:
                client_name = NO_CLIENT_NAME
            else:
                client_name = names.get(client_id) or HIDDEN_CLIENT_NAME
            rows.append(
                {
                    "client_id": client_id,
                    "client_name": client_name,
                    "requests": c.requests,
                    "vacancies": c.vacancies,
                    "placements": c.placements,
                    "hit_ratio": hit_ratio,
                    "fill_rate": ratio_pct(c.placements, c.vacancies),
                    "open_jobs": c.open_jobs,
                    "monthly_placements": [
                        {
                            "month": w.start.strftime("%Y-%m"),
                            "placements": c.monthly.get(i, 0),
                        }
                        for i, w in enumerate(windows)
                    ],
                    "top_hiring_manager": c.top_hm,
                    "prev_hit_ratio": prev_hit_ratio,
                    "delta_pp": delta_pp,
                    "alert": alert,
                    "_open_requests": c.open_requests,
                }
            )
        rows.sort(
            key=lambda r: (-r["placements"], -r["requests"], r["client_name"].lower())
        )

        requests = sum(r["requests"] for r in rows)
        vacancies = sum(r["vacancies"] for r in rows)
        placements = sum(r["placements"] for r in rows)
        open_requests = sum(r.pop("_open_requests") for r in rows)
        hit_ratio = ratio_pct(placements, requests)
        user = users.get(dl_id) or {}
        leads.append(
            {
                "dl_id": dl_id,
                "dl_name": user.get("name") or f"User {dl_id}",
                "is_active": bool(user.get("is_active", False)),
                "requests": requests,
                "vacancies": vacancies,
                "placements": placements,
                "hit_ratio": hit_ratio,
                "fill_rate": ratio_pct(placements, vacancies),
                "open_requests": open_requests,
                "target_achieved": (
                    None if hit_ratio is None else hit_ratio >= HIT_RATIO_TARGET_PCT
                ),
                "clients": rows,
            }
        )

    leads.sort(key=lambda r: (-r["placements"], -r["requests"], r["dl_name"]))

    unattributed = {"requests": 0, "placements": 0}
    for (dl_id, _), c in cells.items():
        if dl_id is None:
            unattributed["requests"] += c.requests
            unattributed["placements"] += c.placements

    return {
        "period": period.as_payload(),
        "previous_period": previous.as_payload(),
        "hit_ratio_target_pct": HIT_RATIO_TARGET_PCT,
        "alert_rule": {
            "drop_pp": ALERT_DROP_PP,
            "min_requests_both_windows": ALERT_MIN_REQUESTS,
        },
        "leads": leads,
        # Org-level, nigdy w czyimś wierszu — jak w rankingu.
        "unattributed": unattributed,
    }
