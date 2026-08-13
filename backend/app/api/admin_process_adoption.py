"""GET /api/admin/process-adoption — read-only pomiar adopcji i widoczności procesu.

Odpowiada na dwa pytania, których nie da się rozstrzygnąć z kodu ani z ekranu:

**A. ADOPCJA — czy praca dzieje się w NEXUSIE, czy w Traffitcie?**
   Rozbicie ruchów `candidate_stages` po etapie i po pochodzeniu wiersza.

**B. WIDOCZNOŚĆ — jeśli praca się dzieje, dlaczego KPI jej nie widzi?**
   Wodospad odpadania kamieni milowych: ile ich jest w surowym widoku, ile
   przeżywa CTE atrybucji, ile ma `credit_user`, ile trafia na AKTYWNEGO
   użytkownika (dopiero to ostatnie widać na kaflach `/dashboard`).

Powód powstania (2026-08-13): kafle „Statystyki rekrutacji" i
`/api/reports/recruitment` liczą ten sam lejek i różnią się 5-15× po
normalizacji długości okna, a sierpień 2026 wygląda na urwisko (15 weryfikacji
/ 0 rekomendacji wobec 500-900 / 125-272 miesięcznie) mimo świeżego syncu
Traffita. Bez tego endpointu każda diagnoza wymagałaby dostępu do bazy.

Kontrakt (jak `/api/admin/pipeline-inventory`):
- WYŁĄCZNIE odczyt (SELECT); endpoint niczego nie mutuje ani nie naprawia.
- Zero PII: same liczby, etapy, miesiące i etykiety enumów. Żadnych nazwisk,
  adresów, ID kandydatów ani treści. `distinct_movers` to LICZBA osób, nie lista.
- Każde zapytanie ma własny timeout; błąd jednego nie wywala raportu.
- `query_version` + `generated_at` pozwalają porównywać kolejne przebiegi.

Auth: jak `/api/admin/snapshot` — klucz serwisowy, X-Snapshot-Token albo JWT admina.

WAŻNE przy czytaniu wyników — dyskryminator „nasza praca vs import" to
`external_source = 'manual'`, **NIE `IS NULL`**: kolumna ma ORM-owy default
`"manual"` (`models/recruitment_pipeline.py:224`), a importer stempluje
`'traffit'` (`services/traffit/mappers.py:629`). Predykat `IS NULL` zwróciłby
zero wszędzie — prawdziwy wynik z fałszywego powodu. Z tego samego powodu sam
`moved_by` nie jest znacznikiem pracy własnej: importer mapuje operatorów
Traffita na realne `users.id`.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_snapshot import _snapshot_auth
from app.core.database import get_db
from app.services.kpi_panel import VERIFIER_ANCHORED_CTE

router = APIRouter()

# Bump przy każdej zmianie definicji zapytań — raporty porównujemy tylko
# w obrębie tej samej wersji.
QUERY_VERSION = "adoption-v1"

QUERY_TIMEOUT_SECONDS = 25.0
# Wodospad jedzie po CTE atrybucji (to samo, które liczy kafle), więc dostaje
# własny, dłuższy budżet — to najdroższe zapytanie w tym raporcie.
WATERFALL_TIMEOUT_SECONDS = 60.0

_WARSAW_MONTH = (
    "to_char(date_trunc('month', {col} AT TIME ZONE 'Europe/Warsaw'), 'YYYY-MM')"
)


# ── A. Adopcja ───────────────────────────────────────────────────────────────

# Ruchy per etap × pochodzenie w oknie. `with_mover` i `distinct_movers` mówią,
# czy wiersz w ogóle ma autora — ale UWAGA: import też go bywa ma (mapowanie
# operatorów Traffita), więc rozstrzyga dopiero para (etap, external_source).
_STAGE_ORIGIN_SQL = """
    SELECT
        cs.stage::text AS stage,
        COALESCE(cs.external_source, '(null)') AS origin,
        count(*) AS moves,
        count(*) FILTER (WHERE cs.moved_by IS NOT NULL) AS with_mover,
        count(DISTINCT cs.moved_by) AS distinct_movers
    FROM candidate_stages cs
    WHERE cs.moved_at >= :since
    GROUP BY 1, 2
    ORDER BY 3 DESC
