"""Insights → „W drodze” — co stoi dziś w lejku i ile z tego może wpaść.

Prośba Artura 22.10.2026: „mamy 10 placementów, ale już jest 10 akceptów —
czy będziemy mieli kolejne 10?”. Lejek w oknie mówi, ile par DOSZŁO do etapu;
tu jest stan na dziś: ile par stoi w każdej kolumnie Tablicy za weryfikacją,
od kiedy, i co z akceptacji zwykle kończy się placementem.

Kolumnę pary liczy ta sama reguła co Tablica i raport „Lejek po etapach”
(`insights_stage_breakdown._KEY_CASE_SQL` — odznaka z nazwy etapu szablonu,
potem kod etapu), więc „Teraz” w raporcie i tutaj to te same liczby.

Prognoza jest świadomie ostrożna:

* skuteczność = akceptacje ROZSTRZYGNIĘTE (placement albo zamknięcie) od
  12.10.2026 — wcześniej akceptacji nikt nie odnotowywał (Traffit ich nie znał,
  DynaReporter nie prowadził), więc starsza historia nie istnieje;
* przy mniej niż `MIN_FORECAST_SAMPLE` rozstrzygnięciach skuteczności nie ma
  (`rate_pct = None`) — ekran mówi wtedy „mało danych”, a nie zgaduje.
"""

from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any, Optional, Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import competition_history
from app.services.insights_stage_breakdown import (
    _DEF_MAP_CTE,
    _JOB_FILTER_SQL,
    _KEY_CASE_SQL,
    _load_def_map,
)
from app.services.placement_exclusions import excluded_hired_sql

# Kolumny Tablicy za weryfikacją, w kolejności lejka. Klucze to klucze wierszy
# „Lejka po etapach” (`insights_stage_breakdown.ROWS`).
COLUMNS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("cv_qc", "Czekają na wysyłkę CV", ("qc", "cpro")),
    ("cv_sent", "Czekają na decyzję klienta", ("cv_sent",)),
    (
        "client_interview",
        "Rozmowy u klienta",
        ("prep", "client_interview", "after_interview"),
    ),
    (
        "contract",
        "Akceptacje do domknięcia",
        ("acceptance", "contract_sent", "contract_signed"),
    ),
)

KEY_LABELS = {
    "acceptance": "Akceptacja",
    "contract_sent": "Umowa wysłana",
    "contract_signed": "Umowa podpisana",
}
# Etykiety pozostałych kluczy w kolumnach „w drodze” — jak wiersze raportu.
STAGE_LABELS = {
    "qc": "QC CV",
    "cpro": "W kolejce Cpro",
    "cv_sent": "Wysłane do klienta",
    "prep": "Prep",
    "client_interview": "Rozmowa u klienta",
    "after_interview": "Po rozmowie",
}

# Para stoi „długo”, gdy w kolumnie jest dłużej niż tyle dni.
STALE_DAYS = 10
# Poniżej tylu rozstrzygniętych akceptacji skuteczność nie jest pokazywana.
MIN_FORECAST_SAMPLE = 10

_COLUMN_CASE_SQL = (
    "CASE "
    + " ".join(
        f"WHEN key IN ({', '.join(repr(k) for k in keys)}) THEN '{col}'"
        for col, _label, keys in COLUMNS
    )
    + " END"
)

DEFINITIONS = {
    "columns": (
        "Stan na dziś: pary (kandydat, rekrutacja), których najnowszy etap stoi "
        "w tej kolumnie Tablicy, w opublikowanych rekrutacjach. Od kiedy — od "
        "wejścia do kolumny."
    ),
    "forecast": (
        "Skuteczność akceptacji: z akceptacji rozstrzygniętych od 12.10.2026 "
        "(placement albo zamknięcie) — ile skończyło się placementem. Szacunek "
        "to otwarte akceptacje razy ta skuteczność; przy mniej niż "
        f"{MIN_FORECAST_SAMPLE} rozstrzygnięciach go nie pokazujemy."
    ),
}


