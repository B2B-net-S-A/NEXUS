"""GET /api/admin/pipeline-inventory — read-only anomaly report pipeline'u.

Moduł 4 (pipeline/submission/placement), plan PR-00: zmierzyć produkcyjny stan
lifecycle ZANIM zmienimy authority (RecruitmentProcess/ledger w falach 1+).
Klasy anomalii pochodzą z sekcji 14.1 dokumentu audytu
`docs/recruitment-pipeline-submission-placement-module-audit-and-claude-
implementation-plan-2026-07-16.md`.

Kontrakt:
- WYŁĄCZNIE odczyt (SELECT) — endpoint niczego nie naprawia i nie mutuje.
- Zero PII w output: sample zawiera tylko numeryczne ID (candidate/job/stage/
  contract/email-schedule) oraz zewnętrzne identyfikatory Traffit. Żadnych
  nazwisk, adresów e-mail, telefonów, treści CV ani feedbacku.
- Sample ograniczone do SAMPLE_LIMIT pozycji per check.
- Każdy check ma własny timeout; błąd jednego checku nie wywala raportu
  (pole `error` zamiast liczby).
- `query_version` + `generated_at` pozwalają porównywać kolejne przebiegi.

Auth: jak /api/admin/snapshot — X-Snapshot-Token (machine) albo JWT admina.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_snapshot import _snapshot_auth
from app.core.database import get_db

router = APIRouter()

# Bump przy każdej zmianie definicji zapytań — raporty porównujemy tylko
# w obrębie tej samej wersji.
QUERY_VERSION = "m4-pr00-v1"

SAMPLE_LIMIT = 20
CHECK_TIMEOUT_SECONDS = 20.0

# Kanoniczny "latest per para" wg audytu: (moved_at DESC, id DESC).
_LATEST_CTE = """
    SELECT DISTINCT ON (candidate_id, job_id)
        id, candidate_id, job_id, stage, stage_def_id,
        verification_status, moved_at
    FROM candidate_stages
    ORDER BY candidate_id, job_id, moved_at DESC, id DESC
