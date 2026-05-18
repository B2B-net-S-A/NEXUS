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

from fastapi import APIRouter, Depends, File, Query, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, RecruiterPlus
from app.core.database import get_db
from app.models.dr_upload import DrUploadHistory
from app.models.user import User, UserRole

router = APIRouter()

ALLOWED_FILE_TYPES = {
    "body_leasing",
    "sales",
    "finances",
    "mrr_monthly",
    "sales_weekly",
}


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


@router.post(
    "/excel",
    response_model=UploadResultResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_excel(
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
    file: UploadFile = File(...),
    file_type: str = Query(
        ..., description="body_leasing | sales | finances | mrr_monthly | sales_weekly"
    ),
) -> UploadResultResponse:
    """Audit upload — XLSX parsing TODO.

    Obecnie zapisuje wpis w dr_upload_history ze statusem 'failed' i
    error_message wyjaśniającym że XLSX parsing nie jest zaimplementowany.
    Po dodaniu openpyxl parserów per file_type — będą wstrzykiwać dane
    do odpowiednich tabel dr_kpi_*.
    """
    if file_type not in ALLOWED_FILE_TYPES:
        return UploadResultResponse(
            upload_id=0,
            status="failed",
            records_inserted=0,
            error_message=f"Niedozwolony file_type. Oczekiwane: {ALLOWED_FILE_TYPES}",
        )

    file_name = file.filename or "unnamed.xlsx"
    # Read content to verify upload (but don't parse yet)
    content = await file.read()
    size_kb = len(content) // 1024

    entry = DrUploadHistory(
        uploaded_by=current_user.id,
        file_type=file_type,
        file_name=file_name,
        records_count=0,
        status="failed",
        error_message=(
            f"XLSX parsing dla file_type={file_type} jeszcze nie zaimplementowane "
            f"(B.2.11 follow-up). Plik {file_name} ({size_kb} KB) zarejestrowany "
            "tylko jako audit log."
        ),
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)

    return UploadResultResponse(
        upload_id=entry.id,
        status=entry.status,
        records_inserted=0,
        error_message=entry.error_message,
    )
