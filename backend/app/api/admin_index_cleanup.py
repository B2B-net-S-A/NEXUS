"""Admin index hygiene: review the plan (GET), then queue exactly it (POST).

``GET /api/admin/index-cleanup`` — read-only plan: candidate points without a
candidate row (orphans) and jobs without a vector or without the
``embedding_id`` stamp, with a fingerprint.

``POST /api/admin/index-cleanup`` — the reviewed fingerprint and counts. The
plan is rebuilt and work is queued only when it is unchanged: deletes for the
orphan points and upserts (the existing ``embed_job`` path) for the jobs, both
in the durable index outbox. Idempotent while the worker catches up. The worker
re-checks every orphan delete against the database before touching the index.

Admin only (JWT): unlike the snapshot inventories, this one queues writes.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminUser
from app.core.database import get_db
from app.services import index_cleanup
from app.services.index_outbox_service import worker_enabled

router = APIRouter()


class IndexCleanupApproval(BaseModel):
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    orphan_count: int = Field(ge=0)
    job_count: int = Field(ge=0)


def _unavailable() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Indeks wektorowy niedostępny — planu nie da się ustalić.",
    )


@router.get("/index-cleanup")
async def index_cleanup_plan(
    _admin: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Co zatwierdzenie zakolejkuje — bez żadnego zapisu."""
    try:
        plan = await index_cleanup.build_plan(db)
    except index_cleanup.IndexUnavailable:
        raise _unavailable() from None
    return {**plan, "worker_enabled": worker_enabled()}


@router.post("/index-cleanup")
async def index_cleanup_enqueue(
    approval: IndexCleanupApproval,
    _admin: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Zakolejkuj dokładnie przejrzany plan; inny plan → 409, nic nie idzie."""
    try:
        result = await index_cleanup.enqueue_reviewed_cleanup(
            db,
            expected_fingerprint=approval.fingerprint,
            orphan_count=approval.orphan_count,
            job_count=approval.job_count,
        )
    except index_cleanup.IndexUnavailable:
        raise _unavailable() from None
    except index_cleanup.CleanupPlanChanged:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Plan zmienił się od przeglądu — pobierz go ponownie (GET).",
        ) from None
    await db.commit()
    return result
