"""Cortex — API warstwy „central intelligence" (PR1: fact store + widoki).

- ``GET  /api/cortex/tech-map``   — mapa skill × derived-seniority (z fill-rate)
- ``GET  /api/cortex/coverage``   — jakość danych: fill-rates, świeżość, procesy
- ``GET  /api/cortex/unmatched-terms`` — kolejka kuracji taksonomii (admin)
- ``POST /api/cortex/admin/backfill-traffit`` (+ ``/status``) — backfill faktów
  z ``traffit_technologie`` (cała baza, bez LLM)

RBAC: widoki dla admin/head_of_recruitment/delivery_lead/tac (dane nazwiskowe
kandydatów — RODO gate jak w Insights); backfill i kuracja — admin only.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminUser, get_db, require_roles
from app.core.database import AsyncSessionLocal
from app.models.cortex import CortexUnmatchedTerm
from app.models.user import User, UserRole
from app.services.cortex.coverage import compute_coverage
from app.services.cortex.extractor_traffit import run_traffit_backfill
from app.services.cortex.tech_map import compute_tech_map

logger = logging.getLogger(__name__)

router = APIRouter()

CortexUser = Annotated[
    User,
    Depends(
        require_roles(
            UserRole.admin,
            UserRole.head_of_recruitment,
            UserRole.delivery_lead,
            UserRole.tac,
        )
    ),
]

# Single-flight, in-memory (wzorzec admin_candidates._JOB): backfill jest
# idempotentny, więc po restarcie kontenera wystarczy odpalić ponownie.
_TRAFFIT_JOB: dict[str, Any] = {
    "running": False,
    "total": 0,
    "processed": 0,
    "facts_upserted": 0,
    "unmatched_tokens": 0,
    "errors": 0,
    "started_at": None,
    "finished_at": None,
    "limit": None,
    "last_error": None,
}


async def _run_traffit_job(limit: Optional[int]) -> None:
    _TRAFFIT_JOB.update(
        running=True,
        total=0,
        processed=0,
        facts_upserted=0,
        unmatched_tokens=0,
        errors=0,
        started_at=datetime.now(timezone.utc).isoformat(),
        finished_at=None,
        limit=limit,
        last_error=None,
    )
    try:
        async with AsyncSessionLocal() as db:
            await run_traffit_backfill(db, limit=limit, progress=_TRAFFIT_JOB)
    except Exception as e:  # noqa: BLE001 — never crash the background task
        _TRAFFIT_JOB["last_error"] = repr(e)
        logger.exception("[cortex] traffit backfill job crashed")
    finally:
        _TRAFFIT_JOB["running"] = False
        _TRAFFIT_JOB["finished_at"] = datetime.now(timezone.utc).isoformat()


@router.get("/tech-map")
async def tech_map(
    _user: CortexUser,
    db: AsyncSession = Depends(get_db),
    source: Optional[str] = Query(
        default=None,
        pattern="^(traffit|cv_llm|screening)$",
        description="Ogranicz do jednego źródła faktów.",
    ),
    employment: Optional[str] = Query(
        default=None,
        pattern="^at_client$",
        description="`at_client` = tylko konsultanci obecnie u klientów.",
    ),
    min_count: int = Query(
        default=2,
        ge=1,
        le=100,
        description="Ukryj komórki z mniejszą liczbą kandydatów (szum).",
    ),
) -> dict[str, Any]:
    """Mapa technologiczna bazy: komórki (skill, derived-seniority) → liczność."""
    return await compute_tech_map(
        db, source=source, employment=employment, min_count=min_count
    )


@router.get("/coverage")
async def coverage(
    _user: CortexUser, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Jakość danych Cortexa: fill-rates, świeżość faktów, stan procesów."""
    return await compute_coverage(db)


@router.get("/unmatched-terms")
async def unmatched_terms(
    _admin: AdminUser,
    db: AsyncSession = Depends(get_db),
    term_status: str = Query(
        default="new", alias="status", pattern="^(new|mapped|ignored|all)$"
    ),
    limit: int = Query(default=50, ge=1, le=500),
) -> list[dict[str, Any]]:
    """Kolejka kuracji taksonomii — najczęstsze tokeny spoza słownika."""
    q = select(CortexUnmatchedTerm).order_by(CortexUnmatchedTerm.occurrences.desc())
    if term_status != "all":
        q = q.where(CortexUnmatchedTerm.status == term_status)
    rows = (await db.execute(q.limit(limit))).scalars().all()
    return [
        {
            "term": row.term,
            "occurrences": row.occurrences,
            "status": row.status,
            "last_seen_at": row.last_seen_at.isoformat() if row.last_seen_at else None,
        }
        for row in rows
    ]


@router.post("/admin/backfill-traffit")
async def trigger_traffit_backfill(
    _admin: AdminUser,
    limit: Optional[int] = Query(
        default=None,
        ge=1,
        description="Przetwórz co najwyżej N kandydatów (batch weryfikacyjny). "
        "Bez limitu = cała baza z niepustym traffit_technologie.",
    ),
) -> dict[str, Any]:
    """Odpal backfill faktów z Traffita w tle. Admin only."""
    if _TRAFFIT_JOB["running"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Backfill już trwa",
        )
    asyncio.create_task(_run_traffit_job(limit))
    return {"status": "started", "limit": limit}


@router.get("/admin/backfill-traffit/status")
async def traffit_backfill_status(_admin: AdminUser) -> dict[str, Any]:
    """Postęp backfillu (in-memory; znika po restarcie kontenera)."""
    return dict(_TRAFFIT_JOB)