"""

# Ten sam podział, ale w osi czasu — pokazuje, czy praca własna rośnie, maleje,
# czy urwała się w konkretnym miesiącu.
_STAGE_ORIGIN_MONTHLY_SQL = f"""
    SELECT
        {_WARSAW_MONTH.format(col="cs.moved_at")} AS month,
        COALESCE(cs.external_source, '(null)') AS origin,
        count(*) AS moves
    FROM candidate_stages cs
    WHERE cs.moved_at >= :since
    GROUP BY 1, 2
    ORDER BY 1 DESC, 3 DESC
"""


# ── B. Widoczność ────────────────────────────────────────────────────────────

# Stan procesów w osi miesiąca otwarcia. To tu widać, czy procesy zakładane od
# konkretnego miesiąca mają `kpi_eligible = NULL` (a wtedy wypadają z OBU gałęzi
# „classified" w CTE atrybucji: kpi_panel.py:191 i :206).
_PROCESS_ELIGIBILITY_SQL = f"""
    SELECT
        {_WARSAW_MONTH.format(col="rp.opened_at")} AS month,
        COALESCE(rp.origin_kind::text, '(null)') AS origin_kind,
        CASE
            WHEN rp.kpi_eligible IS NULL THEN 'null'
            WHEN rp.kpi_eligible THEN 'true'
            ELSE 'false'
        END AS kpi_eligible,
        (rp.credit_user_id IS NULL) AS without_credit_user,
        rp.status::text AS status,
        count(*) AS processes
    FROM recruitment_processes rp
    WHERE rp.opened_at >= :since
    GROUP BY 1, 2, 3, 4, 5
    ORDER BY 1 DESC, 6 DESC
"""

# Surowa strona wodospadu: pierwsze osiągnięcia etapu per (kandydat, oferta).
# To jest liczba, którą pokazuje /api/reports/recruitment.
_RAW_MILESTONES_SQL = f"""
    SELECT
        {_WARSAW_MONTH.format(col="afm.first_reached_at")} AS month,
        afm.stage::text AS stage,
        count(*) AS raw_milestones
    FROM analytics_first_milestones afm
    WHERE afm.first_reached_at >= :since
    GROUP BY 1, 2
"""

# Strona atrybuowana: DOKŁADNIE to CTE, które liczy kafle — nie reimplementacja.
# Trzy kolejne zawężenia w jednym przebiegu:
#   credited              — przeżyło okna procesu, kpi_eligible i kotwicę verified
#   credited_with_user    — ma niepustego credit_user (kpi_team.py:60)
#   credited_active_user  — credit_user jest AKTYWNY (kpi_team.py:15-17) = kafel
_CREDITED_MILESTONES_SQL = (
    VERIFIER_ANCHORED_CTE
    + f"""
    , windowed AS (
        SELECT stage, reached_at, credit_user
        FROM credited
        WHERE reached_at >= :since
    )
    SELECT
        {_WARSAW_MONTH.format(col="w.reached_at")} AS month,
        w.stage AS stage,
        count(*) AS credited,
        count(*) FILTER (WHERE w.credit_user IS NOT NULL) AS credited_with_user,
        count(*) FILTER (WHERE u.id IS NOT NULL AND u.is_active IS TRUE)
            AS credited_active_user
    FROM windowed w
    LEFT JOIN users u ON u.id = w.credit_user
    GROUP BY 1, 2
