"""Wykluczone placementy — reguła wykrywania i jedyne źródło SQL-a (0343).

Decyzje właściciela (22.09.2026):

A. Seria z 24–25.09.2025 (jedno konto ustawiło 45 parom „Zatrudniony" w dwa
   dni, wiersze z importu Traffita) NIE liczy się jako placement nigdzie —
   Insights, Rada (z tabelami rok do roku), KPI, wyścigi, pulpity, raporty,
   kreator metryk, kampanie, ścieżka rozwoju, Hall of Fame. Wykluczona jest
   CAŁA seria (wszystkie 45 par, także 10 z „CV wysłane"). Historia etapów
   zostaje w bazie — nigdy nie kasujemy ``candidate_stages``.
B. Na przyszłość: seria = jedno konto ustawia „Zatrudniony" co najmniej
   ``SERIES_THRESHOLD`` parom w jednym dniu kalendarzowym (Europe/Warsaw).
   Z takiej serii wykluczane są automatycznie pary BEZ etapu „CV wysłane".
C. Admin widzi listę wykluczeń (``GET /api/admin/placement-exclusions``).

Co jest „serią": liczymy PIERWSZE wejście pary (kandydat, rekrutacja) na
„Zatrudniony" — to samo, co widok liczy jako placement — per (konto, dzień
warszawski). Seria liczy się po WSZYSTKICH parach tego konta z tego dnia;
filtr „bez CV" wybiera z niej wyłącznie pary do wykluczenia.

Historyczna seria jest rozpoznawana REGUŁĄ na danych (konto z co najmniej
``SERIES_THRESHOLD`` pierwszymi zatrudnieniami w danym dniu, dni
``HISTORICAL_SERIES_DAYS``), nigdy po ID osoby, konta czy kandydata — repo
jest publiczne, a ID z produkcji nie mają tu czego szukać.

Wykluczenie działa po PARZE: pomijamy wszystkie wiersze ``hired`` tej pary.
Import Traffita dopisuje wiersz na każde zdarzenie, więc wykluczenie jednego
wiersza odsłoniłoby następny (zduplikowany) jako „pierwsze zatrudnienie".

Gdzie działa:

* widok ``analytics_first_milestones`` (``VIEW_SQL`` niżej, lustro
  w ``entrypoint.sh``) — Insights, Rada, Hall of Fame, kampanie, seniority,
  pulpity, kreator metryk, gałąź ``legacy`` w ``VERIFIER_ANCHORED_CTE``;
* ``VERIFIER_ANCHORED_CTE`` — gałąź ``classified`` czyta ``candidate_stages``
  wprost, więc dostaje ``excluded_hired_sql("cs")``;
* liczniki czytające ``candidate_stages`` wprost —
  ``not_excluded_placement(...)`` (SQLAlchemy).

Wykrywanie dobowe: ``run_detection_safely`` po nocnym imporcie Traffita
(``tasks/traffit_sync.py``) i przed zamrożeniem wyścigów
(``tasks/competition_autofreeze.py``). Idempotentne, NIGDY nie zdejmuje
istniejących wykluczeń.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import and_, exists, select, text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

RULE_VERSION = 1
SERIES_THRESHOLD = 10
SERIES_TZ = "Europe/Warsaw"

REASON_NO_CV = "admin_bulk_no_cv"
REASON_2025_09_SERIES = "admin_bulk_2025_09_series"
REASONS: tuple[str, ...] = (REASON_NO_CV, REASON_2025_09_SERIES)
REASON_LABELS_PL: dict[str, str] = {
    REASON_NO_CV: (
        "Seria „Zatrudniony” jednego konta (co najmniej "
        f"{SERIES_THRESHOLD} par w dniu) bez etapu „CV wysłane”"
    ),
    REASON_2025_09_SERIES: "Masowe ustawienie „Zatrudniony” 24–25.09.2025",
}

# Dni historycznej serii (decyzja A). Daty, nie ID — reguła wyżej rozpoznaje
# konto po liczbie zatrudnień, a nie po tym, kim jest.
HISTORICAL_SERIES_DAYS: tuple[str, ...] = ("2025-09-24", "2025-09-25")

SEED_MARKER = "0343_placement_exclusions"

MILESTONE_STAGES_SQL = (
    "'verified', 'cv_sent', 'interview', 'client_interview', 'acceptance', 'hired'"
)


def excluded_pair_exists_sql(alias: str) -> str:
    """``EXISTS`` — para wiersza ``alias`` jest na liście wykluczeń."""
    return (
        "EXISTS (SELECT 1 FROM placement_exclusions pe "
        f"WHERE pe.candidate_id = {alias}.candidate_id "
        f"AND pe.job_id = {alias}.job_id)"
    )


def excluded_hired_sql(alias: str) -> str:
    """Predykat dla surowych zapytań na ``candidate_stages``: przepuszcza
    każdy etap poza ``hired`` wykluczonej pary."""
    return f"({alias}.stage::text <> 'hired' OR NOT {excluded_pair_exists_sql(alias)})"


def not_excluded_placement(candidate_col: Any, job_col: Any):
    """SQLAlchemy: para (kandydat, rekrutacja) NIE jest wykluczonym placementem.

    Dla zapytań, które liczą wyłącznie wiersze ``hired`` z ``candidate_stages``
    (np. „zatrudnieni w tym miesiącu", wypełnione wakaty w raportach).
    """
    from app.models.placement_exclusion import PlacementExclusion

    return ~exists().where(
        and_(
            PlacementExclusion.candidate_id == candidate_col,
            PlacementExclusion.job_id == job_col,
        )
    )


# ── Widok kanoniczny ─────────────────────────────────────────────────────────

# Lista kolumn IDENTYCZNA z 0184 — CREATE OR REPLACE VIEW nie pozwala jej
# zmienić, a konsumenci czytają ją po nazwach.
VIEW_SQL = f"""
    CREATE OR REPLACE VIEW analytics_first_milestones AS
    SELECT
        candidate_id,
        job_id,
        stage,
        moved_at AS first_reached_at,
        moved_by AS first_moved_by,
        id AS candidate_stage_id
    FROM (
        SELECT
            cs.candidate_id,
            cs.job_id,
            cs.stage,
            cs.moved_at,
            cs.moved_by,
            cs.id,
            ROW_NUMBER() OVER (
                PARTITION BY cs.candidate_id, cs.job_id, cs.stage
                ORDER BY cs.moved_at ASC, cs.id ASC
            ) AS rn
        FROM candidate_stages cs
        WHERE cs.stage IN ({MILESTONE_STAGES_SQL})
          AND (cs.stage <> 'verified' OR cs.verification_status = 'active')
          AND (
              cs.stage <> 'hired'
              OR NOT EXISTS (
                  SELECT 1 FROM placement_exclusions pe
                  WHERE pe.candidate_id = cs.candidate_id
                    AND pe.job_id = cs.job_id
              )
          )
    ) ranked
    WHERE rn = 1
"""

# Definicja sprzed 0343 (0184) — do downgrade.
PREVIOUS_VIEW_SQL = f"""
    CREATE OR REPLACE VIEW analytics_first_milestones AS
    SELECT
        candidate_id,
        job_id,
        stage,
        moved_at AS first_reached_at,
        moved_by AS first_moved_by,
        id AS candidate_stage_id
    FROM (
        SELECT
            cs.candidate_id,
            cs.job_id,
            cs.stage,
            cs.moved_at,
            cs.moved_by,
            cs.id,
            ROW_NUMBER() OVER (
                PARTITION BY cs.candidate_id, cs.job_id, cs.stage
                ORDER BY cs.moved_at ASC, cs.id ASC
            ) AS rn
        FROM candidate_stages cs
        WHERE cs.stage IN ({MILESTONE_STAGES_SQL})
          AND (cs.stage <> 'verified' OR cs.verification_status = 'active')
    ) ranked
    WHERE rn = 1
"""

TABLE_DDL: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS placement_exclusions (
        id BIGSERIAL PRIMARY KEY,
        candidate_id INTEGER NOT NULL
            REFERENCES candidates(id) ON DELETE CASCADE,
        job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
        candidate_stage_id INTEGER
            REFERENCES candidate_stages(id) ON DELETE SET NULL,
        reason VARCHAR(40) NOT NULL,
        rule_version INTEGER NOT NULL DEFAULT 1,
        detected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        details JSONB NOT NULL DEFAULT '{}'::jsonb,
        CONSTRAINT uq_placement_exclusions_candidate_job
            UNIQUE (candidate_id, job_id),
        CONSTRAINT ck_placement_exclusions_reason
            CHECK (reason IN ('admin_bulk_no_cv', 'admin_bulk_2025_09_series'))
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_placement_exclusions_job_id "
    "ON placement_exclusions (job_id)",
)


# ── Wykrywanie ───────────────────────────────────────────────────────────────

# Pierwsze „Zatrudniony" każdej pary + seria (konto, dzień warszawski).
# `stage::text`, bo porównanie enumu z literałem spoza enumu to błąd.
_SERIES_CTE = f"""
    WITH first_hired AS (
        SELECT DISTINCT ON (cs.candidate_id, cs.job_id)
               cs.id AS candidate_stage_id,
               cs.candidate_id,
               cs.job_id,
               cs.moved_by,
               (cs.moved_at AT TIME ZONE '{SERIES_TZ}')::date AS series_day
        FROM candidate_stages cs
        WHERE cs.stage::text = 'hired'
          AND cs.job_id IS NOT NULL
        ORDER BY cs.candidate_id, cs.job_id, cs.moved_at ASC, cs.id ASC
    ),
    series AS (
        SELECT moved_by, series_day, count(*) AS series_size
        FROM first_hired
        WHERE moved_by IS NOT NULL
        GROUP BY moved_by, series_day
        HAVING count(*) >= :threshold
    ),
    candidates_in_series AS (
        SELECT fh.candidate_stage_id,
               fh.candidate_id,
               fh.job_id,
               fh.moved_by,
               fh.series_day,
               s.series_size,
               EXISTS (
                   SELECT 1 FROM candidate_stages cv
                   WHERE cv.candidate_id = fh.candidate_id
                     AND cv.job_id = fh.job_id
                     AND cv.stage::text = 'cv_sent'
               ) AS had_cv_sent
        FROM first_hired fh
        JOIN series s
          ON s.moved_by = fh.moved_by AND s.series_day = fh.series_day
    )
"""

_INSERT_TAIL = """
    INSERT INTO placement_exclusions (
        candidate_id, job_id, candidate_stage_id, reason, rule_version, details
    )
    SELECT candidate_id,
           job_id,
           candidate_stage_id,
           :reason,
           :rule_version,
           jsonb_build_object(
               'mover_user_id', moved_by,
               'series_day', series_day::text,
               'series_size', series_size,
               'had_cv_sent', had_cv_sent
           )
    FROM candidates_in_series
    WHERE {where}
      -- Zawężenie WYŁĄCZNIE dla testów na wspólnej bazie (NULL = cała baza).
      -- Seria i tak liczy się po wszystkich parach konta z danego dnia.
      AND (
          CAST(:only AS integer[]) IS NULL
          OR candidate_id = ANY(CAST(:only AS integer[]))
      )
    ON CONFLICT (candidate_id, job_id) DO NOTHING
    RETURNING candidate_stage_id
"""

# A. Historyczna seria — CAŁA, także pary z „CV wysłane".
HISTORICAL_SERIES_SQL = _SERIES_CTE + _INSERT_TAIL.format(
    where="series_day::text IN ("
    + ", ".join(f"'{day}'" for day in HISTORICAL_SERIES_DAYS)
    + ")"
)

# B. Reguła na całą historię — wyłącznie pary BEZ „CV wysłane".
RULE_SQL = _SERIES_CTE + _INSERT_TAIL.format(where="NOT had_cv_sent")


def _params(reason: str, only: Optional[list[int]] = None) -> dict[str, Any]:
    return {
        "threshold": SERIES_THRESHOLD,
        "reason": reason,
        "rule_version": RULE_VERSION,
        "only": only,
    }


def historical_params(only: Optional[list[int]] = None) -> dict[str, Any]:
    return _params(REASON_2025_09_SERIES, only)


def rule_params(only: Optional[list[int]] = None) -> dict[str, Any]:
    return _params(REASON_NO_CV, only)


def receipt(historical_ids: list[int], rule_ids: list[int]) -> dict[str, Any]:
    """Paragon w ``app_settings`` — WYŁĄCZNIE liczby i ID wierszy etapów."""
    return {
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "rule_version": RULE_VERSION,
        "threshold": SERIES_THRESHOLD,
        "historical_series_excluded": len(historical_ids),
        "rule_excluded": len(rule_ids),
        "historical_candidate_stage_ids": sorted(i for i in historical_ids if i),
        "rule_candidate_stage_ids": sorted(i for i in rule_ids if i),
    }


RECEIPT_SQL = (
    "INSERT INTO app_settings (key, value) VALUES (:key, CAST(:value AS jsonb)) "
    "ON CONFLICT (key) DO NOTHING"
)


async def run_seed(db: AsyncSession) -> Optional[dict[str, Any]]:
    """Jednorazowe zasianie (A + B na całą historię) z paragonem.

    Lustro migracji 0343 dla ``entrypoint.sh`` (prod alembic bywa osierocony).
    Advisory lock + znacznik → drugi start kończy się natychmiast. Wołający
    commituje. ``None`` = już wykonane.
    """
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": SEED_MARKER}
    )
    done = await db.scalar(
        text("SELECT 1 FROM app_settings WHERE key = :key"), {"key": SEED_MARKER}
    )
    if done:
        return None
    historical = [
        row[0]
        for row in (
            await db.execute(text(HISTORICAL_SERIES_SQL), historical_params())
        ).all()
    ]
    rule = [row[0] for row in (await db.execute(text(RULE_SQL), rule_params())).all()]
    summary = receipt(historical, rule)
    await db.execute(
        text(RECEIPT_SQL), {"key": SEED_MARKER, "value": json.dumps(summary)}
    )
    return summary


async def detect_new_series(
    db: AsyncSession, *, only_candidate_ids: Optional[list[int]] = None
) -> int:
    """Reguła B na całej historii. Zwraca liczbę NOWYCH wykluczeń.

    Idempotentne (``ON CONFLICT DO NOTHING``) i nigdy nie zdejmuje wykluczeń.
    Wołający commituje. ``only_candidate_ids`` zawęża ZAPIS — wyłącznie dla
    testów, które nie mogą ruszać cudzych wierszy we wspólnej bazie.
    """
    rows = (await db.execute(text(RULE_SQL), rule_params(only_candidate_ids))).all()
    return len(rows)


async def run_detection_safely(trigger: str) -> int:
    """Dobowe wykrywanie we własnej sesji. Nigdy nie rzuca.

    Liczba nowych wykluczeń trafia do logu (bez ID — log idzie do Loki).
    """
    from app.core.database import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as db:
            inserted = await detect_new_series(db)
            await db.commit()
    except Exception:  # noqa: BLE001 — statystyka nie może wywrócić importu
        logger.exception("placement exclusion detection failed (%s)", trigger)
        return 0
    if inserted:
        logger.warning(
            "placement exclusions: %d new pair(s) excluded (%s)", inserted, trigger
        )
        try:
            from app.core.cache import cache_invalidate

            await cache_invalidate("analytics:")
        except Exception:  # noqa: BLE001
            logger.debug("cache invalidation after exclusion failed", exc_info=True)
    return inserted


async def list_exclusions(db: AsyncSession) -> list[dict[str, Any]]:
    """Lista dla admina — nazwiska, rekrutacja, klient, kto i kiedy."""
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.job import Job
    from app.models.placement_exclusion import PlacementExclusion
    from app.models.recruitment_pipeline import CandidateStage
    from app.models.user import User

    stmt = (
        select(
            PlacementExclusion,
            Candidate.name,
            Candidate.lastname,
            Job.title,
            Client.id,
            Client.name,
            CandidateStage.moved_at,
            CandidateStage.moved_by,
        )
        .join(Candidate, Candidate.id == PlacementExclusion.candidate_id)
        .join(Job, Job.id == PlacementExclusion.job_id)
        .outerjoin(Client, Client.id == Job.client_id)
        .outerjoin(
            CandidateStage, CandidateStage.id == PlacementExclusion.candidate_stage_id
        )
        .order_by(
            CandidateStage.moved_at.desc().nulls_last(),
            PlacementExclusion.id.desc(),
        )
    )
    rows = (await db.execute(stmt)).all()
    mover_ids: set[int] = set()
    for row in rows:
        exclusion = row[0]
        mover = row.moved_by or (exclusion.details or {}).get("mover_user_id")
        if isinstance(mover, int):
            mover_ids.add(mover)
    names: dict[int, str] = {}
    if mover_ids:
        for uid, user_name, email in (
            await db.execute(
                select(User.id, User.name, User.email).where(
                    User.id.in_(sorted(mover_ids))
                )
            )
        ).all():
            names[uid] = user_name or email
    out: list[dict[str, Any]] = []
    for row in rows:
        exclusion: Any = row[0]
        details = exclusion.details or {}
        mover = row.moved_by or details.get("mover_user_id")
        candidate_name = " ".join(p for p in (row[1], row[2]) if p).strip()
        out.append(
            {
                "id": exclusion.id,
                "candidate_id": exclusion.candidate_id,
                "candidate_name": candidate_name
                or f"Kandydat #{exclusion.candidate_id}",
                "job_id": exclusion.job_id,
                "job_title": row[3],
                "client_id": row[4],
                "client_name": row[5],
                "hired_at": row.moved_at,
                "moved_by_user_id": mover if isinstance(mover, int) else None,
                "moved_by_name": names.get(mover) if isinstance(mover, int) else None,
                "reason": exclusion.reason,
                "reason_label": REASON_LABELS_PL.get(
                    exclusion.reason, exclusion.reason
                ),
                "had_cv_sent": details.get("had_cv_sent"),
                "series_day": details.get("series_day"),
                "series_size": details.get("series_size"),
                "rule_version": exclusion.rule_version,
                "detected_at": exclusion.detected_at,
            }
        )
    return out
