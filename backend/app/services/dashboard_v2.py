"""Role-aware Dashboard v2 aggregators.

Business metrics are delegated to Analytics v1 and existing domain services.
This layer owns only composition, scope enforcement and truthful section
quality.  A source failure is isolated to its section and never becomes a
fabricated zero.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import Any, Awaitable, Callable

from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.periods import Period
from app.core.cache import cache_get, cache_set
from app.models.user import User
from app.schemas.dashboard_v2 import (
    AdminOpsBoardRow,
    AdminOpsDashboardData,
    AdminOpsDashboardResponse,
    AdminOpsKpis,
    CompetitionRankingEntry,
    DashboardAlert,
    DashboardDataQuality,
    DashboardKpi,
    DashboardQueueItem,
    DashboardSectionQuality,
    DeliveryLeadDashboardData,
    DeliveryLeadDashboardResponse,
    DeliveryLeadKpis,
    DeliveryRiskBoardRow,
    FinanceExceptionBoardRow,
    FinanceExecutiveDashboardData,
    FinanceExecutiveKpis,
    FinanceOperationsDashboardData,
    FinanceOperationsKpis,
    FinanceDashboardResponse,
    HeadOfRecruitmentDashboardData,
    HeadOfRecruitmentDashboardResponse,
    HeadOfRecruitmentKpis,
    MyWorkDashboardData,
    MyWorkDashboardResponse,
    MyWorkKpis,
    RecruitmentFunnelConversions,
    RecruitmentHallOfFame,
    RecruitmentHallOfFameHistoryEntry,
    RecruitmentHallOfFameHistoryPeriod,
    RecruitmentLinkedIn,
    RecruitmentLinkedInRow,
    RecruitmentLinkedInTotals,
    RecruitmentMonthlyRace,
    RecruitmentMonthlyRaces,
    RecruitmentQuarterlyLeague,
    RecruitmentStatsData,
    RecruitmentStatsDashboardResponse,
    RecruitmentStatsKpis,
    RecruitmentStatsPeriod,
    RecruitmentTeamBoardRow,
    RecruitmentTeamTable,
    RecruitmentTeamTableRow,
    RecruitmentTeamTableTotals,
    RecruitmentTrend,
    RecruitmentTrendMonth,
)
from app.services import dashboard_v2_sources as sources

logger = logging.getLogger(__name__)


@dataclass
class _Quality:
    sections: dict[str, DashboardSectionQuality] = field(default_factory=dict)

    def set(
        self,
        name: str,
        status: str,
        *,
        warnings: list[str] | None = None,
        watermarks: dict[str, datetime] | None = None,
    ) -> None:
        self.sections[name] = DashboardSectionQuality(
            status=status,
            warnings=warnings or [],
            source_watermarks=watermarks or {},
        )

    def build(self) -> DashboardDataQuality:
        statuses = [section.status for section in self.sections.values()]
        if not statuses or all(status == "unavailable" for status in statuses):
            overall = "unavailable"
        elif any(status in {"partial", "unavailable"} for status in statuses):
            overall = "partial"
        elif any(status == "stale" for status in statuses):
            overall = "stale"
        else:
            overall = "complete"
        warnings: list[str] = []
        watermarks: dict[str, datetime] = {}
        for section in self.sections.values():
            warnings.extend(
                warning for warning in section.warnings if warning not in warnings
            )
            watermarks.update(section.source_watermarks)
        return DashboardDataQuality(
            status=overall,
            warnings=warnings,
            source_watermarks=watermarks,
            sections=self.sections,
        )


async def _capture(
    quality: _Quality,
    name: str,
    loader: Callable[[], Awaitable[Any]],
) -> Any | None:
    try:
        value = await loader()
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 - section isolation is intentional
        logger.exception("dashboard_v2 source %s failed", name)
        quality.set(
            name,
            "unavailable",
            warnings=[f"{name}: {type(exc).__name__}"],
        )
        return None
    quality.set(name, "complete")
    return value


def _mark_partial(quality: _Quality, name: str, warning: str) -> None:
    """Downgrade a successful but structurally incomplete source."""

    existing = quality.sections.get(name)
    if existing is not None and existing.status == "unavailable":
        return
    warnings = list(existing.warnings) if existing is not None else []
    if warning not in warnings:
        warnings.append(warning)
    quality.set(
        name,
        "partial",
        warnings=warnings,
        watermarks=existing.source_watermarks if existing is not None else None,
    )


def _source_kpi_quality(
    quality: _Quality,
    name: str,
    value: Any,
) -> str:
    if value is None:
        return "unavailable"
    section = quality.sections.get(name)
    if section is None or section.status == "unavailable":
        return "unavailable"
    return section.status


def _mapping_with_list_fields(value: Any, *fields: str) -> bool:
    return isinstance(value, dict) and all(
        isinstance(value.get(field), list) for field in fields
    )


def _team_priority_shape_is_complete(value: Any) -> bool:
    if not _mapping_with_list_fields(value, "members"):
        return False
    if "unowned_carry_over_count" not in value or "overdue" not in value:
        return False
    return all(
        isinstance(member, dict)
        and isinstance(member.get("user_id"), int)
        and isinstance(member.get("assignments"), list)
        and "verification_capacity" in member
        and "carry_over_count" in member
        and "urgent_carry_over_count" in member
        for member in value["members"]
    )


def _my_priority_shape_is_complete(value: Any) -> bool:
    if not _mapping_with_list_fields(value, "assignments", "carry_over"):
        return False
    return all(
        isinstance(assignment, dict)
        and "verification_target" in assignment
        and "recommendation_target" in assignment
        and isinstance(assignment.get("progress"), dict)
        and "verifications" in assignment["progress"]
        and "recommendations" in assignment["progress"]
        for assignment in value["assignments"]
    )


def _personal_kpis_shape_is_complete(value: Any) -> bool:
    return isinstance(value, dict) and all(
        key in value
        for key in (
            "completed_calls",
            "first_verifications",
            "first_recommendations",
            "first_placements",
        )
    )


def _contact_queue_shape_is_complete(value: Any) -> bool:
    return (
        _mapping_with_list_fields(value, "items")
        and isinstance(value.get("utilization"), dict)
        and "used" in value["utilization"]
        and "capacity" in value["utilization"]
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, date):
        return datetime.combine(value, time.min, tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="python")
    return {}


def _kpi(
    value: str | int | float | None,
    unit: str,
    definition: str,
    *,
    quality: str = "complete",
    target: str | int | float | None = None,
    comparison: str | int | float | None = None,
    href: str | None = None,
) -> DashboardKpi:
    return DashboardKpi(
        value=value,
        unit=unit,
        quality=quality,
        target=target,
        comparison=comparison,
        definition=definition,
        drilldown_href=href,
    )


def _unavailable_kpi(unit: str, definition: str) -> DashboardKpi:
    return _kpi(None, unit, definition, quality="unavailable")


def _queue_from_alerts(alerts: list[DashboardAlert]) -> list[DashboardQueueItem]:
    severity_priority = {"critical": 100, "warning": 70, "info": 30}
    return [
        DashboardQueueItem(
            id=f"alert:{alert.id}",
            kind=alert.kind,
            priority=severity_priority[alert.severity],
            title=alert.title,
            subtitle=alert.description,
            source=alert.source,
            due_at=alert.due_at,
            entity_type=alert.entity_type,
            entity_id=alert.entity_id,
            href=alert.href,
            action_label="Otwórz" if alert.href else None,
        )
        for alert in alerts[:7]
    ]


# ── Admin Ops ────────────────────────────────────────────────────────────────


async def build_admin_ops_dashboard(
    request: Request,
    user: User,
    db: AsyncSession,
) -> AdminOpsDashboardResponse:
    scope = await sources.resolve_scope(user, db)
    sources.require_scope(scope, "organization")
    quality = _Quality()

    snapshot = await _capture(
        quality, "admin_snapshot", lambda: sources.load_admin_snapshot(request, db)
    )
    schema = await _capture(
        quality, "schema_drift", lambda: sources.load_admin_schema_drift(db)
    )
    coverage = await _capture(
        quality, "index_coverage", lambda: sources.load_admin_index_coverage(db)
    )
    priority_status = await _capture(
        quality, "priority_work", lambda: sources.load_priority_status(user, db)
    )
    priority_alerts = await _capture(
        quality, "priority_alerts", lambda: sources.load_priority_alerts(user, db)
    )
    traffit = await _capture(
        quality, "traffit", lambda: sources.load_traffit_status(user, db)
    )

    snapshot_payload = _mapping(snapshot)
    health = snapshot_payload.get("health")
    checks_value = health.get("checks") if isinstance(health, dict) else None
    checks = checks_value if isinstance(checks_value, dict) else {}
    if snapshot is not None and not checks:
        _mark_partial(
            quality,
            "admin_snapshot",
            "admin_snapshot.health.checks is missing or empty.",
        )
    healthy = sum(1 for value in checks.values() if value == "healthy")
    readiness = f"{healthy}/{len(checks)}" if checks else None

    schema_payload = _mapping(schema)
    schema_summary_value = schema_payload.get("summary")
    schema_summary = (
        schema_summary_value if isinstance(schema_summary_value, dict) else {}
    )
    required_schema_keys = {
        "missing_tables",
        "missing_columns_high",
        "missing_enum_types",
        "missing_enum_values",
    }
    schema_shape_complete = required_schema_keys <= set(schema_summary) and all(
        isinstance(schema_summary[key], (int, float)) for key in required_schema_keys
    )
    if schema is not None and not schema_shape_complete:
        _mark_partial(
            quality,
            "schema_drift",
            "schema_drift.summary is missing required counters.",
        )
    schema_critical = (
        sum(int(schema_summary[key]) for key in required_schema_keys)
        if schema_shape_complete
        else None
    )

    workers_value_raw = snapshot_payload.get("background_tasks")
    workers = workers_value_raw if isinstance(workers_value_raw, dict) else {}
    workers_shape_complete = (
        {"running", "expected"} <= set(workers)
        and isinstance(workers.get("running"), (int, float))
        and isinstance(workers.get("expected"), (int, float))
        and int(workers["expected"]) > 0
    )
    if snapshot is not None and not workers_shape_complete:
        _mark_partial(
            quality,
            "admin_snapshot",
            "admin_snapshot.background_tasks is missing a positive expected count.",
        )
    workers_value = (
        f"{int(workers.get('running', 0))}/{int(workers.get('expected', 0))}"
        if workers_shape_complete
        else None
    )
    coverage_payload = _mapping(coverage)
    outbox_value = coverage_payload.get("outbox")
    outbox = outbox_value if isinstance(outbox_value, dict) else {}
    outbox_shape_complete = {"failed", "dead"} <= set(outbox) and all(
        isinstance(outbox[key], (int, float)) for key in ("failed", "dead")
    )
    if coverage is not None and not outbox_shape_complete:
        _mark_partial(
            quality,
            "index_coverage",
            "index_coverage.outbox is missing failed/dead counters.",
        )
    failed_dead = (
        int(outbox["failed"]) + int(outbox["dead"]) if outbox_shape_complete else None
    )
    traffit_payload = _mapping(traffit)
    states_value = traffit_payload.get("states")
    states = (
        [state for state in states_value if isinstance(state, dict)]
        if isinstance(states_value, list)
        else []
    )
    if traffit is not None and (
        not states
        or not isinstance(states_value, list)
        or len(states) != len(states_value)
    ):
        _mark_partial(
            quality,
            "traffit",
            "traffit.states is missing or empty.",
        )
    healthy_states = sum(
        1 for state in states if state.get("last_status") in {"ok", "success"}
    )
    integrations_value = f"{healthy_states}/{len(states)}" if states else None
    coverage_values = [
        row.get("coverage_pct")
        for row in (coverage_payload.get("candidates"), coverage_payload.get("jobs"))
        if isinstance(row, dict) and isinstance(row.get("coverage_pct"), (int, float))
    ]
    if coverage is not None and len(coverage_values) != 2:
        _mark_partial(
            quality,
            "index_coverage",
            "index_coverage is missing candidate or job coverage.",
        )
    lowest_coverage = min(coverage_values) if coverage_values else None

    alerts: list[DashboardAlert] = []
    for check_name, state in checks.items():
        if state != "healthy":
            alerts.append(
                DashboardAlert(
                    id=f"health:{check_name}",
                    kind="dependency_health",
                    severity="critical" if state == "unhealthy" else "warning",
                    title=f"Zależność {check_name}: {state}",
                    source="admin_snapshot",
                    href="/settings/admin/system",
                )
            )
    if schema_critical:
        alerts.append(
            DashboardAlert(
                id="schema:critical",
                kind="schema_drift",
                severity="critical",
                title=f"Krytyczny drift schematu: {schema_critical}",
                source="schema_drift",
                href="/settings/admin/system",
            )
        )
    if failed_dead:
        alerts.append(
            DashboardAlert(
                id="outbox:failed-dead",
                kind="outbox_backlog",
                severity="critical" if int(outbox.get("dead", 0)) else "warning",
                title=f"Failed/dead events: {failed_dead}",
                source="index_coverage",
                href="/settings/admin/system",
            )
        )
    if priority_status and priority_status.get("last_error"):
        alerts.append(
            DashboardAlert(
                id="priority:last-error",
                kind="priority_work",
                severity="critical",
                title="Priority Work zgłasza błąd",
                description=str(priority_status["last_error"]),
                source="priority_work",
                href="/dashboard?context=recruitment-lead",
            )
        )
    for row in priority_alerts or []:
        alerts.append(
            DashboardAlert(
                id=f"priority-alert:{row.get('id')}",
                kind=str(row.get("kind") or "priority_work"),
                severity=(
                    row.get("severity")
                    if row.get("severity") in {"info", "warning", "critical"}
                    else "warning"
                ),
                title=str(row.get("kind") or "Priority Work alert"),
                source="priority_work",
                occurred_at=_as_datetime(row.get("last_seen_at")),
                entity_type="job" if row.get("job_id") else None,
                entity_id=row.get("job_id"),
                href=(f"/jobs/{row['job_id']}" if row.get("job_id") else None),
            )
        )
    alerts.sort(
        key=lambda alert: {"critical": 0, "warning": 1, "info": 2}[alert.severity]
    )
    board = [
        AdminOpsBoardRow(
            id=alert.id,
            severity=alert.severity,
            domain=alert.source,
            signal=alert.title,
            last_success_at=None,
            next_action_href=alert.href,
        )
        for alert in alerts
    ]

    data = AdminOpsDashboardData(
        kpis=AdminOpsKpis(
            critical_readiness=_kpi(
                readiness,
                "fraction",
                "Zdrowe krytyczne checki / wszystkie krytyczne checki.",
                quality=_source_kpi_quality(quality, "admin_snapshot", readiness),
            ),
            critical_schema_drift=_kpi(
                schema_critical,
                "count",
                "Brakujące tabele, kolumny high-severity i elementy enum.",
                quality=_source_kpi_quality(quality, "schema_drift", schema_critical),
            ),
            background_workers=_kpi(
                workers_value,
                "fraction",
                "Uruchomione zadania tła / oczekiwane zadania tła.",
                quality=_source_kpi_quality(quality, "admin_snapshot", workers_value),
            ),
            failed_dead_events=_kpi(
                failed_dead,
                "count",
                "Bieżące wpisy failed + dead w monitorowanym outboxie.",
                quality=_source_kpi_quality(quality, "index_coverage", failed_dead),
            ),
            integrations_in_sla=_kpi(
                integrations_value,
                "fraction",
                "Integracje z ostatnim poprawnym statusem / monitorowane integracje.",
                quality=_source_kpi_quality(quality, "traffit", integrations_value),
            ),
            lowest_critical_coverage=_kpi(
                lowest_coverage,
                "percent",
                "Najniższe pokrycie spośród krytycznych indeksów danych.",
                quality=_source_kpi_quality(quality, "index_coverage", lowest_coverage),
            ),
        ),
        alerts=alerts,
        queue=_queue_from_alerts(alerts),
        operations_board=board,
    )
    return AdminOpsDashboardResponse(
        generated_at=_now(),
        scope=scope.payload,
        data_quality=quality.build(),
        data=data,
    )


# ── Delivery Lead ────────────────────────────────────────────────────────────


async def build_delivery_lead_dashboard(
    user: User,
    db: AsyncSession,
    period: Period,
) -> DeliveryLeadDashboardResponse:
    scope = await sources.resolve_scope(user, db)
    sources.require_scope(scope, "delivery_clients", "organization")
    quality = _Quality()

    metrics_snapshot = await _capture(
        quality,
        "delivery_metrics",
        lambda: sources.load_delivery_metrics(user, db, period, scope),
    )
    allowed_job_ids = (
        {row.job_id for row in metrics_snapshot.jobs} if metrics_snapshot else set()
    )
    demands = None
    if scope.payload.kind == "delivery_clients":
        demands = await _capture(
            quality,
            "priority_demands",
            lambda: sources.load_delivery_demands(user, db, allowed_job_ids),
        )
    else:
        quality.set(
            "priority_demands",
            "unavailable",
            warnings=["Admin organization scope has no single DL demand owner."],
        )

    quality.set(
        "delivery_sla",
        "unavailable",
        warnings=[
            "Kanoniczny scoped SLA/TTFR resolver nie jest jeszcze dostępny; "
            "wartości nie są zgadywane."
        ],
    )

    jobs = metrics_snapshot.jobs if metrics_snapshot else []
    open_requests = len(jobs) if metrics_snapshot is not None else None
    open_vacancies = (
        sum(job.open_vacancies for job in jobs)
        if metrics_snapshot is not None
        else None
    )
    placements = metrics_snapshot.placements if metrics_snapshot is not None else None

    now = _now()
    risk_board: list[DeliveryRiskBoardRow] = []
    alerts: list[DashboardAlert] = []
    for job in jobs:
        created_at = (
            job.created_at
            if job.created_at.tzinfo
            else job.created_at.replace(tzinfo=timezone.utc)
        )
        age_days = max(0, (now - created_at).days)
        missing_recommendation = job.first_recommendation_at is None
        if missing_recommendation and (age_days >= 7 or job.priority == "urgent"):
            risk = "critical"
        elif missing_recommendation and (age_days >= 3 or job.priority == "high"):
            risk = "warning"
        else:
            risk = "info"
        risk_board.append(
            DeliveryRiskBoardRow(
                client_id=job.client_id,
                client_name=job.client_name,
                job_id=job.job_id,
                job_title=job.job_title,
                priority=job.priority,
                open_vacancies=job.open_vacancies,
                tac_user_id=job.tac_user_id,
                age_days=age_days,
                first_recommendation_at=job.first_recommendation_at,
                risk=risk,
                next_action_href=f"/jobs/{job.job_id}",
            )
        )
        if risk != "info":
            alerts.append(
                DashboardAlert(
                    id=f"job-risk:{job.job_id}",
                    kind="job_without_recommendation",
                    severity=risk,
                    title=f"{job.job_title}: brak pierwszej rekomendacji",
                    description=f"{job.client_name} · {age_days} dni",
                    source="delivery_metrics",
                    entity_type="job",
                    entity_id=job.job_id,
                    href=f"/jobs/{job.job_id}",
                )
            )

    queue: list[DashboardQueueItem] = []
    for demand in demands or []:
        job = demand.get("job") or {}
        due = _as_datetime(demand.get("deadline"))
        queue.append(
            DashboardQueueItem(
                id=f"priority-demand:{demand.get('id')}",
                kind="priority_demand",
                priority=90 if demand.get("urgency") == "critical" else 70,
                title=str(job.get("title") or "Priority request"),
                subtitle=str(demand.get("note") or "") or None,
                source="priority_work",
                due_at=due,
                entity_type="job",
                entity_id=job.get("id"),
                href=f"/jobs/{job['id']}" if job.get("id") else None,
                action_label="Otwórz request",
                version=demand.get("row_version"),
            )
        )
    queue.extend(_queue_from_alerts(alerts))
    queue.sort(
        key=lambda item: (
            -item.priority,
            item.due_at or datetime.max.replace(tzinfo=timezone.utc),
        )
    )

    data = DeliveryLeadDashboardData(
        kpis=DeliveryLeadKpis(
            open_requests=_kpi(
                open_requests,
                "count",
                "Opublikowane joby w przecięciu przypisanych klientów i TAC.",
                quality="complete" if metrics_snapshot is not None else "unavailable",
            ),
            open_vacancies=_kpi(
                open_vacancies,
                "count",
                "Suma headcount opublikowanych jobów w scoped portfolio.",
                quality="complete" if metrics_snapshot is not None else "unavailable",
            ),
            first_recommendation_sla_pct=_unavailable_kpi(
                "percent", "Joby z pierwszą rekomendacją w uzgodnionym SLA."
            ),
            median_time_to_first_recommendation_hours=_unavailable_kpi(
                "hours", "Mediana od utworzenia joba do pierwszego cv_sent."
            ),
            fill_rate_pct=_unavailable_kpi(
                "percent", "Pierwsze placementy / historyczne vacancies w okresie."
            ),
            placements=_kpi(
                placements,
                "count",
                "Pierwsze hired w okresie, ograniczone client + TAC + actor scope.",
                quality="complete" if metrics_snapshot is not None else "unavailable",
            ),
        ),
        alerts=alerts,
        queue=queue[:20],
        risk_board=risk_board,
    )
    return DeliveryLeadDashboardResponse(
        generated_at=_now(),
        scope=scope.payload,
        data_quality=quality.build(),
        data=data,
    )


# ── Head of Recruitment ──────────────────────────────────────────────────────


async def build_head_of_recruitment_dashboard(
    user: User,
    db: AsyncSession,
    period: Period,
) -> HeadOfRecruitmentDashboardResponse:
    scope = await sources.resolve_scope(user, db)
    sources.require_scope(scope, "recruitment_org", "organization")
    quality = _Quality()

    team = await _capture(
        quality, "priority_team", lambda: sources.load_team_priority_work(user, db)
    )
    contact = await _capture(
        quality, "contact_oversight", lambda: sources.load_contact_oversight(user, db)
    )
    if contact is not None and not (
        isinstance(contact, dict) and isinstance(contact.get("counters"), dict)
    ):
        _mark_partial(
            quality,
            "contact_oversight",
            "contact_oversight: odpowiedź nie zawiera counters",
        )
        contact = None
    team_shape_complete = _team_priority_shape_is_complete(team)
    if team is not None and not team_shape_complete:
        _mark_partial(
            quality,
            "priority_team",
            "priority_team: odpowiedź nie zawiera pełnego kontraktu rosteru",
        )
    members = team["members"] if team_shape_complete else []
    if scope.payload.kind == "recruitment_org":
        allowed = set(scope.payload.operator_user_ids)
        members = [row for row in members if int(row.get("user_id", -1)) in allowed]

    async def _team_kpis() -> list[dict[str, Any]]:
        return [
            await sources.load_user_kpis(int(member["user_id"]), db, period)
            for member in members
        ]

    if not team_shape_complete:
        team_kpis = None
        quality.set(
            "team_kpis",
            "unavailable",
            warnings=[
                "team_kpis: brak bezpiecznego rosteru operatorów z priority_team"
            ],
        )
    else:
        # An empty but successfully loaded roster is a truthful zero. A failed
        # roster source must never be converted to `sum([]) == 0`.
        team_kpis = await _capture(quality, "team_kpis", _team_kpis)
        if team_kpis is not None and not (
            isinstance(team_kpis, list)
            and all(_personal_kpis_shape_is_complete(row) for row in team_kpis)
        ):
            _mark_partial(
                quality,
                "team_kpis",
                "team_kpis: co najmniej jeden operator nie ma pełnego zestawu KPI",
            )
            team_kpis = None
    quality.set(
        "recruitment_sla",
        "unavailable",
        warnings=[
            "Scoped first-recommendation SLA and interview conversion are not "
            "yet exposed by the canonical analytics service."
        ],
    )

    total_capacity = sum(int(row.get("verification_capacity") or 0) for row in members)
    total_target = sum(
        int(assignment.get("verification_target") or 0)
        for row in members
        for assignment in row.get("assignments") or []
    )
    capacity_pct = (
        round(100 * total_target / total_capacity, 1) if total_capacity else None
    )
    placements = (
        sum(int(row.get("first_placements") or 0) for row in team_kpis)
        if team_kpis is not None
        else None
    )
    unassigned = (
        int(team.get("unowned_carry_over_count") or 0) if team_shape_complete else None
    )

    alerts: list[DashboardAlert] = []
    if team_shape_complete and team.get("overdue"):
        alerts.append(
            DashboardAlert(
                id="priority-plan:overdue",
                kind="priority_plan",
                severity="critical",
                title="Plan priorytetów wymaga przeglądu",
                source="priority_work",
                href="/dashboard?context=recruitment-lead",
            )
        )
    if unassigned:
        alerts.append(
            DashboardAlert(
                id="priority:unassigned",
                kind="unassigned_work",
                severity="critical",
                title=f"Nieprzypisane carry-over: {unassigned}",
                source="priority_work",
                href="/dashboard?context=recruitment-lead",
            )
        )

    team_board: list[RecruitmentTeamBoardRow] = []
    priority_vacancies = 0
    for member in members:
        assignments = member.get("assignments") or []
        target = sum(int(item.get("verification_target") or 0) for item in assignments)
        blockers = sum(
            1
            for item in assignments
            if item.get("blocker")
            or any(
                blocker.get("status") in {"pending", "accepted"}
                for blocker in item.get("blockers") or []
            )
        )
        # A recommendation target is the closest canonical demand quantity
        # already exposed by Priority Work; job headcount stays a separate metric.
        priority_vacancies += sum(
            int(item.get("recommendation_target") or 0) for item in assignments
        )
        capacity = int(member.get("verification_capacity") or 0)
        if capacity and target > capacity:
            alerts.append(
                DashboardAlert(
                    id=f"capacity:{member.get('user_id')}",
                    kind="capacity_overload",
                    severity="warning",
                    title=f"{member.get('user_name')}: target powyżej capacity",
                    source="priority_work",
                    entity_type="user",
                    entity_id=member.get("user_id"),
                    href="/dashboard?context=recruitment-lead",
                )
            )
        team_board.append(
            RecruitmentTeamBoardRow(
                user_id=int(member["user_id"]),
                user_name=str(member.get("user_name") or ""),
                roles=list(member.get("roles") or [member.get("role")]),
                status=str(member.get("status") or "active"),
                verification_capacity=capacity,
                verification_target=target,
                assignment_count=len(assignments),
                carry_over_count=int(member.get("carry_over_count") or 0),
                urgent_carry_over_count=int(member.get("urgent_carry_over_count") or 0),
                blocker_count=blockers,
            )
        )

    counters = (contact or {}).get("counters") or {}
    for key, label in (
        ("overdue", "Zaległe kontakty"),
        ("unassigned", "Nieprzypisane kontakty"),
        ("awaiting_capacity", "Kontakty oczekujące na capacity"),
        ("blocked_no_phone", "Kontakty bez telefonu"),
    ):
        value = int(counters.get(key) or 0)
        if value:
            alerts.append(
                DashboardAlert(
                    id=f"contact:{key}",
                    kind="contact_oversight",
                    severity="critical"
                    if key in {"overdue", "unassigned"}
                    else "warning",
                    title=f"{label}: {value}",
                    source="candidate_contact",
                    href="/candidates/contact-queue",
                )
            )
    alerts.sort(
        key=lambda alert: {"critical": 0, "warning": 1, "info": 2}[alert.severity]
    )

    data = HeadOfRecruitmentDashboardData(
        kpis=HeadOfRecruitmentKpis(
            priority_vacancies=_kpi(
                priority_vacancies if team_shape_complete else None,
                "count",
                "Suma recommendation targets w aktualnym planie priorytetów.",
                quality=(
                    quality.sections["priority_team"].status
                    if team_shape_complete
                    else "unavailable"
                ),
            ),
            unassigned_work=_kpi(
                unassigned,
                "count",
                "Carry-over wymagające przypisania ownera.",
                quality=(
                    quality.sections["priority_team"].status
                    if team_shape_complete
                    else "unavailable"
                ),
            ),
            capacity_utilization_pct=_kpi(
                capacity_pct,
                "percent",
                "Suma verification targets / suma verification capacity.",
                quality="complete"
                if team_shape_complete and capacity_pct is not None
                else "unavailable",
            ),
            first_recommendation_sla_pct=_unavailable_kpi(
                "percent", "Procent jobów z pierwszą rekomendacją w SLA."
            ),
            recommendation_to_interview_pct=_unavailable_kpi(
                "percent", "Pierwsze interview / pierwsze rekomendacje w okresie."
            ),
            placements=_kpi(
                placements,
                "count",
                "Suma kanonicznych first_placements dla scoped operatorów.",
                quality=(
                    quality.sections["team_kpis"].status
                    if team_kpis is not None
                    else "unavailable"
                ),
            ),
        ),
        alerts=alerts,
        queue=_queue_from_alerts(alerts),
        team_board=team_board,
    )
    return HeadOfRecruitmentDashboardResponse(
        generated_at=_now(),
        scope=scope.payload,
        data_quality=quality.build(),
        data=data,
    )


# ── My Work ──────────────────────────────────────────────────────────────────


async def build_my_work_dashboard(
    user: User,
    db: AsyncSession,
    period: Period,
) -> MyWorkDashboardResponse:
    scope = sources.narrow_to_self(
        user,
        await sources.resolve_scope(user, db),
    )
    quality = _Quality()

    priority = await _capture(
        quality, "priority_work", lambda: sources.load_my_priority_work(user, db)
    )
    priority_shape_complete = _my_priority_shape_is_complete(priority)
    if priority is not None and not priority_shape_complete:
        _mark_partial(
            quality,
            "priority_work",
            "priority_work: odpowiedź nie zawiera assignments i carry_over",
        )
    user_kpis = await _capture(
        quality, "personal_kpis", lambda: sources.load_user_kpis(user.id, db, period)
    )
    personal_kpis_shape_complete = _personal_kpis_shape_is_complete(user_kpis)
    if user_kpis is not None and not personal_kpis_shape_complete:
        _mark_partial(
            quality,
            "personal_kpis",
            "personal_kpis: odpowiedź nie zawiera wszystkich kanonicznych KPI",
        )
    calls_available = sources.cloudtalk_calls_available()
    if not calls_available:
        quality.set(
            "completed_calls",
            "unavailable",
            warnings=[
                "CloudTalk jest wyłączony; liczba rozmów jest niedostępna, "
                "a nie zerowa."
            ],
        )
    contact_status = await _capture(
        quality, "contact_status", lambda: sources.load_contact_feature_status(user)
    )
    contact_status_shape_complete = isinstance(contact_status, dict) and isinstance(
        contact_status.get("enabled"), bool
    )
    if contact_status is not None and not contact_status_shape_complete:
        _mark_partial(
            quality,
            "contact_status",
            "contact_status: odpowiedź nie zawiera flagi enabled",
        )
    contact_queue = None
    if contact_status_shape_complete and contact_status["enabled"]:
        contact_queue = await _capture(
            quality, "contact_queue", lambda: sources.load_my_contact_queue(user, db)
        )
        if contact_queue is not None and not _contact_queue_shape_is_complete(
            contact_queue
        ):
            _mark_partial(
                quality,
                "contact_queue",
                "contact_queue: odpowiedź nie zawiera items i utilization",
            )
            contact_queue = None
    else:
        quality.set(
            "contact_queue",
            "unavailable",
            warnings=[
                (
                    "Candidate Contact jest wyłączony dla tego środowiska."
                    if contact_status_shape_complete
                    else "Nie można wiarygodnie ustalić statusu Candidate Contact."
                )
            ],
        )

    queue: list[DashboardQueueItem] = []
    assignments = priority["assignments"] if priority_shape_complete else []
    carry_over = priority["carry_over"] if priority_shape_complete else []
    target_total = 0
    progress_total = 0
    alerts: list[DashboardAlert] = []
    for assignment in assignments:
        target = int(assignment.get("verification_target") or 0) + int(
            assignment.get("recommendation_target") or 0
        )
        progress = assignment.get("progress") or {}
        achieved = min(
            int(progress.get("verifications") or 0),
            int(assignment.get("verification_target") or 0),
        ) + min(
            int(progress.get("recommendations") or 0),
            int(assignment.get("recommendation_target") or 0),
        )
        target_total += target
        progress_total += achieved
        job = assignment.get("job") or {}
        queue.append(
            DashboardQueueItem(
                id=f"priority-assignment:{assignment.get('id')}",
                kind="priority_assignment",
                priority=max(
                    50, 100 - (ord(str(assignment.get("rank") or "E")[0]) - 65) * 10
                ),
                title=str(job.get("title") or "Priority request"),
                subtitle=f"Priorytet {assignment.get('rank')}",
                source="priority_work",
                entity_type="job",
                entity_id=job.get("id"),
                href=f"/jobs/{job['id']}" if job.get("id") else None,
                action_label="Obsłuż proces",
            )
        )
        blocker = assignment.get("blocker")
        if blocker:
            alerts.append(
                DashboardAlert(
                    id=f"blocker:{blocker.get('id')}",
                    kind="priority_blocker",
                    severity="warning",
                    title=f"Blocker: {job.get('title') or 'request'}",
                    description=blocker.get("note"),
                    source="priority_work",
                    entity_type="job",
                    entity_id=job.get("id"),
                    href=f"/jobs/{job['id']}" if job.get("id") else None,
                )
            )
    for item in carry_over:
        candidate = item.get("candidate") or {}
        job = item.get("job") or {}
        queue.append(
            DashboardQueueItem(
                id=f"carry-over:{item.get('process_id')}",
                kind="carry_over",
                priority=95 if item.get("urgency") in {"critical", "urgent"} else 80,
                title=str(candidate.get("name") or "Kandydat"),
                subtitle=f"{job.get('title') or 'Request'} · {item.get('days_in_stage', 0)} dni",
                source="priority_work",
                entity_type="process",
                entity_id=item.get("process_id"),
                href=f"/jobs/{job['id']}" if job.get("id") else None,
                action_label="Dokończ proces",
                version=item.get("state_version"),
            )
        )
    for item in (contact_queue or {}).get("items") or []:
        due = _as_datetime(item.get("callback_at") or item.get("due_at"))
        candidate = item.get("candidate") or {}
        full_name = (
            " ".join(
                part
                for part in (candidate.get("name"), candidate.get("lastname"))
                if part
            ).strip()
            or "Kandydat"
        )
        queue.append(
            DashboardQueueItem(
                id=f"contact:{item.get('id')}",
                kind="candidate_contact",
                priority=100 if due and due < _now() else 85,
                title=full_name,
                subtitle=str(item.get("status") or ""),
                source="candidate_contact",
                due_at=due,
                entity_type="candidate",
                entity_id=candidate.get("id"),
                href="/candidates/contact-queue",
                action_label="Zapisz wynik kontaktu",
                version=item.get("version"),
            )
        )
    queue.sort(
        key=lambda item: (
            -item.priority,
            item.due_at or datetime.max.replace(tzinfo=timezone.utc),
        )
    )
    overdue_count = sum(1 for item in queue if item.due_at and item.due_at < _now())
    overdue_sources = (priority_shape_complete, contact_queue is not None)
    overdue = overdue_count if any(overdue_sources) else None
    overdue_quality = (
        "complete"
        if all(overdue_sources)
        else ("partial" if any(overdue_sources) else "unavailable")
    )
    completion = round(100 * progress_total / target_total, 1) if target_total else None
    utilization = (contact_queue or {}).get("utilization") or {}
    if utilization and int(utilization.get("used") or 0) >= int(
        utilization.get("capacity") or 20
    ):
        alerts.append(
            DashboardAlert(
                id="contact:capacity",
                kind="contact_capacity",
                severity="warning",
                title="Kolejka kontaktu osiągnęła limit",
                source="candidate_contact",
                href="/candidates/contact-queue",
            )
        )

    data = MyWorkDashboardData(
        kpis=MyWorkKpis(
            plan_completion_pct=_kpi(
                completion,
                "percent",
                "Ograniczony targetem postęp weryfikacji i rekomendacji.",
                quality=(
                    "complete"
                    if priority_shape_complete and target_total
                    else "unavailable"
                ),
            ),
            overdue_actions=_kpi(
                overdue,
                "count",
                "Elementy własnej kolejki z due_at wcześniejszym niż teraz.",
                quality=overdue_quality,
            ),
            completed_calls=_kpi(
                (
                    user_kpis["completed_calls"]
                    if personal_kpis_shape_complete and calls_available
                    else None
                ),
                "count",
                "Call.status=completed w wybranym okresie.",
                quality=(
                    "complete"
                    if personal_kpis_shape_complete and calls_available
                    else "unavailable"
                ),
            ),
            first_verifications=_kpi(
                (
                    user_kpis["first_verifications"]
                    if personal_kpis_shape_complete
                    else None
                ),
                "count",
                "Pierwsze verified przypisane użytkownikowi.",
                quality=(
                    quality.sections["personal_kpis"].status
                    if personal_kpis_shape_complete
                    else "unavailable"
                ),
            ),
            first_recommendations=_kpi(
                (
                    user_kpis["first_recommendations"]
                    if personal_kpis_shape_complete
                    else None
                ),
                "count",
                "Pierwsze cv_sent przypisane użytkownikowi.",
                quality=(
                    quality.sections["personal_kpis"].status
                    if personal_kpis_shape_complete
                    else "unavailable"
                ),
            ),
            placements=_kpi(
                (
                    user_kpis["first_placements"]
                    if personal_kpis_shape_complete
                    else None
                ),
                "count",
                "Pierwsze hired przypisane użytkownikowi.",
                quality=(
                    quality.sections["personal_kpis"].status
                    if personal_kpis_shape_complete
                    else "unavailable"
                ),
            ),
        ),
        alerts=alerts,
        queue=queue[:30],
    )
    return MyWorkDashboardResponse(
        generated_at=_now(),
        scope=scope.payload,
        data_quality=quality.build(),
        data=data,
    )


# ── Finance ──────────────────────────────────────────────────────────────────


def _finance_flag_status(flag: str, warnings: list[str]) -> str:
    if flag == "unavailable":
        return "unavailable"
    if flag == "partial" or warnings:
        return "partial"
    return "complete"


async def build_finance_dashboard(
    user: User,
    db: AsyncSession,
    period: Period,
    *,
    tab: str,
) -> FinanceDashboardResponse:
    scope = await sources.resolve_scope(user, db)
    sources.require_scope(scope, "organization")
    quality = _Quality()
    as_of = sources.finance_as_of(period)

    summary_result = await _capture(
        quality,
        "finance_summary",
        lambda: sources.load_finance_summary(db, as_of=as_of),
    )
    summary: dict[str, Any] | None = None
    if summary_result is not None:
        summary, warnings, flag = summary_result
        quality.set(
            "finance_summary",
            _finance_flag_status(flag, warnings),
            warnings=warnings,
        )

    forecast = await _capture(
        quality, "revenue_forecast", lambda: sources.load_revenue_forecast(user, db)
    )
    forecast_value: str | None = None
    if forecast is not None:
        if forecast.fx_missing:
            quality.set(
                "revenue_forecast",
                "unavailable",
                warnings=list(forecast.fx_warnings),
            )
        else:
            forecast_value = str(
                sum((Decimal(month.revenue) for month in forecast.months), Decimal("0"))
            )

    alerts: list[DashboardAlert] = []
    queue: list[DashboardQueueItem] = []
    exceptions: list[FinanceExceptionBoardRow] = []

    if tab == "operations":
        dso = await _capture(
            quality, "invoice_dso", lambda: sources.load_finance_dso(user, db)
        )
        overdue_invoices = await _capture(
            quality,
            "overdue_invoices",
            lambda: sources.load_overdue_invoices(user, db),
        )
        dso_incomplete = bool(dso and any(bool(row.fx_incomplete) for row in dso))
        outstanding = None
        if dso is not None and not dso_incomplete:
            outstanding = str(
                sum((Decimal(row.outstanding) for row in dso), Decimal("0"))
            )
        elif dso_incomplete:
            quality.set(
                "invoice_dso",
                "unavailable",
                warnings=[
                    "Brak FX dla części faktur; outstanding PLN nie jest sumowany."
                ],
            )

        overdue_value: str | None = None
        if overdue_invoices is not None:
            currencies = {
                (invoice.currency or "PLN").upper() for invoice in overdue_invoices
            }
            if currencies <= {"PLN"}:
                overdue_value = str(
                    sum(
                        (Decimal(invoice.amount) for invoice in overdue_invoices),
                        Decimal("0"),
                    )
                )
            else:
                quality.set(
                    "overdue_invoices",
                    "unavailable",
                    warnings=[
                        "Overdue obejmuje wiele walut; endpoint źródłowy nie "
                        "udostępnia bezpiecznej sumy PLN."
                    ],
                )
        for invoice in overdue_invoices or []:
            due = _as_datetime(invoice.due_date)
            alert = DashboardAlert(
                id=f"invoice:{invoice.id}",
                kind="overdue_invoice",
                severity="critical",
                title=f"Faktura {invoice.invoice_number} po terminie",
                source="invoices",
                due_at=due,
                entity_type="invoice",
                entity_id=invoice.id,
                href=f"/invoices/{invoice.id}",
            )
            alerts.append(alert)
            queue.append(
                DashboardQueueItem(
                    id=f"invoice:{invoice.id}",
                    kind="overdue_invoice",
                    priority=100,
                    title=f"Faktura {invoice.invoice_number}",
                    subtitle=f"{invoice.amount} {invoice.currency}",
                    source="invoices",
                    due_at=due,
                    entity_type="invoice",
                    entity_id=invoice.id,
                    href=f"/invoices/{invoice.id}",
                    action_label="Otwórz fakturę",
                )
            )
            exceptions.append(
                FinanceExceptionBoardRow(
                    id=f"invoice:{invoice.id}",
                    severity="critical",
                    kind="overdue_invoice",
                    contract_id=invoice.contract_id,
                    invoice_id=invoice.id,
                    invoice_number=invoice.invoice_number,
                    amount=str(invoice.amount),
                    currency=invoice.currency,
                    due_at=due,
                    next_action_href=f"/invoices/{invoice.id}",
                )
            )

        summary_values = summary or {}
        data: Any = FinanceOperationsDashboardData(
            kpis=FinanceOperationsKpis(
                mrr_pln=_kpi(
                    summary_values.get("mrr"),
                    "PLN",
                    "MRR aktywnych date-effective kontraktów na as_of.",
                    quality=_source_kpi_quality(
                        quality,
                        "finance_summary",
                        summary_values.get("mrr"),
                    ),
                ),
                monthly_margin_pln=_kpi(
                    summary_values.get("monthly_margin"),
                    "PLN",
                    "Miesięczna marża aktywnych kontraktów na as_of.",
                    quality=_source_kpi_quality(
                        quality,
                        "finance_summary",
                        summary_values.get("monthly_margin"),
                    ),
                ),
                margin_pct=_kpi(
                    summary_values.get("margin_pct"),
                    "percent",
                    "Miesięczna marża / MRR.",
                    quality=_source_kpi_quality(
                        quality,
                        "finance_summary",
                        summary_values.get("margin_pct"),
                    ),
                ),
                outstanding_pln=_kpi(
                    outstanding,
                    "PLN",
                    "Należności client-facing po konwersji FX.",
                    quality="complete" if outstanding is not None else "unavailable",
                ),
                overdue_pln=_kpi(
                    overdue_value,
                    "PLN",
                    "Faktury client-facing po terminie; tylko bezpieczna suma PLN.",
                    quality="complete" if overdue_value is not None else "unavailable",
                ),
                revenue_forecast_3m_pln=_kpi(
                    forecast_value,
                    "PLN",
                    "Suma prognozowanego przychodu kolejnych trzech miesięcy.",
                    quality="complete" if forecast_value is not None else "unavailable",
                ),
            ),
            alerts=alerts,
            queue=queue[:30],
            exceptions_board=exceptions,
        )
    else:
        trend_result = await _capture(
            quality, "finance_trend", lambda: sources.load_finance_trend(db, months=12)
        )
        if trend_result is not None:
            _, warnings, flag = trend_result
            quality.set(
                "finance_trend",
                _finance_flag_status(flag, warnings),
                warnings=warnings,
            )
        clients_result = await _capture(
            quality,
            "finance_clients",
            lambda: sources.load_finance_clients(db, as_of=as_of),
        )
        if clients_result is not None:
            _, warnings, flag = clients_result
            quality.set(
                "finance_clients",
                _finance_flag_status(flag, warnings),
                warnings=warnings,
            )
        quality.set(
            "mrr_at_risk",
            "unavailable",
            warnings=["Kanoniczna metryka MRR at risk 90d nie jest jeszcze dostępna."],
        )
        summary_values = summary or {}
        consultants = _mapping(summary_values.get("consultants"))
        utilization = consultants.get("utilization_pct")
        data = FinanceExecutiveDashboardData(
            kpis=FinanceExecutiveKpis(
                mrr_pln=_kpi(
                    summary_values.get("mrr"),
                    "PLN",
                    "MRR aktywnych date-effective kontraktów na as_of.",
                    quality=_source_kpi_quality(
                        quality,
                        "finance_summary",
                        summary_values.get("mrr"),
                    ),
                ),
                monthly_margin_pln=_kpi(
                    summary_values.get("monthly_margin"),
                    "PLN",
                    "Miesięczna marża aktywnych kontraktów na as_of.",
                    quality=_source_kpi_quality(
                        quality,
                        "finance_summary",
                        summary_values.get("monthly_margin"),
                    ),
                ),
                margin_pct=_kpi(
                    summary_values.get("margin_pct"),
                    "percent",
                    "Miesięczna marża / MRR.",
                    quality=_source_kpi_quality(
                        quality,
                        "finance_summary",
                        summary_values.get("margin_pct"),
                    ),
                ),
                revenue_forecast_3m_pln=_kpi(
                    forecast_value,
                    "PLN",
                    "Suma prognozowanego przychodu kolejnych trzech miesięcy.",
                    quality="complete" if forecast_value is not None else "unavailable",
                ),
                utilization_pct=_kpi(
                    utilization,
                    "percent",
                    "Aktywni konsultanci / aktywni + bench na as_of.",
                    quality=_source_kpi_quality(
                        quality,
                        "finance_summary",
                        utilization,
                    ),
                ),
                mrr_at_risk_90d_pln=_unavailable_kpi(
                    "PLN", "MRR kontraktów kończących się w ciągu 90 dni."
                ),
            ),
            alerts=alerts,
            queue=queue,
            exceptions_board=exceptions,
        )

    return FinanceDashboardResponse(
        generated_at=_now(),
        scope=scope.payload,
        data_quality=quality.build(),
        data=data,
    )


# ── Statystyki rekrutacji (sekcja wspólna wszystkich presetów) ───────────────

_RECRUITMENT_STATS_CACHE_PREFIX = "dashv2:recruitment-stats"


def _competition_entry(
    raw: dict[str, Any],
    fallback_rank: int,
    *,
    prize_pln: int | None = None,
) -> CompetitionRankingEntry:
    """Jawne mapowanie luźnego `RankedUser.to_dict()` na typowany kontrakt.

    Wybieramy wyłącznie znane klucze — nowe extras w serwisie konkursów nie
    wysadzą kontraktu `extra="forbid"`.
    """
    required = raw.get("required_verifications")
    # Review: nie `or 0` — legalne 0 zostaje zerem, ale None/brak klucza też
    # ma dać 0 bez połykania innych falsy wartości.
    metric = raw.get("metric_value")
    return CompetitionRankingEntry(
        rank=int(raw.get("rank") or fallback_rank),
        user_id=raw["user_id"],
        name=raw["name"],
        metric_value=metric if metric is not None else 0,
        role=raw.get("role"),
        hit_ratio=raw.get("hit_ratio"),
        prize_pln=raw.get("prize_pln", prize_pln),
        excluded=bool(raw.get("excluded", False)),
        qualified=raw.get("qualified"),
        placements=raw.get("placements"),
        interviews=raw.get("interviews"),
        recommendations=raw.get("recommendations"),
        verifications=raw.get("verifications"),
        precision_pct=raw.get("precision_pct"),
        required_verifications=int(required) if required is not None else None,
        disqualification_reasons=list(raw.get("disqualification_reasons") or []),
    )


def _recruitment_race(block: dict[str, Any]) -> RecruitmentMonthlyRace:
    leader = block.get("qualified_leader") or {}
    return RecruitmentMonthlyRace(
        requirements=list(block.get("requirements") or []),
        ranking=[
            _competition_entry(entry, idx + 1)
            for idx, entry in enumerate(block.get("ranking") or [])
        ],
        excluded_user_ids=list(block.get("excluded_user_ids") or []),
        qualified_leader_user_id=leader.get("user_id"),
    )


async def build_recruitment_stats_dashboard(
    user: User,
    db: AsyncSession,
    period: Period,
) -> RecruitmentStatsDashboardResponse:
    """Composite sekcji „Statystyki rekrutacji" na /dashboard.

    Dane są org-wide BY DESIGN (decyzja właściciela 2026-08-07: każda rola
    operacyjna widzi imienne wyniki całego zespołu) — scope w kopercie
    raportuje kontekst uprawnień widza, ale NIE filtruje danych. Dzięki temu
    payload jest identyczny dla każdego uprawnionego i cache może być
    org-level (klucz bez user_id): ciężkie CTE liczy się ≤1×/TTL niezależnie
    od liczby userów na stronie głównej.
    """
    scope = await sources.resolve_scope(user, db)

    cache_key = (
        f"{_RECRUITMENT_STATS_CACHE_PREFIX}:{period.kind.value}"
        f":{period.start.isoformat()}:{period.end.isoformat()}"
    )
    cached = await cache_get(cache_key)
    if cached:
        response = RecruitmentStatsDashboardResponse.model_validate(cached)
        # Scope odzwierciedla BIEŻĄCEGO widza, nie tego, kto napełnił cache.
        return response.model_copy(update={"scope": scope.payload})

    quality = _Quality()

    team = await _capture(
        quality,
        "team_funnel",
        lambda: sources.load_recruitment_team_panel(db, period),
    )
    # Guard typu zamiast duck-checku pojedynczego atrybutu (review): adapter
    # zwraca dokładnie TeamPanelResult; wszystko inne = malformed źródło.
    from app.services.kpi_team import TeamPanelResult

    if team is not None and not isinstance(team, TeamPanelResult):
        _mark_partial(
            quality,
            "team_funnel",
            "team_funnel: odpowiedź nie jest TeamPanelResult",
        )
        team = None
    league = await _capture(
        quality, "quarterly_league", lambda: sources.load_quarterly_league(db)
    )
    if league is not None and not _mapping_with_list_fields(league, "ranked"):
        _mark_partial(
            quality,
            "quarterly_league",
            "quarterly_league: odpowiedź nie zawiera rankingu",
        )
        league = None
    races = await _capture(
        quality, "monthly_races", lambda: sources.load_monthly_races(db)
    )

    def _race_block_shape_ok(block: Any) -> bool:
        # Review: guard musi pokrywać KAŻDY klucz czytany przy mapowaniu
        # (period/days_remaining/prize) — inaczej KeyError poza _capture
        # wywala cały endpoint zamiast zdegradować jeden blok.
        return (
            _mapping_with_list_fields(block, "ranking")
            and "period" in block
            and "days_remaining" in block
            and isinstance(block.get("prize"), dict)
            and "amount_pln" in block["prize"]
            and "name" in block["prize"]
        )

    if races is not None and not (
        isinstance(races, dict)
        and _race_block_shape_ok(races.get("recommendations"))
        and _race_block_shape_ok(races.get("placements"))
    ):
        _mark_partial(
            quality,
            "monthly_races",
            "monthly_races: odpowiedź nie zawiera kompletnych obu wyścigów",
        )
        races = None
    hof = await _capture(quality, "hall_of_fame", lambda: sources.load_hall_of_fame(db))
    if hof is not None and not _mapping_with_list_fields(hof, "all_time", "history"):
        _mark_partial(
            quality,
            "hall_of_fame",
            "hall_of_fame: odpowiedź nie zawiera all_time i history",
        )
        hof = None
    linkedin = await _capture(
        quality, "linkedin", lambda: sources.load_linkedin_summary(db, period)
    )
    if linkedin is not None and not _mapping_with_list_fields(linkedin, "per_user"):
        _mark_partial(
            quality,
            "linkedin",
            "linkedin: odpowiedź nie zawiera per_user",
        )
        linkedin = None
    trend = await _capture(quality, "trend", lambda: sources.load_recruitment_trend(db))

    kpi_quality = _source_kpi_quality(quality, "team_funnel", team)
    totals = team.totals if team is not None else None
    kpis = RecruitmentStatsKpis(
        verifications=_kpi(
            totals.weryfikacje if totals else None,
            "count",
            "Pierwsze przejścia na etap Zweryfikowany w oknie "
            "(atrybucja verifier-anchored).",
            quality=kpi_quality,
        ),
        recommendations=_kpi(
            totals.rekomendacje if totals else None,
            "count",
            "CV wysłane do klienta — pierwsze cv_sent per proces.",
            quality=kpi_quality,
        ),
        interviews=_kpi(
            totals.interview if totals else None,
            "count",
            "Pierwsze interview per proces.",
            quality=kpi_quality,
        ),
        acceptances=_kpi(
            totals.akceptacje if totals else None,
            "count",
            "Klient zaakceptował kandydata — pierwsze acceptance per proces.",
            quality=kpi_quality,
        ),
        placements=_kpi(
            totals.placementy if totals else None,
            "count",
            "Pierwsze hired per proces.",
            quality=kpi_quality,
        ),
    )

    team_table = None
    conversions = None
    if team is not None:
        team_table = RecruitmentTeamTable(
            precision_target_pct=team.precision_target_pct,
            rows=[
                RecruitmentTeamTableRow(
                    user_id=row.user_id,
                    name=row.name,
                    role=row.role,
                    verifications=row.weryfikacje,
                    recommendations=row.rekomendacje,
                    interviews=row.interview,
                    acceptances=row.akceptacje,
                    placements=row.placementy,
                    cv_to_base=row.cv_to_base,
                    precision_pct=row.precision_pct,
                    precision_verified_30d=row.precision_verified_30d,
                    precision_sent_30d=row.precision_sent_30d,
                )
                for row in team.rows
            ],
            totals=RecruitmentTeamTableTotals(
                verifications=team.totals.weryfikacje,
                recommendations=team.totals.rekomendacje,
                interviews=team.totals.interview,
                acceptances=team.totals.akceptacje,
                placements=team.totals.placementy,
                cv_to_base=team.totals.cv_to_base,
                precision_pct=team.totals.precision_pct,
                people=team.totals.people,
            ),
        )
        from app.services.recruitment_trend import funnel_conversions

        fc = funnel_conversions(
            weryfikacje=team.totals.weryfikacje,
            rekomendacje=team.totals.rekomendacje,
            interview=team.totals.interview,
            akceptacje=team.totals.akceptacje,
            placementy=team.totals.placementy,
        )
        conversions = RecruitmentFunnelConversions(
            verified_to_recommendation_pct=fc.verified_to_recommendation_pct,
            recommendation_to_interview_pct=fc.recommendation_to_interview_pct,
            interview_to_acceptance_pct=fc.interview_to_acceptance_pct,
            acceptance_to_placement_pct=fc.acceptance_to_placement_pct,
            interview_to_placement_pct=fc.interview_to_placement_pct,
            overall_pct=fc.overall_pct,
        )

    quarterly_league = None
    if league is not None:
        prizes: dict[str, int] = league.get("prizes_pln") or {}
        entries = [
            _competition_entry(
                entry,
                idx + 1,
                prize_pln=prizes.get(str(idx + 1)),
            )
            for idx, entry in enumerate(league["ranked"])
        ]
        quarterly_league = RecruitmentQuarterlyLeague(
            period=league["period"],
            days_remaining=league["days_remaining"],
            points_formula=league["points_formula"],
            prizes_pln=prizes,
            requirement=league["requirement"],
            top3=entries[:3],
            full_ranking=entries,
        )

    monthly_races = None
    if races is not None:
        rec_block = races["recommendations"]
        monthly_races = RecruitmentMonthlyRaces(
            period=rec_block["period"],
            days_remaining=rec_block["days_remaining"],
            prize_amount_pln=rec_block["prize"]["amount_pln"],
            prize_name=rec_block["prize"]["name"],
            recommendations=_recruitment_race(rec_block),
            placements=_recruitment_race(races["placements"]),
        )

    hall_of_fame = None
    if hof is not None:
        hall_of_fame = RecruitmentHallOfFame(
            all_time=[
                _competition_entry(entry, idx + 1)
                for idx, entry in enumerate(hof["all_time"])
            ],
            history=[
                RecruitmentHallOfFameHistoryPeriod(
                    period=item["period"],
                    top3=[
                        RecruitmentHallOfFameHistoryEntry(
                            rank=winner["rank"],
                            user_id=winner["user_id"],
                            name=winner["name"],
                            metric_value=winner.get("metric_value"),
                            points=winner.get("points"),
                            prize_pln=winner.get("prize_pln"),
                        )
                        for winner in item["top3"]
                    ],
                )
                for item in hof["history"]
            ],
        )

    linkedin_block = None
    if linkedin is not None:
        totals_raw = linkedin["totals"]
        linkedin_block = RecruitmentLinkedIn(
            date_from=linkedin["date_from"],
            date_to=linkedin["date_to"],
            per_user=[
                RecruitmentLinkedInRow(
                    user_id=row.user_id,
                    name=row.name,
                    role=row.role,
                    cv_added=row.cv_added,
                    messages_sent=row.messages_sent,
                    responses_received=row.responses_received,
                    response_rate=row.response_rate,
                    cv_response_rate=row.cv_response_rate,
                    days_reported=row.days_reported,
                )
                for row in linkedin["per_user"]
            ],
            totals=RecruitmentLinkedInTotals(**totals_raw),
        )

    trend_block = None
    if trend is not None:
        trend_block = RecruitmentTrend(
            months=[
                RecruitmentTrendMonth(
                    month=point.month,
                    verifications=point.weryfikacje,
                    recommendations=point.rekomendacje,
                    interviews=point.interview,
                    acceptances=point.akceptacje,
                    placements=point.placementy,
                )
                for point in trend
            ]
        )

    computed_at = _now()
    data_quality = quality.build()
    data_quality.source_watermarks["recruitment_stats.computed_at"] = computed_at

    response = RecruitmentStatsDashboardResponse(
        generated_at=computed_at,
        scope=scope.payload,
        data_quality=data_quality,
        data=RecruitmentStatsData(
            period=RecruitmentStatsPeriod(
                kind=period.kind.value,
                start=period.start,
                end=period.end,
            ),
            kpis=kpis,
            team_table=team_table,
            conversions=conversions,
            quarterly_league=quarterly_league,
            monthly_races=monthly_races,
            hall_of_fame=hall_of_fame,
            linkedin=linkedin_block,
            trend=trend_block,
        ),
    )
    # Krótszy TTL dla stanu zdegradowanego — awaria nie „zamraża się" na 2 min.
    ttl = 120 if data_quality.status == "complete" else 30
    await cache_set(cache_key, response.model_dump(mode="json"), ttl_seconds=ttl)
    return response
