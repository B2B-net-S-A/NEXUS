"""Read-only analytics v1 queries backed exclusively by live ATS data.

The migration that accompanies this module creates three ordinary views:
latest pipeline state, first canonical milestones and candidate first-touch
source.  Keeping those definitions in PostgreSQL makes dashboard, KPI and
future competition consumers share exactly the same semantics.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.periods import AnalyticsPeriod, WARSAW
from app.analytics.schemas import (
    CallsData,
    KpiTargets,
    MetricDefinition,
    MetricsMetaData,
    OverviewCandidates,
    OverviewClients,
    OverviewContracts,
    OverviewData,
    OverviewJobs,
    OverviewPipeline,
    PersonalKpiData,
    PipelineSnapshotData,
    PrecisionMetric,
    RecentHire,
    RecentHiresData,
    RecruitmentFunnelData,
    SourceMetric,
    SourcesData,
    StageCount,
    TeamCallRow,
    TeamCallsData,
    TeamKpiRow,
    TeamKpisData,
)
from app.core.config import settings


_OVERVIEW_SQL = text(
    """
    SELECT
      (SELECT count(*) FROM candidates) AS candidates_total,
      (SELECT count(*) FROM candidates WHERE status = 'active')
        AS candidates_active,
      (SELECT count(*) FROM jobs) AS jobs_total,
      (SELECT count(*) FROM jobs WHERE status = 'published') AS jobs_open,
      (SELECT count(*) FROM clients) AS clients_total,
      (SELECT count(*) FROM clients WHERE status = 'active') AS clients_active,
      (
        SELECT count(*) FROM contracts
        WHERE status IN ('active', 'ending')
          AND start_date <= :report_date
          AND (end_date IS NULL OR end_date >= :report_date)
      ) AS contracts_active,
      (
        SELECT count(*) FROM contracts
        WHERE status IN ('active', 'ending')
          AND start_date IS NOT NULL
          AND start_date <= :report_date
          AND end_date >= :report_date
          AND end_date < :expiry_end
      ) AS contracts_expiring,
      (
        SELECT count(*) FROM contracts
        WHERE status IN ('active', 'ending')
          AND start_date IS NULL
      ) AS contracts_incomplete_dates,
      (
        SELECT count(*) FROM analytics_first_candidate_milestones
        WHERE stage = 'hired'
          AND reached_at >= :period_start
          AND reached_at < :period_end
      ) AS placements
    """
)

_PIPELINE_SQL = text(
    """
    SELECT stage, count(*) AS candidates
    FROM analytics_latest_candidate_stages
    GROUP BY stage
    ORDER BY stage
    """
)

_FUNNEL_SQL = text(
    """
    WITH first_in_period AS (
      SELECT cs.candidate_id, cs.job_id, cs.stage::text AS stage
      FROM candidate_stages cs
      WHERE cs.stage IN (
        'verified', 'cv_sent', 'interview', 'client_interview', 'hired'
      )
        AND cs.moved_at >= :period_start
        AND cs.moved_at < :period_end
        AND NOT EXISTS (
          SELECT 1
          FROM candidate_stages earlier
          WHERE earlier.candidate_id = cs.candidate_id
            AND earlier.job_id = cs.job_id
            AND earlier.stage = cs.stage
            AND (
              earlier.moved_at < cs.moved_at
              OR (earlier.moved_at = cs.moved_at AND earlier.id < cs.id)
            )
        )
    )
    SELECT
      count(*) FILTER (WHERE stage = 'verified') AS verified,
      count(*) FILTER (WHERE stage = 'cv_sent') AS recommended,
      count(*) FILTER (WHERE stage = 'interview') AS internal_interview,
      count(*) FILTER (WHERE stage = 'client_interview') AS client_interview,
      count(*) FILTER (WHERE stage = 'hired') AS placed
    FROM first_in_period
    """
)

_RECENT_HIRES_SQL = text(
    """
    SELECT
      m.candidate_id,
      concat_ws(' ', nullif(c.name, '?'), nullif(c.lastname, '?')) AS candidate_name,
      m.job_id,
      j.title AS job_title,
      cl.id AS client_id,
      coalesce(nullif(cl.display_name, ''), cl.name) AS client_name,
      m.reached_at AS hired_at
    FROM analytics_first_candidate_milestones m
    JOIN candidates c ON c.id = m.candidate_id
    JOIN jobs j ON j.id = m.job_id
    JOIN clients cl ON cl.id = j.client_id
    WHERE m.stage = 'hired'
      AND m.reached_at >= :period_start
      AND m.reached_at < :period_end
    ORDER BY m.reached_at DESC, m.candidate_stage_id DESC
    LIMIT :limit
    """
)

_SOURCES_SQL = text(
    """
    WITH first_events AS (
      SELECT e.candidate_id, e.channel::text AS source, e.captured_at AS first_touch_at
      FROM candidate_source_events e
      WHERE e.captured_at >= :period_start
        AND e.captured_at < :period_end
        AND NOT EXISTS (
          SELECT 1
          FROM candidate_source_events earlier
          WHERE earlier.candidate_id = e.candidate_id
            AND (
              earlier.captured_at < e.captured_at
              OR (earlier.captured_at = e.captured_at AND earlier.id < e.id)
            )
        )
    ), candidate_fallback AS (
      SELECT
        c.id AS candidate_id,
        CASE
          WHEN c.source_enum IS NOT NULL THEN c.source_enum::text
          WHEN lower(trim(c.source)) IN (
            'linkedin', 'pracuj', 'jjit', 'referral', 'database', 'manual'
          ) THEN lower(trim(c.source))
          WHEN nullif(trim(c.source), '') IS NULL THEN 'unknown'
          ELSE 'other'
        END AS source,
        c.created_at AS first_touch_at
      FROM candidates c
      WHERE c.created_at >= :period_start
        AND c.created_at < :period_end
        AND NOT EXISTS (
          SELECT 1
          FROM candidate_source_events e
          WHERE e.candidate_id = c.id
        )
    ), cohort AS (
      SELECT candidate_id, source, first_touch_at FROM first_events
      UNION ALL
      SELECT candidate_id, source, first_touch_at FROM candidate_fallback
    )
    SELECT
      cohort.source,
      count(DISTINCT cohort.candidate_id) AS cohort_candidates,
      count(DISTINCT cohort.candidate_id) FILTER (
        WHERE first_hire.first_hired_at >= cohort.first_touch_at
          AND first_hire.first_hired_at < :period_end
      ) AS placed_by_period_end
    FROM cohort
    LEFT JOIN LATERAL (
      SELECT cs.moved_at AS first_hired_at
      FROM candidate_stages cs
      WHERE cs.candidate_id = cohort.candidate_id
        AND cs.stage = 'hired'
      ORDER BY cs.moved_at ASC, cs.id ASC
      LIMIT 1
    ) first_hire ON TRUE
    GROUP BY cohort.source
    ORDER BY cohort_candidates DESC, cohort.source ASC
    """
)

_VIEWER_SAFE_SOURCE_KEYS = frozenset(
    {
        "linkedin",
        "pracuj",
        "jjit",
        "referral",
        "database",
        "manual",
        "aktywny_search",
        "cv_upload",
        "email",
        "posting",
        "import_csv",
        "unknown",
        "other",
    }
)


def _viewer_safe_source(value: object) -> str:
    """Prevent free-form legacy source values from leaking through viewer API."""

    normalized = str(value or "unknown").strip().lower()
    return normalized if normalized in _VIEWER_SAFE_SOURCE_KEYS else "other"


_CALLS_SQL = text(
    """
    SELECT
      count(*) AS completed,
      count(*) FILTER (WHERE direction = 'inbound') AS inbound,
      count(*) FILTER (WHERE direction = 'outbound') AS outbound,
      coalesce(sum(duration_seconds), 0) AS total_duration_seconds,
      avg(duration_seconds) FILTER (WHERE duration_seconds IS NOT NULL)
        AS average_duration_seconds
    FROM calls
    WHERE status = 'completed'
      AND coalesce(started_at, created_at) >= :period_start
      AND coalesce(started_at, created_at) < :period_end
    """
)

_MY_CALLS_SQL = text(
    """
    SELECT
      count(*) AS completed,
      count(*) FILTER (WHERE direction = 'inbound') AS inbound,
      count(*) FILTER (WHERE direction = 'outbound') AS outbound,
      coalesce(sum(duration_seconds), 0) AS total_duration_seconds,
      avg(duration_seconds) FILTER (WHERE duration_seconds IS NOT NULL)
        AS average_duration_seconds
    FROM calls
    WHERE status = 'completed'
      AND coalesce(started_at, created_at) >= :period_start
      AND coalesce(started_at, created_at) < :period_end
      AND user_id = :user_id
    """
)

_PERSONAL_KPI_SQL = text(
    """
    SELECT
      (
        SELECT count(*) FROM calls
        WHERE status = 'completed'
          AND user_id = :user_id
          AND coalesce(started_at, created_at) >= :period_start
          AND coalesce(started_at, created_at) < :period_end
      ) AS calls_completed,
      (
        SELECT count(*) FROM candidates
        WHERE created_by = :user_id
          AND created_at >= :period_start
          AND created_at < :period_end
      ) AS candidates_added,
      count(*) FILTER (
        WHERE stage = 'verified'
          AND reached_at >= :period_start AND reached_at < :period_end
      ) AS verifications,
      count(*) FILTER (
        WHERE stage = 'cv_sent'
          AND reached_at >= :period_start AND reached_at < :period_end
      ) AS recommendations,
      count(*) FILTER (
        WHERE stage = 'hired'
          AND reached_at >= :period_start AND reached_at < :period_end
      ) AS placements,
      count(*) FILTER (
        WHERE stage = 'verified'
          AND reached_at >= :precision_start AND reached_at < :precision_end
      ) AS precision_verified,
      count(*) FILTER (
        WHERE stage = 'cv_sent'
          AND reached_at >= :precision_start AND reached_at < :precision_end
      ) AS precision_recommended
    FROM analytics_first_candidate_milestones
    WHERE credited_user_id = :user_id
    """
)

_KPI_TARGETS_SQL = text(
    """
    SELECT kpi_id, target_value, priority
    FROM (
      SELECT kpi_id, target_value, 1 AS priority
      FROM user_kpi_targets
      WHERE user_id = :user_id
      UNION ALL
      SELECT kpi_id, target_value, 2 AS priority
      FROM kpi_role_defaults
      WHERE role::text = :role
    ) resolved
    ORDER BY kpi_id, priority
    """
)

_TEAM_TARGETS_SQL = text(
    """
    SELECT user_id, kpi_id, target_value, priority
    FROM (
      SELECT t.user_id, t.kpi_id, t.target_value, 1 AS priority
      FROM user_kpi_targets t
      JOIN users u ON u.id = t.user_id
      WHERE u.is_active IS TRUE
      UNION ALL
      SELECT u.id AS user_id, d.kpi_id, d.target_value, 2 AS priority
      FROM users u
      JOIN kpi_role_defaults d ON d.role = u.role
      WHERE u.is_active IS TRUE
    ) resolved
    ORDER BY user_id, kpi_id, priority
    """
)

_TEAM_KPI_SQL = text(
    """
    WITH milestone_counts AS (
      SELECT credited_user_id AS user_id,
        count(*) FILTER (WHERE stage = 'verified') AS verifications,
        count(*) FILTER (WHERE stage = 'cv_sent') AS recommendations,
        count(*) FILTER (WHERE stage = 'hired') AS placements
      FROM analytics_first_candidate_milestones
      WHERE reached_at >= :period_start AND reached_at < :period_end
        AND credited_user_id IS NOT NULL
      GROUP BY credited_user_id
    ), candidate_counts AS (
      SELECT created_by AS user_id, count(*) AS candidates_added
      FROM candidates
      WHERE created_at >= :period_start AND created_at < :period_end
        AND created_by IS NOT NULL
      GROUP BY created_by
    ), call_counts AS (
      SELECT user_id, count(*) AS calls_completed
      FROM calls
      WHERE status = 'completed'
        AND coalesce(started_at, created_at) >= :period_start
        AND coalesce(started_at, created_at) < :period_end
        AND user_id IS NOT NULL
      GROUP BY user_id
    )
    SELECT u.id AS user_id, u.name AS user_name, u.role::text AS primary_role,
      coalesce(cl.calls_completed, 0) AS calls_completed,
      coalesce(m.verifications, 0) AS verifications,
      coalesce(c.candidates_added, 0) AS candidates_added,
      coalesce(m.recommendations, 0) AS recommendations,
      coalesce(m.placements, 0) AS placements
    FROM users u
    LEFT JOIN milestone_counts m ON m.user_id = u.id
    LEFT JOIN candidate_counts c ON c.user_id = u.id
    LEFT JOIN call_counts cl ON cl.user_id = u.id
    WHERE u.is_active IS TRUE
      AND (
        u.role::text IN ('sourcer', 'recruiter', 'tac')
        OR u.roles ?| ARRAY['sourcer', 'recruiter', 'tac']
      )
    ORDER BY placements DESC, recommendations DESC, verifications DESC,
             calls_completed DESC, u.name ASC
    """
)

_TEAM_CALLS_SQL = text(
    """
    SELECT u.id AS user_id, u.name AS user_name,
      count(c.id) AS completed,
      coalesce(sum(c.duration_seconds), 0) AS total_duration_seconds,
      avg(c.duration_seconds) FILTER (WHERE c.duration_seconds IS NOT NULL)
        AS average_duration_seconds
    FROM users u
    LEFT JOIN calls c
      ON c.user_id = u.id
      AND c.status = 'completed'
      AND coalesce(c.started_at, c.created_at) >= :period_start
      AND coalesce(c.started_at, c.created_at) < :period_end
    WHERE u.is_active IS TRUE
      AND (
        u.role::text IN ('sourcer', 'recruiter', 'tac')
        OR u.roles ?| ARRAY['sourcer', 'recruiter', 'tac']
      )
    GROUP BY u.id, u.name
    ORDER BY completed DESC, u.name ASC
    """
)


def _integer(row: Any, key: str) -> int:
    return int(row[key] or 0)


def _optional_float(value: Any) -> float | None:
    return round(float(value), 2) if value is not None else None


_TARGET_ID_ALIASES: dict[str, str] = {
    "calls_daily": "calls_daily",
    "daily_activity_count": "calls_daily",
    "verifications_daily": "verifications_daily",
    "daily_verifications": "verifications_daily",
    "cv_added_daily": "cv_added_daily",
    "daily_new_candidates": "cv_added_daily",
    "placements_monthly": "placements_monthly",
    "monthly_placements": "placements_monthly",
    "precision_monthly": "precision_monthly",
}


def _target_value(
    resolved: dict[str, int],
    *target_ids: str,
    default: int | None,
) -> int | None:
    for target_id in target_ids:
        if target_id in resolved:
            return resolved[target_id]
    return default


def _record_target(
    candidates: dict[str, tuple[int, int, int]],
    *,
    raw_id: str,
    target_value: int,
    priority: int,
) -> None:
    """Resolve aliases while preserving user-over-role priority.

    Legacy and v1 target IDs may coexist during migration.  Priority 1 is a
    per-user override and must win even if it uses the legacy identifier;
    for equal priority the canonical identifier wins deterministically.
    """

    canonical_id = _TARGET_ID_ALIASES.get(raw_id, raw_id)
    candidate = (priority, 0 if raw_id == canonical_id else 1, target_value)
    current = candidates.get(canonical_id)
    if current is None or candidate[:2] < current[:2]:
        candidates[canonical_id] = candidate


def _kpi_targets(primary_role: str, resolved: dict[str, int]) -> KpiTargets:
    operational = primary_role in {"sourcer", "recruiter", "tac"}
    cv_target = 5 if primary_role in {"recruiter", "tac"} else None
    return KpiTargets(
        calls_daily=_target_value(
            resolved,
            "calls_daily",
            "daily_activity_count",
            default=settings.POWERCALLING_DAILY_TARGET,
        ),
        verifications_daily=_target_value(
            resolved,
            "verifications_daily",
            "daily_verifications",
            default=settings.VERIFICATIONS_DAILY_TARGET if operational else 0,
        ),
        candidates_added_daily=_target_value(
            resolved,
            "cv_added_daily",
            "daily_new_candidates",
            default=cv_target,
        ),
        placements_monthly=_target_value(
            resolved,
            "placements_monthly",
            "monthly_placements",
            default=1 if operational else 0,
        ),
        precision_pct=_target_value(
            resolved,
            "precision_monthly",
            default=75 if operational else 0,
        ),
    )


class AnalyticsV1Service:
    """Stateless canonical aggregation service."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def overview(
        self,
        period: AnalyticsPeriod,
        *,
        generated_at: datetime | None = None,
    ) -> OverviewData:
        generated = generated_at or datetime.now(WARSAW)
        if generated.tzinfo is None:
            generated = generated.replace(tzinfo=WARSAW)
        else:
            generated = generated.astimezone(WARSAW)
        # Point-in-time contract data uses the current Warsaw business date for
        # an open period, and the last included date for a historical period.
        # It must never silently use the first day of month/quarter/year.
        report_date = min(generated.date(), period.end.date() - timedelta(days=1))
        # Calendar-date arithmetic is correct here: expiry semantics are a
        # date range, while timestamp periods remain half-open and DST-safe.
        expiry_end = report_date + timedelta(days=31)
        result = await self.db.execute(
            _OVERVIEW_SQL,
            {
                "report_date": report_date,
                "expiry_end": expiry_end,
                "period_start": period.start,
                "period_end": period.end,
            },
        )
        row = result.mappings().one()
        return OverviewData(
            candidates=OverviewCandidates(
                total=_integer(row, "candidates_total"),
                active=_integer(row, "candidates_active"),
            ),
            jobs=OverviewJobs(
                total=_integer(row, "jobs_total"), open=_integer(row, "jobs_open")
            ),
            clients=OverviewClients(
                total=_integer(row, "clients_total"),
                active=_integer(row, "clients_active"),
            ),
            contracts=OverviewContracts(
                active=_integer(row, "contracts_active"),
                expiring_30_days=_integer(row, "contracts_expiring"),
                incomplete_date_data=_integer(row, "contracts_incomplete_dates"),
            ),
            pipeline=OverviewPipeline(placements=_integer(row, "placements")),
        )

    async def pipeline_snapshot(self) -> PipelineSnapshotData:
        result = await self.db.execute(_PIPELINE_SQL)
        stages = [
            StageCount(stage=str(row["stage"]), candidates=int(row["candidates"]))
            for row in result.mappings().all()
        ]
        return PipelineSnapshotData(
            total_pairs=sum(stage.candidates for stage in stages), stages=stages
        )

    async def recruitment_funnel(
        self, period: AnalyticsPeriod
    ) -> RecruitmentFunnelData:
        result = await self.db.execute(
            _FUNNEL_SQL,
            {"period_start": period.start, "period_end": period.end},
        )
        row = result.mappings().one()
        return RecruitmentFunnelData(
            verified=_integer(row, "verified"),
            recommended=_integer(row, "recommended"),
            internal_interview=_integer(row, "internal_interview"),
            client_interview=_integer(row, "client_interview"),
            placed=_integer(row, "placed"),
        )

    async def recent_hires(
        self, period: AnalyticsPeriod, *, limit: int = 10
    ) -> RecentHiresData:
        result = await self.db.execute(
            _RECENT_HIRES_SQL,
            {
                "period_start": period.start,
                "period_end": period.end,
                "limit": limit,
            },
        )
        return RecentHiresData(
            hires=[
                RecentHire(
                    candidate_id=int(row["candidate_id"]),
                    candidate_name=str(row["candidate_name"] or "Nieznany kandydat"),
                    job_id=int(row["job_id"]),
                    job_title=str(row["job_title"]),
                    client_id=int(row["client_id"]),
                    client_name=str(row["client_name"]),
                    hired_at=row["hired_at"],
                )
                for row in result.mappings().all()
            ]
        )

    async def sources(self, period: AnalyticsPeriod) -> SourcesData:
        result = await self.db.execute(
            _SOURCES_SQL,
            {"period_start": period.start, "period_end": period.end},
        )
        metrics: list[SourceMetric] = []
        for row in result.mappings().all():
            cohort = _integer(row, "cohort_candidates")
            # DISTINCT cohort SQL guarantees this invariant.  The clamp is a
            # final defensive barrier against drifted legacy views returning a
            # mathematically impossible conversion above 100%.
            placed = min(_integer(row, "placed_by_period_end"), cohort)
            metrics.append(
                SourceMetric(
                    source=_viewer_safe_source(row["source"]),
                    cohort_candidates=cohort,
                    placed_by_period_end=placed,
                    hire_rate_pct=round(placed * 100 / cohort, 2) if cohort else 0.0,
                )
            )
        return SourcesData(sources=metrics)

    async def calls(
        self, period: AnalyticsPeriod, *, user_id: int | None = None
    ) -> CallsData:
        query = _MY_CALLS_SQL if user_id is not None else _CALLS_SQL
        params: dict[str, Any] = {
            "period_start": period.start,
            "period_end": period.end,
        }
        if user_id is not None:
            params["user_id"] = user_id
        result = await self.db.execute(query, params)
        row = result.mappings().one()
        return CallsData(
            completed=_integer(row, "completed"),
            inbound=_integer(row, "inbound"),
            outbound=_integer(row, "outbound"),
            total_duration_seconds=_integer(row, "total_duration_seconds"),
            average_duration_seconds=_optional_float(row["average_duration_seconds"]),
        )

    async def personal_kpis(
        self,
        period: AnalyticsPeriod,
        *,
        user_id: int,
        primary_role: str,
        generated_at: datetime,
        calls_available: bool = True,
    ) -> PersonalKpiData:
        precision_end = min(generated_at, period.end)
        precision_start = precision_end - timedelta(days=30)
        result = await self.db.execute(
            _PERSONAL_KPI_SQL,
            {
                "user_id": user_id,
                "period_start": period.start,
                "period_end": period.end,
                "precision_start": precision_start,
                "precision_end": precision_end,
            },
        )
        row = result.mappings().one()
        verified = _integer(row, "precision_verified")
        recommended = _integer(row, "precision_recommended")
        precision = round(recommended * 100 / verified, 2) if verified >= 5 else None
        target_result = await self.db.execute(
            _KPI_TARGETS_SQL, {"user_id": user_id, "role": primary_role}
        )
        target_candidates: dict[str, tuple[int, int, int]] = {}
        for target_row in target_result.mappings().all():
            _record_target(
                target_candidates,
                raw_id=str(target_row["kpi_id"]),
                target_value=int(target_row["target_value"]),
                priority=int(target_row["priority"]),
            )
        resolved_targets = {
            target_id: candidate[2]
            for target_id, candidate in target_candidates.items()
        }
        return PersonalKpiData(
            calls_completed=(
                _integer(row, "calls_completed") if calls_available else None
            ),
            calls_available=calls_available,
            verifications=_integer(row, "verifications"),
            candidates_added=_integer(row, "candidates_added"),
            recommendations=_integer(row, "recommendations"),
            placements=_integer(row, "placements"),
            precision_30d=PrecisionMetric(
                value_pct=precision,
                verified=verified,
                recommended=recommended,
            ),
            targets=_kpi_targets(primary_role, resolved_targets),
        )

    async def team_kpis(
        self, period: AnalyticsPeriod, *, calls_available: bool = True
    ) -> TeamKpisData:
        result = await self.db.execute(
            _TEAM_KPI_SQL,
            {"period_start": period.start, "period_end": period.end},
        )
        rows = result.mappings().all()
        target_result = await self.db.execute(_TEAM_TARGETS_SQL)
        target_candidates_by_user: dict[int, dict[str, tuple[int, int, int]]] = {}
        for target_row in target_result.mappings().all():
            candidates = target_candidates_by_user.setdefault(
                int(target_row["user_id"]), {}
            )
            _record_target(
                candidates,
                raw_id=str(target_row["kpi_id"]),
                target_value=int(target_row["target_value"]),
                priority=int(target_row["priority"]),
            )
        targets_by_user = {
            user_id: {
                target_id: candidate[2] for target_id, candidate in candidates.items()
            }
            for user_id, candidates in target_candidates_by_user.items()
        }
        return TeamKpisData(
            users=[
                TeamKpiRow(
                    user_id=int(row["user_id"]),
                    user_name=str(row["user_name"]),
                    primary_role=str(row["primary_role"]),
                    calls_completed=(
                        _integer(row, "calls_completed") if calls_available else None
                    ),
                    calls_available=calls_available,
                    verifications=_integer(row, "verifications"),
                    candidates_added=_integer(row, "candidates_added"),
                    recommendations=_integer(row, "recommendations"),
                    placements=_integer(row, "placements"),
                    targets=_kpi_targets(
                        str(row["primary_role"]),
                        targets_by_user.get(int(row["user_id"]), {}),
                    ),
                )
                for row in rows
            ]
        )

    async def team_calls(self, period: AnalyticsPeriod) -> TeamCallsData:
        result = await self.db.execute(
            _TEAM_CALLS_SQL,
            {"period_start": period.start, "period_end": period.end},
        )
        return TeamCallsData(
            users=[
                TeamCallRow(
                    user_id=int(row["user_id"]),
                    user_name=str(row["user_name"]),
                    completed=_integer(row, "completed"),
                    total_duration_seconds=_integer(row, "total_duration_seconds"),
                    average_duration_seconds=_optional_float(
                        row["average_duration_seconds"]
                    ),
                )
                for row in result.mappings().all()
            ]
        )

    @staticmethod
    def metric_definitions() -> MetricsMetaData:
        return MetricsMetaData(
            definitions=[
                MetricDefinition(
                    key="pipeline.current",
                    label="Aktualny pipeline",
                    definition="Najnowszy etap dla każdej pary kandydat i rekrutacja.",
                    source="candidate_stages",
                ),
                MetricDefinition(
                    key="recruitment.verified",
                    label="Weryfikacja",
                    definition="Pierwsze osiągnięcie etapu verified.",
                    source="candidate_stages",
                ),
                MetricDefinition(
                    key="recruitment.recommended",
                    label="Rekomendacja",
                    definition="Pierwsze osiągnięcie etapu cv_sent.",
                    source="candidate_stages",
                ),
                MetricDefinition(
                    key="recruitment.internal_interview",
                    label="Interview wewnętrzny",
                    definition="Pierwsze osiągnięcie etapu interview.",
                    source="candidate_stages",
                ),
                MetricDefinition(
                    key="recruitment.client_interview",
                    label="Interview klienta",
                    definition="Pierwsze osiągnięcie etapu client_interview.",
                    source="candidate_stages",
                ),
                MetricDefinition(
                    key="recruitment.placement",
                    label="Placement",
                    definition="Pierwsze osiągnięcie etapu hired.",
                    source="candidate_stages",
                ),
                MetricDefinition(
                    key="calls.completed",
                    label="Zakończone rozmowy",
                    definition=(
                        "Rozmowy o statusie completed przypisane przez "
                        "COALESCE(started_at, created_at)."
                    ),
                    source="calls",
                ),
                MetricDefinition(
                    key="sources.first_touch",
                    label="Źródło first-touch",
                    definition=(
                        "Pierwsze zarejestrowane źródło kandydata; konwersja jest "
                        "liczona dla kohorty pozyskanej w wybranym okresie."
                    ),
                    source="candidate_source_events,candidates",
                ),
                MetricDefinition(
                    key="finance.monthly_run_rate",
                    label="Miesięczny run-rate",
                    definition=(
                        "Miesięczny przychód i koszt kontraktów aktywnych "
                        "date-effective, przeliczone do PLN po kursie NBP z "
                        "dnia raportowego."
                    ),
                    source="contracts,fx_rates",
                ),
                MetricDefinition(
                    key="commercial.tender_outcome",
                    label="Wynik przetargu",
                    definition=(
                        "Wygrany wyłącznie gdy close_reason=filled_by_us; "
                        "zamknięty bez powodu pozostaje unknown."
                    ),
                    source="jobs",
                ),
            ]
        )
