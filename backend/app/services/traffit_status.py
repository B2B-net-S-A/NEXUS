"""Read-only Traffit status shared by the authorized API and Admin Ops."""

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.tasks.traffit_sync import sync_is_running


async def read_traffit_status(db: AsyncSession) -> dict[str, Any]:
    """Current watermark + last-run stats for every phase + scheduler markers."""
    rows = await db.execute(
        text(
            "SELECT phase, last_synced_at, last_run_started_at, "
            "last_run_finished_at, last_status, stats, cursor_at, cursor_payload "
            "FROM traffit_sync_state ORDER BY phase"
        )
    )
    states = [
        {
            "phase": r.phase,
            "last_synced_at": r.last_synced_at.isoformat()
            if r.last_synced_at
            else None,
            "last_run_started_at": r.last_run_started_at.isoformat()
            if r.last_run_started_at
            else None,
            "last_run_finished_at": r.last_run_finished_at.isoformat()
            if r.last_run_finished_at
            else None,
            "last_status": r.last_status,
            "stats": r.stats,
            # Resume cursor (Stage 3) — non-null while a phase (e.g.
            # candidate_activities) is mid-catch-up; watch cursor.page advance
            # across runs to see resumable pagination working, NULL after a
            # full pass.
            "cursor_at": r.cursor_at.isoformat() if r.cursor_at else None,
            "cursor": r.cursor_payload,
        }
        for r in rows
    ]
    # Roll the parked rows up to the top level. Quarantine only works if
    # somebody sees it: a row that stops blocking the watermark but stays buried
    # three levels deep in a per-phase stats blob has simply been forgotten with
    # extra steps. This is the list an operator has to act on.
    quarantined: list[dict[str, Any]] = []
    for state in states:
        stats = state["stats"] or {}
        if not isinstance(stats, dict):
            continue
        attempts = stats.get("quarantine") or {}
        for ref in stats.get("quarantined") or []:
            quarantined.append(
                {
                    "phase": state["phase"],
                    "ref": ref,
                    "attempts": attempts.get(ref),
                    "last_seen": state["last_run_finished_at"],
                }
            )

    return {
        "enabled": settings.TRAFFIT_SYNC_ENABLED,
        "running": sync_is_running(),
        "max_row_attempts": settings.TRAFFIT_MAX_ROW_ATTEMPTS,
        "quarantined": quarantined,
        "states": states,
    }
