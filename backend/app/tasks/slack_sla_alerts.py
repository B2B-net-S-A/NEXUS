"""
Phase 7c — Slack alerts for SLA violations.

Polls pipeline overview-sla logic every N minutes, finds new breaches since
the last check, and posts them to SLACK_WEBHOOK_URL (if configured).

Dedup: keeps an in-process set of already-alerted (candidate_stage_id, moved_at)
pairs so we don't spam on every poll. A new breach = a candidate stage that
crossed its SLA threshold since the last run (or entered a new stage that's
already over SLA). On each run we replace the set — this does mean if the
worker restarts, we'll re-alert once per breach, which is acceptable noise.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models.pipeline_template import PipelineStageDef
from app.models.recruitment_pipeline import CandidateStage

logger = logging.getLogger(__name__)


_DEFAULT_INTERVAL_MINUTES = 30


async def _compute_breaches(db: AsyncSession) -> list[dict]:
    """Re-implement the overview-sla logic for task use (no HTTP self-call)."""
    q = await db.execute(
        select(CandidateStage).order_by(
            CandidateStage.candidate_id,
            CandidateStage.job_id,
            CandidateStage.moved_at.desc(),
        )
    )
    latest: dict[tuple[int, int], CandidateStage] = {}
    for s in q.scalars().all():
        key = (s.candidate_id, s.job_id)
        if key not in latest:
            latest[key] = s

    stage_def_ids = {s.stage_def_id for s in latest.values() if s.stage_def_id}
    stage_defs: dict[int, PipelineStageDef] = {}
    if stage_def_ids:
        sd_rows = await db.execute(
            select(PipelineStageDef).where(PipelineStageDef.id.in_(stage_def_ids))
        )
        stage_defs = {sd.id: sd for sd in sd_rows.scalars().all()}

    now = datetime.now(timezone.utc)
    breaches: list[dict] = []
    for s in latest.values():
        sd = stage_defs.get(s.stage_def_id or 0)
        if not sd or not sd.sla_max_days or sd.is_terminal:
            continue
        moved = s.moved_at
        if moved.tzinfo is None:
            moved = moved.replace(tzinfo=timezone.utc)
        days = (now - moved).days
        if days > sd.sla_max_days:
            breaches.append(
                {
                    "candidate_stage_id": s.id,
                    "candidate_id": s.candidate_id,
                    "job_id": s.job_id,
                    "stage_name": sd.name,
                    "days_in_stage": days,
                    "sla_max_days": sd.sla_max_days,
                    "overdue_by_days": days - sd.sla_max_days,
                }
            )
    return breaches


async def _post_to_slack(webhook: str, breach: dict) -> None:
    """Best-effort Slack post. Silently logs errors."""
    text = (
        f":warning: SLA breach — kandydat #{breach['candidate_id']} "
        f"utknął w etapie *{breach['stage_name']}* od {breach['days_in_stage']} dni "
        f"(SLA = {breach['sla_max_days']}d, overdue +{breach['overdue_by_days']}d). "
        f"Oferta: #{breach['job_id']}"
    )
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(webhook, json={"text": text})
    except Exception as e:  # noqa: BLE001
        logger.warning("slack_sla_alerts: post failed %s", e)


async def slack_sla_alerts_loop(
    interval_minutes: float = _DEFAULT_INTERVAL_MINUTES,
) -> None:
    """Long-running task: poll for SLA breaches and alert on Slack."""
    webhook = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
    if not webhook:
        logger.info("slack_sla_alerts: SLACK_WEBHOOK_URL not set — task disabled")
        return

    logger.info("slack_sla_alerts: started interval=%.1f min", interval_minutes)
    alerted: set[int] = set()  # candidate_stage_ids already reported
    # Initial delay so app startup isn't slowed
    await asyncio.sleep(90)
    while True:
        try:
            async with AsyncSessionLocal() as db:
                breaches = await _compute_breaches(db)
            new_breaches = [
                b for b in breaches if b["candidate_stage_id"] not in alerted
            ]
            for b in new_breaches:
                await _post_to_slack(webhook, b)
                alerted.add(b["candidate_stage_id"])
            # Clean up: if a stage is no longer in breaches (stage moved), let it re-alert if it comes back
            active_ids = {b["candidate_stage_id"] for b in breaches}
            alerted &= active_ids  # keep only still-breaching
            if new_breaches:
                logger.info(
                    "slack_sla_alerts: posted %d new breach alerts", len(new_breaches)
                )
        except Exception as e:  # noqa: BLE001
            logger.warning("slack_sla_alerts: cycle error %s", e)
        await asyncio.sleep(interval_minutes * 60)
