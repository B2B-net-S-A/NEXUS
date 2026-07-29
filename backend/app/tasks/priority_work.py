"""Restart-safe health and alert worker for Recruitment Priority Work."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.recruitment_priority import (
    PriorityAlertSeverity,
    PriorityExceptionStatus,
    PriorityMemberStatus,
    PriorityOriginKind,
    RecruitmentPriorityAlert,
    RecruitmentPriorityException,
)
from app.models.recruitment_process import ProcessStatus, RecruitmentProcess
from app.models.user import User, UserRole
from app.services.priority_work_service import (
    current_plan,
    ensure_priority_state,
    utcnow,
)

logger = logging.getLogger(__name__)
OPERATIONAL_ROLES = (UserRole.sourcer, UserRole.recruiter, UserRole.tac)


def _worker_interval_seconds() -> int:
    return max(
        60,
        int(
            getattr(
                settings,
                "RECRUITMENT_PRIORITY_WORKER_INTERVAL_SECONDS",
                300,
            )
        ),
    )


async def _upsert_alert(
    db,
    *,
    dedupe_key: str,
    kind: str,
    severity: PriorityAlertSeverity,
    payload: dict[str, Any],
) -> None:
    now = utcnow()
    statement = (
        pg_insert(RecruitmentPriorityAlert)
        .values(
            dedupe_key=dedupe_key,
            kind=kind,
            severity=severity,
            payload=payload,
            occurrence_count=1,
            first_seen_at=now,
            last_seen_at=now,
            resolved_at=None,
        )
        .on_conflict_do_update(
            index_elements=[RecruitmentPriorityAlert.dedupe_key],
            set_={
                "kind": kind,
                "severity": severity,
                "payload": payload,
                "occurrence_count": RecruitmentPriorityAlert.occurrence_count + 1,
                "last_seen_at": now,
                "resolved_at": None,
                "updated_at": now,
            },
        )
    )
    await db.execute(statement)


async def run_priority_work_sweep(db) -> dict[str, Any]:
    """Compute persisted health, expire exceptions and deduplicate alerts."""
    now = utcnow()
    state = await ensure_priority_state(db, for_update=True)
    plan = await current_plan(db)

    users = (
        (await db.execute(select(User).where(User.is_active.is_(True)))).scalars().all()
    )
    operational_ids = {
        user.id for user in users if user.has_any_role(*OPERATIONAL_ROLES)
    }
    covered_ids = {
        member.user_id
        for member in (plan.members if plan else [])
        if member.status
        in {
            PriorityMemberStatus.active,
            PriorityMemberStatus.paused,
        }
    }
    users_without_coverage = len(operational_ids - covered_ids)

    unowned_carry_over = int(
        await db.scalar(
            select(func.count(RecruitmentProcess.id))
            .outerjoin(User, User.id == RecruitmentProcess.owner_user_id)
            .where(
                RecruitmentProcess.status == ProcessStatus.open,
                (
                    RecruitmentProcess.owner_user_id.is_(None)
                    | User.id.is_(None)
                    | User.is_active.is_(False)
                ),
            )
        )
        or 0
    )
    process_total = int(
        await db.scalar(
            select(func.count(RecruitmentProcess.id)).where(
                RecruitmentProcess.status != ProcessStatus.voided
            )
        )
        or 0
    )
    eligibility_decided = int(
        await db.scalar(
            select(func.count(RecruitmentProcess.id)).where(
                RecruitmentProcess.status != ProcessStatus.voided,
                (
                    RecruitmentProcess.kpi_eligible.is_not(None)
                    | (RecruitmentProcess.origin_kind == PriorityOriginKind.legacy)
                ),
            )
        )
        or 0
    )
    eligibility_coverage_percent = (
        round(100.0 * eligibility_decided / process_total, 2)
        if process_total
        else 100.0
    )
    shadow_violation_count = int(
        await db.scalar(
            select(func.count(RecruitmentProcess.id)).where(
                RecruitmentProcess.priority_compliant_at_open.is_(False),
                RecruitmentProcess.kpi_eligible.is_(True),
                RecruitmentProcess.status != ProcessStatus.voided,
            )
        )
        or 0
    )
    overdue = bool(plan and plan.review_due_at and plan.review_due_at < now)
    global_mode = str(settings.RECRUITMENT_PRIORITY_MODE).lower()

    await db.execute(
        update(RecruitmentPriorityException)
        .where(
            RecruitmentPriorityException.status == PriorityExceptionStatus.approved,
            RecruitmentPriorityException.expires_at <= now,
        )
        .values(status=PriorityExceptionStatus.expired, updated_at=now)
    )

    alert_specs: list[tuple[str, str, PriorityAlertSeverity, dict[str, Any]]] = []
    if global_mode != "off":
        if overdue and plan:
            alert_specs.append(
                (
                    f"plan-overdue:{plan.id}",
                    "plan_overdue",
                    PriorityAlertSeverity.warning,
                    {
                        "plan_id": plan.id,
                        "version": plan.version,
                        "review_due_at": plan.review_due_at.isoformat(),
                    },
                )
            )
        if users_without_coverage:
            alert_specs.append(
                (
                    f"missing-coverage:{plan.id if plan else 'none'}",
                    "missing_assignments",
                    PriorityAlertSeverity.critical,
                    {"count": users_without_coverage},
                )
            )
        if unowned_carry_over:
            alert_specs.append(
                (
                    "unowned-carry-over",
                    "unowned_carry_over",
                    PriorityAlertSeverity.critical,
                    {"count": unowned_carry_over},
                )
            )
        if eligibility_coverage_percent < 100:
            alert_specs.append(
                (
                    "eligibility-gap",
                    "eligibility_coverage",
                    PriorityAlertSeverity.warning,
                    {
                        "percent": eligibility_coverage_percent,
                        "decided": eligibility_decided,
                        "total": process_total,
                    },
                )
            )
        if shadow_violation_count:
            alert_specs.append(
                (
                    f"shadow-delta:{plan.id if plan else 'none'}",
                    "shadow_delta",
                    PriorityAlertSeverity.warning,
                    {"count": shadow_violation_count},
                )
            )

    active_keys = {spec[0] for spec in alert_specs}
    for key, kind, severity, payload in alert_specs:
        await _upsert_alert(
            db,
            dedupe_key=key,
            kind=kind,
            severity=severity,
            payload=payload,
        )

    # Przy mode=off alert_specs jest z definicji puste, więc auto-resolve poniżej
    # zamknąłby KAŻDY otwarty alert. Rollback shadow → off (albo ostatni tick
    # starego workera podczas rolling restartu) po cichu czyścił listę alertów
    # zebranych w shadow. Sprzątamy tylko wtedy, gdy tryb faktycznie je wylicza.
    if global_mode != "off":
        unresolved = (
            (
                await db.execute(
                    select(RecruitmentPriorityAlert).where(
                        RecruitmentPriorityAlert.resolved_at.is_(None)
                    )
                )
            )
            .scalars()
            .all()
        )
        for alert in unresolved:
            if alert.dedupe_key not in active_keys:
                alert.resolved_at = now

    metrics = {
        "mode": global_mode,
        "current_plan_id": plan.id if plan else None,
        "current_plan_version": plan.version if plan else None,
        "plan_overdue": overdue,
        "users_without_coverage": users_without_coverage,
        "unowned_carry_over": unowned_carry_over,
        "process_total": process_total,
        "eligibility_decided": eligibility_decided,
        "eligibility_coverage_percent": eligibility_coverage_percent,
        "shadow_violation_count": shadow_violation_count,
        "active_alerts": len(active_keys),
    }
    state.worker_heartbeat_at = now
    state.last_alert_sweep_at = now
    state.last_error = None
    state.metrics = metrics
    state.row_version += 1
    await db.flush()
    return metrics


async def _persist_worker_error(exc: Exception) -> None:
    try:
        async with AsyncSessionLocal() as db:
            state = await ensure_priority_state(db, for_update=True)
            state.worker_heartbeat_at = utcnow()
            state.last_error = f"{type(exc).__name__}: {str(exc)[:400]}"
            state.row_version += 1
            await db.commit()
    except Exception:  # noqa: BLE001 - the original error remains primary
        logger.exception("priority_work: could not persist worker failure")


async def priority_work_loop() -> None:
    """Lifespan task. State lives in PostgreSQL, so restarts are harmless."""
    # Kill-switch sprawdzany RAZ, przed pętlą (jak w cloudtalk_sync). Przy mode=off
    # sweep i tak nie generuje alertów, ale przedtem co 300 s robił pełny skan
    # RecruitmentProcess + SELECT ... FOR UPDATE na singletonie — czyli całą pracę
    # przed sprawdzeniem trybu. Tryb siedzi w `Settings` (czytanym przy starcie
    # procesu), więc jego zmiana i tak wymaga redeployu; dzięki temu health
    # raportujący "disabled" przy mode=off wreszcie mówi prawdę.
    if str(settings.RECRUITMENT_PRIORITY_MODE).lower() == "off":
        logger.info("priority_work_loop not started — RECRUITMENT_PRIORITY_MODE=off")
        return

    interval = _worker_interval_seconds()
    logger.info(
        "priority_work_loop started (mode=%s interval=%ds)",
        settings.RECRUITMENT_PRIORITY_MODE,
        interval,
    )
    while True:
        try:
            async with AsyncSessionLocal() as db:
                metrics = await run_priority_work_sweep(db)
                await db.commit()
                logger.debug("priority_work sweep: %s", metrics)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - one tick must not kill the loop
            logger.exception("priority_work sweep failed")
            await _persist_worker_error(exc)
        try:
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            raise


def worker_is_fresh(
    heartbeat: datetime | None,
    *,
    now: datetime | None = None,
    interval_seconds: int | None = None,
) -> bool:
    """Pure health helper used by tests and `/api/health`."""
    if heartbeat is None:
        return False
    now = now or utcnow()
    interval = interval_seconds or _worker_interval_seconds()
    return heartbeat >= now - timedelta(seconds=max(180, interval * 3))
