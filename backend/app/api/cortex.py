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
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminUser, get_db, require_roles
from app.core.database import AsyncSessionLocal
from app.models.cortex import CortexUnmatchedTerm
from app.models.user import User, UserRole
from app.services.cortex import client_stack as client_stack_svc
from app.services.cortex import curation as curation_svc
from app.services.cortex import drill_down as drill_down_svc
from app.services.cortex import runs
from app.services.cortex.coverage import compute_coverage
from app.services.cortex.extractor_traffit import execute_run
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

# Referencje zadań w tle (fire-and-forget ``create_task`` gubi je pod GC).
_bg_tasks: set[asyncio.Task] = set()


def _spawn(coro) -> None:
    task = asyncio.create_task(coro)
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)


async def _run_backfill_task(run_id: int, limit: Optional[int]) -> None:
    """Wykonaj zarezerwowany run w osobnej sesji (przeżywa zamknięcie requestu)."""
    try:
        async with AsyncSessionLocal() as task_db:
            await execute_run(task_db, run_id, limit=limit)
    except Exception:  # noqa: BLE001 — run już oznaczony `failed` w execute_run
        logger.exception("[cortex] backfill task crashed (run_id=%s)", run_id)


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
            "id": row.id,
            "term": row.term,
            "occurrences": row.occurrences,
            "status": row.status,
            "curated_by": row.curated_by,
            "curated_at": row.curated_at.isoformat() if row.curated_at else None,
            "first_seen_at": (
                row.first_seen_at.isoformat() if row.first_seen_at else None
            ),
            "last_seen_at": row.last_seen_at.isoformat() if row.last_seen_at else None,
        }
        for row in rows
    ]


# ── Etap 1: Action Layer (drill-down, search, client×stack, następcy) ─────────