"""

# Terminalność wiersza: sygnał stage_def LUB legacy enum (którykolwiek).
_TERMINAL_ROW = (
    "(COALESCE(d.is_terminal, FALSE) "
    "OR l.stage IN ('hired', 'rejected', 'withdrawn'))"
)


# ── Definicje checków ────────────────────────────────────────────────────────
# key -> (severity, description, SQL zwracające wiersze anomalii).
# Konwencja: pierwsza kolumna(y) idą do sample jako dict; COUNT robimy
# osobnym zapytaniem COUNT(*) OVER () w tym samym SQL (kolumna total_count),
# żeby jeden SQL dawał i licznik, i próbkę.

_CHECKS: list[tuple[str, str, str, str]] = [
    (
        "stage_def_outside_job_template",
        "P0",
        "Latest wiersz pary wskazuje stage_def spoza aktualnego template'u "
        "joba (karta może być niewidoczna na Kanbanie).",
        f"""
        WITH latest AS ({_LATEST_CTE}),
        dflt AS (
            SELECT id FROM pipeline_templates WHERE is_default IS TRUE LIMIT 1
        )
        SELECT l.candidate_id, l.job_id, l.id AS stage_id,
               COUNT(*) OVER () AS total_count
        FROM latest l
        JOIN jobs j ON j.id = l.job_id
        JOIN pipeline_stage_defs d ON d.id = l.stage_def_id
        WHERE d.template_id
              <> COALESCE(j.pipeline_template_id, (SELECT id FROM dflt))
        ORDER BY l.candidate_id DESC, l.job_id DESC
        LIMIT :sample_limit
        """,
    ),
    (
        "pending_not_current",
        "P0",
        "verification_status='pending' na wierszu, który NIE jest latest "
        "swojej pary — historyczny pending nadal actionable na liście "
        "/pending-verifications.",
        f"""
        WITH latest AS ({_LATEST_CTE})
        SELECT cs.candidate_id, cs.job_id, cs.id AS stage_id,
               COUNT(*) OVER () AS total_count
        FROM candidate_stages cs
        LEFT JOIN latest l ON l.id = cs.id
        WHERE cs.verification_status = 'pending' AND l.id IS NULL
        ORDER BY cs.candidate_id DESC, cs.job_id DESC
        LIMIT :sample_limit
        """,
    ),
    (
        "hired_no_contract",
        "P0",
        "Para z etapem hired bez żadnego pasującego Contract "
        "(candidate + ten job albo candidate + contract bez joba).",
        """
        SELECT candidate_id, job_id, COUNT(*) OVER () AS total_count
        FROM (
            SELECT DISTINCT cs.candidate_id, cs.job_id
            FROM candidate_stages cs
            WHERE (
                cs.stage = 'hired'
                OR EXISTS (
                    SELECT 1 FROM pipeline_stage_defs d
                    WHERE d.id = cs.stage_def_id AND d.terminal_type = 'hired'
                )
            )
            AND NOT EXISTS (
                SELECT 1 FROM contracts c
                WHERE c.candidate_id = cs.candidate_id
                  AND (c.job_id = cs.job_id OR c.job_id IS NULL)
            )
        ) pairs
        ORDER BY candidate_id DESC, job_id DESC
        LIMIT :sample_limit
        """,
    ),
    (
        "duplicate_latest_ties",
        "P1",
        "Kilka wierszy pary dzieli identyczny MAX(moved_at) — różne query "
        "mogą wybrać inny 'current' (tie bez tiebreakera po id).",
        """
        WITH mx AS (
            SELECT candidate_id, job_id, MAX(moved_at) AS m
            FROM candidate_stages
            GROUP BY candidate_id, job_id
        )
        SELECT cs.candidate_id, cs.job_id, COUNT(*) AS tied_rows,
               COUNT(*) OVER () AS total_count
        FROM candidate_stages cs
        JOIN mx ON mx.candidate_id = cs.candidate_id
               AND mx.job_id = cs.job_id
               AND cs.moved_at = mx.m
        GROUP BY cs.candidate_id, cs.job_id
        HAVING COUNT(*) > 1
        ORDER BY cs.candidate_id DESC, cs.job_id DESC
        LIMIT :sample_limit
        """,
    ),
    (
        "latest_time_vs_id_mismatch",
        "P1",
        "Latest wg (moved_at, id) ≠ latest wg MAX(id) — backdated eventy "
        "(np. import) zmieniają odpowiedź zależnie od definicji current.",
        """
        WITH by_time AS (
            SELECT DISTINCT ON (candidate_id, job_id)
                candidate_id, job_id, id AS tid
            FROM candidate_stages
            ORDER BY candidate_id, job_id, moved_at DESC, id DESC
        ),
        by_id AS (
            SELECT candidate_id, job_id, MAX(id) AS mid
            FROM candidate_stages
            GROUP BY candidate_id, job_id
        )
        SELECT t.candidate_id, t.job_id,
               COUNT(*) OVER () AS total_count
        FROM by_time t
        JOIN by_id i
          ON i.candidate_id = t.candidate_id AND i.job_id = t.job_id
        WHERE t.tid <> i.mid
        ORDER BY t.candidate_id DESC, t.job_id DESC
        LIMIT :sample_limit
        """,
    ),
    (
        "custom_stage_legacy_new",
        "P1",
        "Latest wiersz z custom stage_def bez legacy_enum_value, zapisany "
        "jako legacy 'new' — semantyka etapu zlana do 'new' w raportach/UI.",
        f"""
        WITH latest AS ({_LATEST_CTE})
        SELECT l.candidate_id, l.job_id, l.id AS stage_id,
               COUNT(*) OVER () AS total_count
        FROM latest l
        JOIN pipeline_stage_defs d ON d.id = l.stage_def_id
        WHERE l.stage = 'new' AND d.legacy_enum_value IS NULL
        ORDER BY l.candidate_id DESC, l.job_id DESC
        LIMIT :sample_limit
        """,
    ),
    (
        "terminal_then_active",
        "P1",
        "Para ma wcześniejszy terminal (hired/rejected/withdrawn), a latest "
        "jest aktywny — niejawny reopen bez komendy/kompensacji.",
        f"""
        WITH latest AS ({_LATEST_CTE})
        SELECT l.candidate_id, l.job_id,
               COUNT(*) OVER () AS total_count
        FROM latest l
        LEFT JOIN pipeline_stage_defs d ON d.id = l.stage_def_id
        WHERE NOT {_TERMINAL_ROW}
          AND EXISTS (
            SELECT 1
            FROM candidate_stages e
            LEFT JOIN pipeline_stage_defs ed ON ed.id = e.stage_def_id
            WHERE e.candidate_id = l.candidate_id
              AND e.job_id = l.job_id
              AND (COALESCE(ed.is_terminal, FALSE)
                   OR e.stage IN ('hired', 'rejected', 'withdrawn'))
          )
        ORDER BY l.candidate_id DESC, l.job_id DESC
        LIMIT :sample_limit
        """,
    ),
    (
        "multiple_live_contracts",
        "P1",
        "Kandydat z >1 kontraktem w statusie active/ending — ryzyko "
        "zduplikowanego placementu.",
        """
        SELECT candidate_id, COUNT(*) AS live_contracts,
               COUNT(*) OVER () AS total_count
        FROM contracts
        WHERE status IN ('active', 'ending')
        GROUP BY candidate_id
        HAVING COUNT(*) > 1
        ORDER BY candidate_id DESC
        LIMIT :sample_limit
        """,
    ),
    (
        "rejection_emails_pending_overdue",
        "P1",
        "Zaplanowane maile odrzucenia w statusie pending przeterminowane "
        ">1h — backlog dispatchera (outbox-like).",
        """
        SELECT id AS scheduled_email_id, candidate_id, job_id,
               COUNT(*) OVER () AS total_count
        FROM scheduled_rejection_emails
        WHERE status = 'pending'
          AND scheduled_at < NOW() - INTERVAL '1 hour'
        ORDER BY id DESC
        LIMIT :sample_limit
        """,
    ),
    (
        "rejection_email_for_restored",
        "P1",
        "Pending mail odrzucenia, choć latest stage pary nie jest już "
        "rejected/withdrawn — restore nie anulował wysyłki (P1.7).",
        f"""
        WITH latest AS ({_LATEST_CTE})
        SELECT e.id AS scheduled_email_id, e.candidate_id, e.job_id,
               COUNT(*) OVER () AS total_count
        FROM scheduled_rejection_emails e
        JOIN latest l
          ON l.candidate_id = e.candidate_id AND l.job_id = e.job_id
        LEFT JOIN pipeline_stage_defs d ON d.id = l.stage_def_id
        WHERE e.status = 'pending'
          AND NOT (
            l.stage IN ('rejected', 'withdrawn')
            OR COALESCE(d.terminal_type::text, '')
               IN ('rejected', 'withdrawn')
          )
        ORDER BY e.id DESC
        LIMIT :sample_limit
        """,
    ),
    (
        "contract_no_hired",
        "P2",
        "Nie-draft Contract wskazujący job, którego para candidate+job "
        "nigdy nie miała etapu hired.",
        """
        SELECT c.id AS contract_id, c.candidate_id, c.job_id,
               COUNT(*) OVER () AS total_count
        FROM contracts c
        WHERE c.job_id IS NOT NULL
          AND c.status <> 'draft'
          AND NOT EXISTS (
            SELECT 1 FROM candidate_stages cs
            WHERE cs.candidate_id = c.candidate_id
              AND cs.job_id = c.job_id
              AND (
                cs.stage = 'hired'
                OR EXISTS (
                    SELECT 1 FROM pipeline_stage_defs d
                    WHERE d.id = cs.stage_def_id
                      AND d.terminal_type = 'hired'
                )
              )
          )
        ORDER BY c.id DESC
        LIMIT :sample_limit
        """,
    ),
    (
        "active_on_closed_job",
        "P2",
        "Latest aktywny (nieterminalny) wiersz na jobie w statusie closed.",
        f"""
        WITH latest AS ({_LATEST_CTE})
        SELECT l.candidate_id, l.job_id,
               COUNT(*) OVER () AS total_count
        FROM latest l
        JOIN jobs j ON j.id = l.job_id
        LEFT JOIN pipeline_stage_defs d ON d.id = l.stage_def_id
        WHERE j.status = 'closed' AND NOT {_TERMINAL_ROW}
        ORDER BY l.candidate_id DESC, l.job_id DESC
        LIMIT :sample_limit
        """,
    ),
    (
        "cv_sent_no_snapshot",
        "P2",
        "Wiersz cv_sent bez snapshotu CV (candidate_stage_cvs) — nie da się "
        "wykazać, jaki materiał widział klient.",
        """
        SELECT cs.candidate_id, cs.job_id, cs.id AS stage_id,
               COUNT(*) OVER () AS total_count
        FROM candidate_stages cs
        WHERE cs.stage = 'cv_sent'
          AND NOT EXISTS (
            SELECT 1 FROM candidate_stage_cvs v
            WHERE v.candidate_stage_id = cs.id
          )
        ORDER BY cs.id DESC
        LIMIT :sample_limit
        """,
    ),
    (
        "share_tokens_no_expiry",
        "P2",
        "Aktywne (nieodwołane) tokeny publicznych linków CV bez expires_at — "
        "wieczne linki do PII. Sample = ID snapshotu CV, nie raw token.",
        """
        SELECT t.candidate_stage_cv_id,
               COUNT(*) OVER () AS total_count
        FROM cv_share_tokens t
        WHERE t.expires_at IS NULL AND t.revoked IS FALSE
        ORDER BY t.candidate_stage_cv_id DESC
        LIMIT :sample_limit
        """,
    ),
    (
        "stale_cards_over_90d",
        "P2",
        "Latest aktywne karty na otwartych jobach starsze niż 90 dni w tym "
        "samym etapie (obserwacja live: karty do 94 dni).",
        f"""
        WITH latest AS ({_LATEST_CTE})
        SELECT l.candidate_id, l.job_id,
               COUNT(*) OVER () AS total_count
        FROM latest l
        JOIN jobs j ON j.id = l.job_id
        LEFT JOIN pipeline_stage_defs d ON d.id = l.stage_def_id
        WHERE j.status <> 'closed'
          AND NOT {_TERMINAL_ROW}
          AND l.moved_at < NOW() - INTERVAL '90 days'
        ORDER BY l.candidate_id DESC, l.job_id DESC
        LIMIT :sample_limit
        """,
    ),
    (
        "duplicate_external_ids",
        "P2",
        "Zduplikowane (external_source, external_id) na candidate_stages — "
        "powinno być niemożliwe po partial unique z migracji 0075.",
        """
        SELECT external_source, external_id, COUNT(*) AS occurrences,
               COUNT(*) OVER () AS total_count
        FROM candidate_stages
        WHERE external_id IS NOT NULL
        GROUP BY external_source, external_id
        HAVING COUNT(*) > 1
        ORDER BY occurrences DESC, external_id DESC
        LIMIT :sample_limit
        """,
    ),
]

_TOTALS_SQL = f"""
    WITH latest AS ({_LATEST_CTE})
    SELECT
        (SELECT COUNT(*) FROM candidate_stages) AS stage_rows,
        (SELECT COUNT(*) FROM latest) AS pairs,
        (
            SELECT COUNT(*)
            FROM latest l
            LEFT JOIN pipeline_stage_defs d ON d.id = l.stage_def_id
            WHERE NOT {_TERMINAL_ROW}
        ) AS open_pairs,
        (
            SELECT COUNT(*) FROM candidate_stages
            WHERE verification_status = 'pending'
        ) AS pending_rows,
        (
            SELECT COUNT(*) FROM scheduled_rejection_emails
            WHERE status = 'pending'
        ) AS rejection_emails_pending
