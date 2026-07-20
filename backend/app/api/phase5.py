"""
Phase 5 endpoints — completion pass:

- GET /api/embed-diagnostics    — verify Voyage + Qdrant health and state
- POST /api/embed-init           — force-create Qdrant collections (Manager+)
- CRUD /api/candidates/{id}/rate-history
- CRUD /api/candidates/{id}/conflicts
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.candidate_access import CandidateFinanceAccess
from app.api.deps import CurrentUser, ManagerOrAdmin
from app.core.config import settings
from app.core.database import get_db
from app.models.candidate import Candidate
from app.models.candidate_conflict import CandidateConflict, ConflictType
from app.models.job import Job
from app.models.rate_history import ContractType, RateHistory
from app.services.embedding_service import (
    _collection,
    _jobs_collection,
    generate_embedding,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Embedding diagnostics ───────────────────────────────────────────────────


@router.get("/embed-diagnostics")
async def embed_diagnostics(
    current_user: CurrentUser,
):
    """
    Report the state of the embedding pipeline so admins can diagnose
    "failed=N/N" situations without shell access.
    """
    report: dict = {
        "voyage": {"key_present": bool(settings.VOYAGE_API_KEY)},
        "qdrant": {
            "host": getattr(settings, "QDRANT_HOST", None),
            "port": getattr(settings, "QDRANT_PORT", None),
        },
        "collections": {"candidates": _collection(), "jobs": _jobs_collection()},
    }

    # Voyage ping — tiny 3-token test query
    if settings.VOYAGE_API_KEY:
        try:
            emb = await generate_embedding("diagnostic ping")
            report["voyage"]["ping_ok"] = emb is not None
            if emb is None:
                report["voyage"]["reason"] = (
                    "generate_embedding returned None (check server logs for Voyage HTTP status)"
                )
            else:
                report["voyage"]["dim"] = len(emb)
        except Exception as e:
            report["voyage"]["ping_ok"] = False
            report["voyage"]["reason"] = f"{type(e).__name__}: {e}"
    else:
        report["voyage"]["ping_ok"] = False
        report["voyage"]["reason"] = "VOYAGE_API_KEY is empty — set it in Coolify env"

    # Qdrant ping — list collections + counts
    def _qdrant_probe():
        from qdrant_client import QdrantClient

        client = QdrantClient(
            host=settings.QDRANT_HOST, port=settings.QDRANT_PORT, timeout=5
        )
        existing = [c.name for c in client.get_collections().collections]
        counts = {}
        for name in (_collection(), _jobs_collection()):
            if name in existing:
                try:
                    info = client.get_collection(name)
                    counts[name] = getattr(info, "points_count", None) or 0
                except Exception:
                    counts[name] = None
            else:
                counts[name] = "MISSING"
        return existing, counts

    try:
        existing, counts = await asyncio.to_thread(_qdrant_probe)
        report["qdrant"]["ok"] = True
        report["qdrant"]["all_collections"] = existing
        report["qdrant"]["counts"] = counts
    except Exception as e:
        report["qdrant"]["ok"] = False
        report["qdrant"]["reason"] = f"{type(e).__name__}: {e}"

    return report


@router.post("/embed-init")
async def embed_init(
    current_user: ManagerOrAdmin,
):
    """Force-create the Qdrant collections (idempotent)."""
    from app.services.embedding_service import init_qdrant_collection

    try:
        await asyncio.to_thread(init_qdrant_collection)
        return {"ok": True, "message": "Collections verified / created."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"init failed: {e}") from e


# ── Rate history CRUD ───────────────────────────────────────────────────────


class RateHistoryCreate(BaseModel):
    rate: int = Field(..., ge=1)
    currency: str = Field("PLN", max_length=3)
    contract_type: ContractType
    start_date: date
    end_date: Optional[date] = None
    client_id: Optional[int] = None
    job_id: Optional[int] = None
    notes: Optional[str] = None


class RateHistoryUpdate(BaseModel):
    rate: Optional[int] = Field(None, ge=1)
    currency: Optional[str] = None
    contract_type: Optional[ContractType] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    client_id: Optional[int] = None
    job_id: Optional[int] = None
    notes: Optional[str] = None


def _rate_to_dict(r: RateHistory) -> dict:
    return {
        "id": r.id,
        "candidate_id": r.candidate_id,
        "client_id": r.client_id,
        "job_id": r.job_id,
        "rate": r.rate,
        "currency": r.currency,
        "contract_type": r.contract_type.value,
        "start_date": r.start_date.isoformat() if r.start_date else None,
        "end_date": r.end_date.isoformat() if r.end_date else None,
        "notes": r.notes,
        "recorded_by": r.recorded_by,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


@router.get("/candidates/{candidate_id}/rate-history")
async def list_rate_history(
    candidate_id: int,
    current_user: CandidateFinanceAccess,
    db: AsyncSession = Depends(get_db),
):
    cand = await db.scalar(select(Candidate.id).where(Candidate.id == candidate_id))
    if not cand:
        raise HTTPException(status_code=404, detail="Candidate not found")
    rows = await db.execute(
        select(RateHistory)
        .where(RateHistory.candidate_id == candidate_id)
        .order_by(RateHistory.start_date.desc())
    )
    return [_rate_to_dict(r) for r in rows.scalars().all()]


@router.post(
    "/candidates/{candidate_id}/rate-history",
    status_code=status.HTTP_201_CREATED,
)
async def create_rate_history(
    candidate_id: int,
    data: RateHistoryCreate,
    current_user: ManagerOrAdmin,
    db: AsyncSession = Depends(get_db),
):
    cand = await db.scalar(select(Candidate.id).where(Candidate.id == candidate_id))
    if not cand:
        raise HTTPException(status_code=404, detail="Candidate not found")
    r = RateHistory(
        candidate_id=candidate_id,
        recorded_by=current_user.id,
        **data.model_dump(),
    )
    db.add(r)
    await db.commit()
    await db.refresh(r)
    return _rate_to_dict(r)


@router.patch("/rate-history/{rate_id}")
async def update_rate_history(
    rate_id: int,
    data: RateHistoryUpdate,
    current_user: ManagerOrAdmin,
    db: AsyncSession = Depends(get_db),
):
    r = await db.scalar(select(RateHistory).where(RateHistory.id == rate_id))
    if not r:
        raise HTTPException(status_code=404, detail="RateHistory not found")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(r, k, v)
    await db.commit()
    await db.refresh(r)
    return _rate_to_dict(r)


@router.delete("/rate-history/{rate_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rate_history(
    rate_id: int,
    current_user: ManagerOrAdmin,
    db: AsyncSession = Depends(get_db),
):
    r = await db.scalar(select(RateHistory).where(RateHistory.id == rate_id))
    if not r:
        raise HTTPException(status_code=404, detail="RateHistory not found")
    await db.delete(r)
    await db.commit()


# ── Candidate conflicts CRUD ────────────────────────────────────────────────


class ConflictCreate(BaseModel):
    client_id: int
    type: ConflictType
    reason: Optional[str] = None
    expires_at: Optional[str] = None


def _conflict_to_dict(c: CandidateConflict) -> dict:
    return {
        "id": c.id,
        "candidate_id": c.candidate_id,
        "client_id": c.client_id,
        "type": c.type.value,
        "reason": c.reason,
        "active": c.active,
        "expires_at": c.expires_at.isoformat() if c.expires_at else None,
        "created_by": c.created_by,
        "created_at": c.created_at.isoformat() if c.created_at else None,
    }


@router.get("/candidates/{candidate_id}/conflicts")
async def list_conflicts(
    candidate_id: int,
    current_user: CurrentUser,
    active_only: bool = True,
    db: AsyncSession = Depends(get_db),
):
    q = select(CandidateConflict).where(CandidateConflict.candidate_id == candidate_id)
    if active_only:
        q = q.where(CandidateConflict.active.is_(True))
    q = q.order_by(CandidateConflict.created_at.desc())
    rows = await db.execute(q)
    return [_conflict_to_dict(c) for c in rows.scalars().all()]


@router.post(
    "/candidates/{candidate_id}/conflicts",
    status_code=status.HTTP_201_CREATED,
)
async def create_conflict(
    candidate_id: int,
    data: ConflictCreate,
    current_user: ManagerOrAdmin,
    db: AsyncSession = Depends(get_db),
):
    cand = await db.scalar(select(Candidate.id).where(Candidate.id == candidate_id))
    if not cand:
        raise HTTPException(status_code=404, detail="Candidate not found")

    from datetime import datetime as dt

    expires = None
    if data.expires_at:
        try:
            expires = dt.fromisoformat(data.expires_at.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(
                status_code=422, detail="expires_at must be ISO-8601"
            ) from None

    cc = CandidateConflict(
        candidate_id=candidate_id,
        client_id=data.client_id,
        type=data.type,
        reason=data.reason,
        expires_at=expires,
        created_by=current_user.id,
    )
    db.add(cc)
    try:
        await db.commit()
    except (
        Exception
    ) as e:  # likely unique-index violation on (candidate, client) while active
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"Active conflict already exists for this (candidate, client): {e}",
        ) from e
    await db.refresh(cc)
    return _conflict_to_dict(cc)


@router.patch("/conflicts/{conflict_id}/deactivate")
async def deactivate_conflict(
    conflict_id: int,
    current_user: ManagerOrAdmin,
    db: AsyncSession = Depends(get_db),
):
    c = await db.scalar(
        select(CandidateConflict).where(CandidateConflict.id == conflict_id)
    )
    if not c:
        raise HTTPException(status_code=404, detail="Conflict not found")
    c.active = False
    await db.commit()
    return {"ok": True, "id": c.id, "active": False}


# ── Jobs context for UI dropdowns ───────────────────────────────────────────


@router.get("/clients-lookup")
async def clients_lookup(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    featured: bool = Query(
        False,
        description=(
            "Gdy true → zwróć tylko klientów z ustawionym display_name "
            "(wyselekcjonowana lista, np. dropdown generatora umów B2B)."
        ),
    ),
):
    """Minimal client list for dropdown (id, name) — avoids heavy /clients payload.

    Zwraca ``display_name`` (ręczne nadpisanie, odporne na sync Traffita) gdy
    ustawione, inaczej ``name``; ukryte (`hidden`) warianty pomija.

    ``featured=true`` zawęża do klientów z ustawionym ``display_name`` — to
    obecnie kuratorska lista (np. 17 nazw w generatorze umów B2B). „Na razie"
    marker = istnienie ``display_name``; gdyby kiedyś potrzebny był trwały
    odrębny znacznik, należałoby dodać dedykowaną kolumnę/flagę."""
    from sqlalchemy import func

    from app.models.client import Client

    name_col = func.coalesce(Client.display_name, Client.name)
    stmt = select(Client.id, name_col).where(Client.hidden.is_(False))
    if featured:
        stmt = stmt.where(Client.display_name.isnot(None))
    rows = await db.execute(stmt.order_by(name_col))
    return [{"id": r[0], "name": r[1]} for r in rows.all()]


@router.get("/jobs-lookup")
async def jobs_lookup(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Minimal job list for dropdown."""
    rows = await db.execute(
        select(Job.id, Job.title).order_by(Job.id.desc()).limit(500)
    )
    return [{"id": r[0], "title": r[1]} for r in rows.all()]