def forecast_range(open_count: int, hired: int, resolved: int) -> dict[str, Any]:
    """Szacunek placementów z otwartych akceptacji — czysta arytmetyka.

    `low`/`high` to podłoga i sufit iloczynu, żeby ekran mógł napisać „8–9”,
    a nie udawać dokładność co do sztuki.
    """

    if resolved < MIN_FORECAST_SAMPLE:
        return {"rate_pct": None, "low": None, "high": None}
    rate = hired / resolved
    expected = open_count * rate
    return {
        "rate_pct": round(rate * 100, 1),
        "low": math.floor(expected),
        "high": math.ceil(expected),
    }


async def _pairs_now(db: AsyncSession, params: dict[str, Any]) -> list[dict[str, Any]]:
    """Pary w kolumnach za weryfikacją, z wejściem do kolumny i rekrutacją."""

    job_filter = _JOB_FILTER_SQL.format(col="cs.job_id")
    rows = (
        (
            await db.execute(
                text(
                    f"""
                WITH {_DEF_MAP_CTE},
                keyed AS (
                  SELECT cs.id, cs.candidate_id, cs.job_id, cs.moved_at,
                         {_KEY_CASE_SQL} AS key
                  FROM candidate_stages cs
                  JOIN jobs j ON j.id = cs.job_id
                  LEFT JOIN def_map m ON m.def_id = cs.stage_def_id
                  WHERE j.status::text = 'published'
                    AND {job_filter}
                ),
                columned AS (
                  SELECT k.*, {_COLUMN_CASE_SQL} AS col FROM keyed k
                ),
                latest AS (
                  SELECT DISTINCT ON (candidate_id, job_id)
                         candidate_id, job_id, key, col, moved_at
                  FROM columned
                  ORDER BY candidate_id, job_id, moved_at DESC, id DESC
                ),
                left_column AS (
                  SELECT c.candidate_id, c.job_id, max(c.moved_at) AS at
                  FROM columned c
                  JOIN latest l
                    ON l.candidate_id = c.candidate_id AND l.job_id = c.job_id
                  WHERE c.col IS DISTINCT FROM l.col
                  GROUP BY c.candidate_id, c.job_id
                ),
                entered AS (
                  SELECT c.candidate_id, c.job_id, min(c.moved_at) AS at
                  FROM columned c
                  JOIN latest l
                    ON l.candidate_id = c.candidate_id AND l.job_id = c.job_id
                   AND c.col = l.col
                  LEFT JOIN left_column lc
                    ON lc.candidate_id = c.candidate_id AND lc.job_id = c.job_id
                  WHERE lc.at IS NULL OR c.moved_at > lc.at
                  GROUP BY c.candidate_id, c.job_id
                )
                SELECT l.candidate_id, l.job_id, l.key, l.col,
                       e.at AS entered_at,
                       j.title AS job_title, j.client_id,
                       cl.name AS client_name,
                       dl.name AS delivery_lead_name,
                       concat_ws(' ', cand.name, cand.lastname) AS candidate_name,
                       (
                         SELECT v.moved_by FROM candidate_stages v
                         WHERE v.candidate_id = l.candidate_id
                           AND v.job_id = l.job_id
                           AND v.stage::text = 'verified'
                           AND v.moved_by IS NOT NULL
                         ORDER BY v.moved_at, v.id
                         LIMIT 1
                       ) AS verifier_id
                FROM latest l
                JOIN entered e
                  ON e.candidate_id = l.candidate_id AND e.job_id = l.job_id
                JOIN jobs j ON j.id = l.job_id
                JOIN candidates cand ON cand.id = l.candidate_id
                LEFT JOIN clients cl ON cl.id = j.client_id
                LEFT JOIN users dl ON dl.id = j.delivery_lead_id
                WHERE l.col IS NOT NULL
                  AND (
                    CAST(:owner_kind AS text) IS NULL
                    OR (CAST(:owner_kind AS text) = 'delivery_lead'
                        AND j.delivery_lead_id = :owner_id)
                    -- Ta sama zasługa co „Mój miesiąc” i wyścigi: pierwszy
                    -- weryfikujący pary.
                    OR (CAST(:owner_kind AS text) = 'verifier' AND (
                      SELECT v.moved_by FROM candidate_stages v
                      WHERE v.candidate_id = l.candidate_id
                        AND v.job_id = l.job_id
                        AND v.stage::text = 'verified'
                        AND v.moved_by IS NOT NULL
                      ORDER BY v.moved_at, v.id
                      LIMIT 1
                    ) = :owner_id)
                  )
                """
                ),
                params,
            )
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


async def _resolved_acceptances(
    db: AsyncSession, params: dict[str, Any]
) -> tuple[int, int]:
    """(placementy, rozstrzygnięte) wśród akceptacji od 12.10.2026.

    Akceptacja = para, która weszła do kolumny „Umowa”. Rozstrzygnięta =
    jej najnowszy etap to zatrudnienie (bez wykluczonych placementów) albo
    zamknięcie procesu. Rekrutacja może być już zamknięta — liczy się los pary.
    """

    job_filter = _JOB_FILTER_SQL.format(col="cs.job_id")
    row = (
        (
            await db.execute(
                text(
                    f"""
                WITH {_DEF_MAP_CTE},
                keyed AS (
                  SELECT cs.id, cs.candidate_id, cs.job_id, cs.moved_at, cs.stage,
                         {_KEY_CASE_SQL} AS key
                  FROM candidate_stages cs
                  LEFT JOIN def_map m ON m.def_id = cs.stage_def_id
                  WHERE {job_filter}
                    AND {excluded_hired_sql("cs")}
                ),
                accepted AS (
                  SELECT DISTINCT candidate_id, job_id
                  FROM keyed
                  WHERE key IN ('acceptance', 'contract_sent', 'contract_signed')
                    AND moved_at >= :since
                ),
                latest AS (
                  SELECT DISTINCT ON (k.candidate_id, k.job_id) k.key
                  FROM keyed k
                  JOIN accepted a
                    ON a.candidate_id = k.candidate_id AND a.job_id = k.job_id
                  ORDER BY k.candidate_id, k.job_id, k.moved_at DESC, k.id DESC
                )
                SELECT
                  count(*) FILTER (WHERE key IN ('hired', 'onboarding')) AS hired,
                  count(*) FILTER (
                    WHERE key IN ('hired', 'onboarding', '__closed', '__reserve')
                  ) AS resolved
                FROM latest
                """
                ),
                params,
            )
        )
        .mappings()
        .one()
    )
    return int(row["hired"] or 0), int(row["resolved"] or 0)


OWNER_KINDS = ("verifier", "delivery_lead")


async def in_flight_by_verifier(
    db: AsyncSession, *, job_ids: Optional[Sequence[int]] = None
) -> dict[int, int]:
    """Ile par w drodze ma dziś każda osoba (pierwszy weryfikujący pary).

    Ta sama zasługa co „Moje osoby w drodze” — kolumna „W drodze” tabeli
    Ludzie w widoku Zespół zgadza się z liczbą, którą osoba widzi u siebie.
    """

    def_ids, def_keys = await _load_def_map(db)
    pairs = await _pairs_now(
        db,
        {
            "def_ids": def_ids,
            "def_keys": def_keys,
            "job_ids": list(job_ids) if job_ids is not None else None,
            "owner_kind": None,
            "owner_id": None,
        },
    )
    counts: dict[int, int] = {}
    for pair in pairs:
        if pair["verifier_id"] is not None:
            uid = int(pair["verifier_id"])
            counts[uid] = counts.get(uid, 0) + 1
    return counts


async def compute_in_flight(
    db: AsyncSession,
    *,
    today: date,
    now: datetime,
    with_acceptances: bool,
    owner: Optional[tuple[str, int]] = None,
    with_people: bool = False,
    job_ids: Optional[Sequence[int]] = None,
) -> dict[str, Any]:
    """Stan „w drodze”. `with_acceptances=False` = bez listy rekrutacji.

    `owner` zawęża pary do jednej osoby: `("verifier", id)` — pary, które
    zweryfikowała (zasługa jak w „Mój miesiąc”), `("delivery_lead", id)` —
    rekrutacje Delivery Leada. `with_people` dokłada listę par z nazwiskiem
    kandydata — wyłącznie dla widoku własnych osób. Skuteczność prognozy jest
    zawsze firmowa: próbka jednej osoby jest za mała.

    `job_ids` zawęża wynik (testy na wspólnej bazie); API go nie przekazuje.
    """

    if owner is not None and owner[0] not in OWNER_KINDS:
        raise ValueError(f"nieznany zakres: {owner[0]}")
    def_ids, def_keys = await _load_def_map(db)
    params: dict[str, Any] = {
        "def_ids": def_ids,
        "def_keys": def_keys,
        "job_ids": list(job_ids) if job_ids is not None else None,
        "since": competition_history.cutover_utc(),
        "owner_kind": owner[0] if owner else None,
        "owner_id": owner[1] if owner else None,
    }
    pairs = await _pairs_now(db, params)

    def days_in(pair: dict[str, Any]) -> int:
        return max((now - pair["entered_at"]).days, 0)

    columns = []
    for col, label, _keys in COLUMNS:
        in_col = [p for p in pairs if p["col"] == col]
        ages = [days_in(p) for p in in_col]
        columns.append(
            {
                "column": col,
                "label": label,
                "count": len(in_col),
                "stale_count": sum(1 for a in ages if a > STALE_DAYS),
                "oldest_days": max(ages) if ages else None,
            }
        )

    def common(p: dict[str, Any]) -> dict[str, Any]:
        return {
            "job_id": p["job_id"],
            "job_title": p["job_title"],
            "client_id": p["client_id"],
            "client_name": p["client_name"],
            "delivery_lead_name": p["delivery_lead_name"],
            "stage_key": p["key"],
            "stage_label": KEY_LABELS.get(p["key"], STAGE_LABELS.get(p["key"], "")),
            "since": p["entered_at"].date().isoformat(),
            "days": days_in(p),
        }

    acceptances = None
    if with_acceptances:
        acceptances = sorted(
            (common(p) for p in pairs if p["col"] == "contract"),
            key=lambda a: (-a["days"], a["client_name"] or "", a["job_id"]),
        )

    people = None
    if with_people:
        order = {col: i for i, (col, _label, _keys) in enumerate(COLUMNS)}
        people = sorted(
            (
                {
                    **common(p),
                    "candidate_id": p["candidate_id"],
                    "candidate_name": p["candidate_name"],
                    "column": p["col"],
                }
                for p in pairs
            ),
            # Najpierw najbliżej placementu, w kolumnie — najdłużej czekający.
            key=lambda x: (-order[x["column"]], -x["days"], x["candidate_id"]),
        )

    hired, resolved = await _resolved_acceptances(db, params)
    open_count = next(c["count"] for c in columns if c["column"] == "contract")
    return {
        "asof": today.isoformat(),
        "stale_days": STALE_DAYS,
        "columns": columns,
        "acceptances": acceptances,
        "people": people,
        "forecast": {
            "open": open_count,
            "hired": hired,
            "resolved": resolved,
            "min_sample": MIN_FORECAST_SAMPLE,
            "since": competition_history.RESULTS_CUTOVER.isoformat(),
            **forecast_range(open_count, hired, resolved),
        },
        "definitions": DEFINITIONS,
    }