"""
)


# ── C. Wspierające ───────────────────────────────────────────────────────────

_SUPPORTING_SQL = """
    SELECT
        (
            SELECT count(*) FROM jobs
            WHERE status = 'closed' AND closed_at >= :since
        ) AS jobs_closed,
        (
            SELECT count(*) FROM jobs
            WHERE status = 'closed' AND closed_at >= :since
              AND close_reason IS NULL
        ) AS jobs_closed_without_reason,
        (
            SELECT count(*) FROM interview_feedback WHERE created_at >= :since
        ) AS interview_feedback_rows,
        (
            SELECT count(*) FROM calendar_events WHERE created_at >= :since
        ) AS calendar_events_rows,
        (
            SELECT count(*) FROM candidate_stages
            WHERE moved_at >= :since AND stage::text = 'client_interview'
        ) AS client_interview_moves
"""

_REJECTION_EMAILS_SQL = """
    SELECT status::text AS status, count(*) AS rows
    FROM scheduled_rejection_emails
    GROUP BY 1
    ORDER BY 2 DESC
"""


async def _run(
    db: AsyncSession,
    key: str,
    sql: str,
    params: dict[str, Any],
    *,
    timeout: float = QUERY_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Wykonaj jedno zapytanie; nigdy nie rzucaj — raportuj błąd inline.

    `rollback()` w `finally` jest OBOWIĄZKOWY, nie kosmetyką. Siedem zapytań
    jedzie po TEJ SAMEJ sesji, a przekroczenie budżetu `asyncio.wait_for`
    anuluje zapytanie w locie (`pg_cancel_backend`) i zostawia połączenie
    w stanie przerwanej transakcji. Bez resetu każde KOLEJNE zapytanie dostałoby
    `InFailedSQLTransaction` (25P02) i raport pokazałby jako zepsute również te
    trywialne — czyli najdroższe zapytanie pociągnęłoby za sobą diagnostykę,
    która miała wyjaśnić, dlaczego padło.

    Reset po KAŻDYM zapytaniu, nie tylko po błędzie, ma drugi powód: kończy
    niejawną transakcję odczytu. Inaczej jeden przebieg raportu trzymałby
    otwarty snapshot MVCC przez cały swój czas życia (na prodzie nawet ~2 min).
    """
    started = time.monotonic()
    try:
        result = await asyncio.wait_for(db.execute(text(sql), params), timeout=timeout)
        rows = [dict(row) for row in result.mappings().all()]
        return {
            "key": key,
            "rows": rows,
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        }
    except Exception as exc:  # noqa: BLE001 — raport ma przeżyć błąd zapytania
        return {
            "key": key,
            "rows": [],
            "elapsed_ms": int((time.monotonic() - started) * 1000),
            "error": f"{type(exc).__name__}: {exc}",
        }
    finally:
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001 — reset sesji nie może wywalić raportu
            pass