@router.get("/skills")
async def cortex_skills(
    _user: CortexUser,
    db: AsyncSession = Depends(get_db),
    q: Optional[str] = Query(default=None, description="Szukaj po canonical/alias."),
    source: Optional[str] = Query(default=None, pattern="^(traffit|cv_llm|screening)$"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    """Pełna, przeszukiwalna, paginowana lista skilli z faktami (koniec top-40)."""
    return await drill_down_svc.list_skills(
        db, q=q, source=source, limit=limit, offset=offset
    )


@router.get("/skill/{skill_id}/candidates")
async def cortex_skill_candidates(
    skill_id: int,
    _user: CortexUser,
    db: AsyncSession = Depends(get_db),
    seniority: Optional[list[str]] = Query(default=None),
    source: Optional[str] = Query(default=None, pattern="^(traffit|cv_llm|screening)$"),
    employment: Optional[str] = Query(default=None, pattern="^(at_client|available)$"),
    min_confidence: Optional[float] = Query(default=None, ge=0, le=1),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    """Drill-down: konkretni kandydaci z danym skillem (evidence/confidence/świeżość).

    Widok nazwiskowy — RODO gate do ról Cortex (te same, co lista kandydatów)."""
    return await drill_down_svc.skill_candidates(
        db,
        skill_id,
        seniorities=seniority,
        source=source,
        employment=employment,
        min_confidence=min_confidence,
        limit=limit,
        offset=offset,
    )


@router.get("/client-stack")
async def cortex_client_stack(
    _user: CortexUser,
    db: AsyncSession = Depends(get_db),
    client_id: Optional[int] = Query(default=None),
    min_count: int = Query(default=1, ge=1, le=100),
) -> dict[str, Any]:
    """Macierz klient × stack × konsultanci (kto siedzi u klienta i z jakim stackiem)."""
    return await client_stack_svc.client_stack(
        db, client_id=client_id, min_count=min_count
    )


@router.get("/successors")
async def cortex_successors(
    _user: CortexUser,
    db: AsyncSession = Depends(get_db),
    days: int = Query(default=30, ge=1, le=365),
) -> dict[str, Any]:
    """Następcy dla kontraktów kończących się w ``days`` dni (dostępni, wspólny stack)."""
    return await client_stack_svc.contract_successors(
        db, now=datetime.now(timezone.utc).date(), days=days
    )


# ── Etap 1: kuracja taksonomii (admin-only, z audytem) ────────────────────────


class MapTermRequest(BaseModel):
    skill_id: int


class CreateSkillRequest(BaseModel):
    canonical_name: str = Field(min_length=1, max_length=255)
    category: Optional[str] = Field(default=None, max_length=64)
    aliases: Optional[list[str]] = None
    from_term_id: Optional[int] = None


class AddAliasRequest(BaseModel):
    alias: str = Field(min_length=1, max_length=255)


@router.post("/unmatched-terms/{term_id}/map")
async def cortex_map_term(
    term_id: int,
    payload: MapTermRequest,
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Zmapuj unmatched term na istniejący skill (dodaje alias). Admin only."""
    try:
        return await curation_svc.map_term_to_skill(
            db, term_id, payload.skill_id, curated_by=getattr(admin, "email", None)
        )
    except curation_svc.CurationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/unmatched-terms/{term_id}/ignore")
async def cortex_ignore_term(
    term_id: int,
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Oznacz unmatched term jako ignored. Admin only."""
    try:
        return await curation_svc.ignore_term(
            db, term_id, curated_by=getattr(admin, "email", None)
        )
    except curation_svc.CurationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/skills")
async def cortex_create_skill(
    payload: CreateSkillRequest,
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Utwórz nowy canonical skill (+ opcjonalne aliasy / z unmatched termu). Admin only."""
    try:
        return await curation_svc.create_skill(
            db,
            canonical_name=payload.canonical_name,
            category=payload.category,
            aliases=payload.aliases,
            from_term_id=payload.from_term_id,
            curated_by=getattr(admin, "email", None),
        )
    except curation_svc.CurationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/skills/{skill_id}/aliases")
async def cortex_add_alias(
    skill_id: int,
    payload: AddAliasRequest,
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Dodaj alias do istniejącego skilla. Admin only."""
    try:
        return await curation_svc.add_alias(
            db, skill_id, payload.alias, curated_by=getattr(admin, "email", None)
        )
    except curation_svc.CurationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/admin/backfill-traffit")
async def trigger_traffit_backfill(
    _admin: AdminUser,
    db: AsyncSession = Depends(get_db),
    limit: Optional[int] = Query(
        default=None,
        ge=1,
        description="Przetwórz co najwyżej N kandydatów (batch weryfikacyjny). "
        "Bez limitu = cała baza z niepustym traffit_technologie.",
    ),
) -> dict[str, Any]:
    """Odpal backfill faktów z Traffita w tle. Admin only.

    Single-flight jest atomowy: ``runs.create_run`` rezerwuje slot przez partial
    unique ``status='running'`` — zwraca ``None`` gdy inny run trwa (koniec
    TOCTOU z dawnej flagi in-memory). Sprzątamy najpierw osierocone runy.
    """
    await runs.reap_orphans(db)
    run_id = await runs.create_run(
        db, run_type="manual", triggered_by=getattr(_admin, "email", None)
    )
    if run_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Backfill już trwa",
        )
    _spawn(_run_backfill_task(run_id, limit))
    return {"status": "started", "run_id": run_id, "limit": limit}


@router.get("/admin/backfill-traffit/status")
async def traffit_backfill_status(
    _admin: AdminUser, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Postęp ostatniego backfillu — z trwałego ``cortex_extraction_runs``
    (przeżywa restart kontenera, w przeciwieństwie do dawnego in-memory dict)."""
    run = await runs.latest_run(db)
    if run is None:
        return {
            "running": False,
            "status": "idle",
            "total": 0,
            "processed": 0,
            "facts_upserted": 0,
            "unmatched_tokens": 0,
            "errors": 0,
            "started_at": None,
            "finished_at": None,
            "last_error": None,
        }
    stats = run.stats or {}
    return {
        "running": run.status == "running",
        "status": run.status,
        "run_id": run.id,
        "run_type": run.run_type,
        "triggered_by": run.triggered_by,
        "total": stats.get("total", 0),
        "processed": stats.get("processed", 0),
        "facts_upserted": stats.get("facts_upserted", 0),
        "unmatched_tokens": stats.get("unmatched_tokens", 0),
        "errors": stats.get("errors", 0),
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "heartbeat_at": run.heartbeat_at.isoformat() if run.heartbeat_at else None,
        "last_error": run.last_error,
    }
