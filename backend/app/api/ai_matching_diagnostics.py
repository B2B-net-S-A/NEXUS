"""GET /api/admin/ai-matching/diagnostics — read-only ops view (plan support).

Surfaces the state of every flag-gated subsystem from the AI-matching plan
(telemetry, indexing outbox, versioned score cache, text schema, unified
retrieval) in one call, so the rollout can be operated by *observation* — flip a
flag, watch queue depth / lag / coverage / cache version distribution, decide
promote-or-stop. Strictly read-only; each section is guarded so a not-yet-created
table degrades to an error note instead of a 500.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_roles
from app.core.config import settings
from app.core.database import get_db
from app.models.user import User, UserRole

router = APIRouter()


def _flags() -> dict:
    keys = [
        "AI_MATCH_TELEMETRY_ENABLED",
        "AI_SCORING_CONTRACT_V2",
        "AI_INDEX_OUTBOX_ENABLED",
        "AI_INDEX_WORKER_ENABLED",
        "AI_TEXT_SCHEMA_V2",
        "AI_UNIFIED_RETRIEVAL_ENABLED",
        "AI_UNIFIED_RETRIEVAL_SURFACES",
    ]
    return {k: getattr(settings, k, None) for k in keys}


async def _outbox(db: AsyncSession) -> dict:
    try:
        from app.services import index_outbox_service as outbox

        return await outbox.diagnostics(db)
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)[:200]}


async def _telemetry(db: AsyncSession) -> dict:
    try:
        impressions = await db.scalar(text("SELECT count(*) FROM match_impressions"))
        runs = await db.scalar(
            text("SELECT count(DISTINCT run_id) FROM match_impressions")
        )
        outcomes = await db.scalar(text("SELECT count(*) FROM match_outcomes"))
        return {
            "impressions": int(impressions or 0),
            "distinct_runs": int(runs or 0),
            "outcomes": int(outcomes or 0),
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)[:200]}


async def _score_cache(db: AsyncSession) -> dict:
    try:
        rows = (
            await db.execute(
                text(
                    "SELECT scoring_algorithm_version, count(*) "
                    "FROM candidate_job_match_scores GROUP BY scoring_algorithm_version"
                )
            )
        ).all()
        stale = await db.scalar(
            text("SELECT count(*) FROM candidate_job_match_scores WHERE stale = true")
        )
        return {
            "by_version": {str(v): int(c) for v, c in rows},
            "stale": int(stale or 0),
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)[:200]}


@router.get("/ai-matching/diagnostics")
async def ai_matching_diagnostics(
    current_user: User = Depends(require_roles(UserRole.admin)),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """One-call snapshot of the AI-matching plan subsystems (admin, read-only)."""
    from app.services.matching_contracts import current_version_trace

    return {
        "flags": _flags(),
        "version_trace": current_version_trace().as_dict(),
        "indexing_outbox": await _outbox(db),
        "telemetry": await _telemetry(db),
        "score_cache": await _score_cache(db),
    }