def _merge_waterfall(
    raw: list[dict[str, Any]], credited: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Złóż obie strony w jedną tabelę (miesiąc, etap) → 4 liczby.

    Kolejność kolumn to kolejność odpadania: `raw` ≥ `credited` ≥
    `credited_with_user` ≥ `credited_active_user`. Ostatnia kolumna to liczba,
    którą widzi użytkownik na kaflu.

    Semantyka `raw` i `credited` różni się celowo i o tym trzeba pamiętać przy
    czytaniu: surowy widok liczy PIERWSZE osiągnięcie etapu per (kandydat,
    oferta), a CTE atrybucji per PRÓBĘ procesu. Przy ponownej aplikacji tej
    samej osoby na tę samą ofertę `credited` może być większe od `raw` — i to
    nie jest błąd. Interesuje nas kierunek i rząd wielkości różnicy.
    """
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for row in raw:
        key = (row["month"], row["stage"])
        merged[key] = {
            "month": row["month"],
            "stage": row["stage"],
            "raw": int(row["raw_milestones"]),
            "credited": 0,
            "credited_with_user": 0,
            "credited_active_user": 0,
        }
    for row in credited:
        key = (row["month"], row["stage"])
        entry = merged.setdefault(
            key,
            {
                "month": row["month"],
                "stage": row["stage"],
                "raw": 0,
                "credited": 0,
                "credited_with_user": 0,
                "credited_active_user": 0,
            },
        )
        entry["credited"] = int(row["credited"])
        entry["credited_with_user"] = int(row["credited_with_user"])
        entry["credited_active_user"] = int(row["credited_active_user"])

    return sorted(merged.values(), key=lambda r: (r["month"], r["stage"]), reverse=True)


@router.get(
    "/process-adoption",
    summary="Read-only pomiar adopcji procesu i widoczności KPI",
)
async def process_adoption(
    auth_mode: Annotated[str, Depends(_snapshot_auth)],
    db: AsyncSession = Depends(get_db),
    months: Annotated[int, Query(ge=1, le=36)] = 14,
    adoption_days: Annotated[int, Query(ge=1, le=730)] = 90,
) -> dict[str, Any]:
    started = time.monotonic()
    now = datetime.now(tz=timezone.utc)
    since_months = now - timedelta(days=31 * months)
    since_days = now - timedelta(days=adoption_days)

    monthly_params = {"since": since_months}
    window_params = {"since": since_days}

    stage_origin = await _run(db, "stage_origin", _STAGE_ORIGIN_SQL, window_params)
    stage_origin_monthly = await _run(
        db, "stage_origin_monthly", _STAGE_ORIGIN_MONTHLY_SQL, monthly_params
    )
    process_eligibility = await _run(
        db, "process_eligibility", _PROCESS_ELIGIBILITY_SQL, monthly_params
    )
    raw_milestones = await _run(
        db, "raw_milestones", _RAW_MILESTONES_SQL, monthly_params
    )
    credited_milestones = await _run(
        db,
        "credited_milestones",
        _CREDITED_MILESTONES_SQL,
        monthly_params,
        timeout=WATERFALL_TIMEOUT_SECONDS,
    )
    supporting = await _run(db, "supporting", _SUPPORTING_SQL, window_params)
    rejection_emails = await _run(db, "rejection_emails", _REJECTION_EMAILS_SQL, {})

    queries = [
        stage_origin,
        stage_origin_monthly,
        process_eligibility,
        raw_milestones,
        credited_milestones,
        supporting,
        rejection_emails,
    ]
    failed = [q["key"] for q in queries if "error" in q]

    # Adopcja w skrócie: ile ruchów w oknie powstało u nas, ile przyszło z importu.
    manual_moves = sum(
        int(r["moves"]) for r in stage_origin["rows"] if r["origin"] == "manual"
    )
    total_moves = sum(int(r["moves"]) for r in stage_origin["rows"])

    return {
        "query_version": QUERY_VERSION,
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "window": {
            "months": months,
            "adoption_days": adoption_days,
            "monthly_since": since_months.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "adoption_since": since_days.strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        "summary": {
            "queries_total": len(queries),
            "queries_failed": len(failed),
            "failed_keys": failed,
            "moves_in_window": total_moves,
            "moves_manual": manual_moves,
            "moves_manual_pct": (
                round(manual_moves / total_moves * 100, 1) if total_moves else None
            ),
        },
        "adoption": {
            "by_stage_and_origin": stage_origin["rows"],
            "by_month_and_origin": stage_origin_monthly["rows"],
        },
        "visibility": {
            "processes_by_month": process_eligibility["rows"],
            "milestone_waterfall": _merge_waterfall(
                raw_milestones["rows"], credited_milestones["rows"]
            ),
        },
        "supporting": {
            "counts": supporting["rows"][0] if supporting["rows"] else {},
            "rejection_emails_by_status": rejection_emails["rows"],
        },
        "diagnostics": [{k: v for k, v in q.items() if k != "rows"} for q in queries],
        "elapsed_ms": int((time.monotonic() - started) * 1000),
        "auth_mode": auth_mode,
    }
