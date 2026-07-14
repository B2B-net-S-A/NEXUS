"""DynaReporter B.2.11 — Upload + PDF endpoints.

Audit log uploadów (historia kto co kiedy wgrał).

NOTE: pełna obsługa parsowania XLSX (openpyxl) jest TODO w follow-up.
Endpoint POST /excel obecnie tylko rejestruje upload jako 'failed' z
error_message="parsowanie XLSX TODO". Po implementacji parserów per
file_type — zacząć insertować do dr_kpi_body_leasing / dr_kpi_sales / etc.

PDF generation — pominięte (WeasyPrint ma 200MB+ apt deps na ARM).
Można dodać reportlab w kolejnym PR po user feedback.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    AdminUser,
    CurrentUser,
    DynaReporterSection,
    require_dynareporter_section,
)
from app.core.database import get_db
from app.models.dr_upload import DrUploadHistory
from app.models.user import User, UserRole

router = APIRouter(
    dependencies=[Depends(require_dynareporter_section(DynaReporterSection.admin))]
)


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


class UploadResultResponse(BaseModel):
    upload_id: int
    status: str  # 'success' | 'failed' | 'partial'
    records_inserted: int
    error_message: Optional[str] = None


@router.get("/history", response_model=list[UploadHistoryResponse])
async def list_history(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    file_type: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[UploadHistoryResponse]:
    is_priv = current_user.has_any_role(
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


@router.post(
    "/excel",
    status_code=status.HTTP_410_GONE,
)
async def upload_excel(
    current_user: AdminUser,
) -> None:
    """The non-functional legacy importer is permanently disabled.

    Returning 410 prevents clients from mistaking an audit-only record for a
    successful import. Existing upload history remains available to admins.
    """
    del current_user
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="Legacy DynaReporter XLSX import has been retired",
    )