"""


async def _run_check(
    db: AsyncSession, key: str, severity: str, description: str, sql: str
) -> dict[str, Any]:
    """Execute one anomaly query; never raise — report error inline."""
    started = time.monotonic()
    try:
        result = await asyncio.wait_for(
            db.execute(text(sql), {"sample_limit": SAMPLE_LIMIT}),
            timeout=CHECK_TIMEOUT_SECONDS,
        )
        rows = result.mappings().all()
        count = int(rows[0]["total_count"]) if rows else 0
        sample = [
            {k: v for k, v in row.items() if k != "total_count"} for row in rows
        ]
        return {
            "key": key,
            "severity": severity,
            "description": description,
            "count": count,
            "sample": sample,
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        }
    except Exception as exc:  # noqa: BLE001 — raport ma przeżyć błąd checku
        return {
            "key": key,
            "severity": severity,
            "description": description,
            "count": None,
            "sample": [],
            "elapsed_ms": int((time.monotonic() - started) * 1000),
            "error": f"{type(exc).__name__}: {exc}",
        }


@router.get(
    "/pipeline-inventory",
    summary="Read-only raport anomalii lifecycle pipeline (M4 PR-00)",
)
async def pipeline_inventory(
    auth_mode: Annotated[str, Depends(_snapshot_auth)],
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    started = time.monotonic()

    totals: dict[str, Any]
    try:
        totals_row = (
            (await asyncio.wait_for(
                db.execute(text(_TOTALS_SQL)), timeout=CHECK_TIMEOUT_SECONDS
            ))
            .mappings()
            .one()
        )
        totals = dict(totals_row)
    except Exception as exc:  # noqa: BLE001
        totals = {"error": f"{type(exc).__name__}: {exc}"}

    checks = [
        await _run_check(db, key, severity, description, sql)
        for key, severity, description, sql in _CHECKS
    ]

    counted = [c for c in checks if c["count"] is not None]
    return {
        "query_version": QUERY_VERSION,
        "generated_at": datetime.now(tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        "sample_limit": SAMPLE_LIMIT,
        "totals": totals,
        "summary": {
            "checks_total": len(checks),
            "checks_failed": len(checks) - len(counted),
            "anomalies_p0": sum(
                c["count"] for c in counted if c["severity"] == "P0"
            ),
            "anomalies_p1": sum(
                c["count"] for c in counted if c["severity"] == "P1"
            ),
            "anomalies_p2": sum(
                c["count"] for c in counted if c["severity"] == "P2"
            ),
        },
        "checks": checks,
        "elapsed_ms": int((time.monotonic() - started) * 1000),
        "auth_mode": auth_mode,
    }
