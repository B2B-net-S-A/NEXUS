"""DynaReporter B.2.11 — historia uploadów (read-only) + wycofany upload.

R0 (plan 2026-07-16): POST /excel zwraca 410 Gone — parsowanie XLSX nigdy
nie powstało, a „pozorny sukces" wprowadzał w błąd. GET /history zostaje
jako audit log historycznych uploadów.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, RecruiterPlus
from app.core.database import get_db
from app.models.dr_upload import DrUploadHistory
from app.models.user import User, UserRole

router = APIRouter()


class UploadHistoryResponse(BaseModel):
    id: int
    uploaded_by: int
    uploader_name: Optional[str] = None
    file_type: str
    file_name: str
    records_count: int
    status: str
    error_message: Optional[str] = None
    created_at: datetime


@router.get("/history", response_model=list[UploadHistoryResponse])
async def list_history(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    file_type: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[UploadHistoryResponse]:
    is_priv = current_user.role in (
        UserRole.admin,
        UserRole.delivery_lead,
        UserRole.head_of_recruitment,
    )
    stmt = select(DrUploadHistory, User.name).outerjoin(
        User, User.id == DrUploadHistory.uploaded_by
    )
    if not is_priv:
        stmt = stmt.where(DrUploadHistory.uploaded_by == current_user.id)
    if file_type:
        stmt = stmt.where(DrUploadHistory.file_type == file_type)
    stmt = stmt.order_by(DrUploadHistory.created_at.desc()).limit(limit)
    rows = (await db.execute(stmt)).all()
    return [
        UploadHistoryResponse.model_validate({**r.__dict__, "uploader_name": n})
        for r, n in rows
    ]


@router.post("/excel")
async def upload_excel(
    current_user: RecruiterPlus,
) -> None:
    """Wycofane (R0, plan 2026-07-16): XLSX upload nigdy nie parsował danych —
    zwracał 201 z pozornym audit-logiem, sugerując że coś się wydarzyło.
    Live ATS jest jedynym źródłem bieżących statystyk; ręczne uploady
    DynaReportera nie wracają. Historia w dr_upload_history zostaje
    nietknięta (GET /history nadal działa).
    """
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail=(
            "Upload XLSX do DynaReportera został wycofany — bieżące statystyki "
            "liczy live ATS (Analytics v1)."
        ),
    )
