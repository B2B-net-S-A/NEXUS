"""DynaReporter Admin dashboard endpoint.

Port `/admin` z artur-t-96/InfraReporter:
- users: lista wszystkich nexus users z role + allowed_sections + DR legacy_id
- upload-history: lista uploads (dr_upload_history)
- audit-log: ostatnie zmiany (dr_data_audit_log)

Tylko admin role w nexus może oglądać (uprawnienia per-endpoint).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.core.database import get_db
from app.models.user import User, UserRole
from app.schemas.dr_admin_dashboard import (
    AdminUserRow,
    AuditLogRow,
    UploadHistoryRow,
)

router = APIRouter()


def _require_admin(current_user: User) -> None:
    """Multi-role aware — `has_role(admin)` sprawdza primary i secondary
    (users.roles JSONB). Quality check fixup LOW #10."""
    if not current_user.has_role(UserRole.admin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Wymagana rola admin",
        )


@router.get(
    "/users",
    response_model=list[AdminUserRow],
    summary="Lista wszystkich nexus users z DR legacy mapping + KPI completeness",
)
async def list_users(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> list[AdminUserRow]:
    """Zwraca wszystkich userów (admin tylko)."""
    _require_admin(current_user)

    # Single LEFT JOIN z pre-aggregated KPI count zamiast correlated subquery
    # per user (quality check MEDIUM #7).
    sql = text(
        """
        SELECT
            u.id,
            u.name,
            u.email,
            u.role::text AS role,
            u.is_active,
            u.allowed_sections,
            u.dynareporter_legacy_id,
            COALESCE(kpi.cnt, 0)::int AS kpi_entries_count
        FROM users u
        LEFT JOIN (
            SELECT user_id, count(*)::int AS cnt
            FROM dr_kpi_body_leasing
            GROUP BY user_id
        ) kpi ON kpi.user_id = u.id
        ORDER BY u.is_active DESC, u.name ASC
        """
    )
    rows = (await db.execute(sql)).all()
    return [
        AdminUserRow(
            id=r.id,
            name=r.name or "",
            email=r.email or "",
            role=r.role,
            is_active=r.is_active,
            allowed_sections=list(r.allowed_sections or []),
            dynareporter_legacy_id=r.dynareporter_legacy_id,
            kpi_entries_count=r.kpi_entries_count,
        )
        for r in rows
    ]


@router.get(
    "/upload-history",
    response_model=list[UploadHistoryRow],
    summary="Historia uploads (dr_upload_history) — ostatnie N rekordów",
)
async def list_upload_history(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[UploadHistoryRow]:
    """Lista uploadów Excel (admin tylko)."""
    _require_admin(current_user)

    sql = text(
        """
        SELECT
            h.id,
            h.uploaded_by AS uploaded_by_id,
            u.name AS uploaded_by_name,
            h.file_type,
            h.file_name,
            h.records_count,
            h.status,
            h.error_message,
            h.created_at
        FROM dr_upload_history h
        LEFT JOIN users u ON u.id = h.uploaded_by
        ORDER BY h.created_at DESC
        LIMIT :lim
        """
    )
    rows = (await db.execute(sql, {"lim": limit})).all()
    return [
        UploadHistoryRow(
            id=r.id,
            uploaded_by_id=r.uploaded_by_id,
            uploaded_by_name=r.uploaded_by_name or "(deleted user)",
            file_type=r.file_type or "",
            file_name=r.file_name or "",
            records_count=r.records_count or 0,
            status=r.status or "",
            error_message=r.error_message,
            created_at=r.created_at,
        )
        for r in rows
    ]


@router.get(
    "/audit-log",
    response_model=list[AuditLogRow],
    summary="Audit log (dr_data_audit_log) — ostatnie N zmian",
)
async def list_audit_log(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[AuditLogRow]:
    """Last N audit entries (admin tylko)."""
    _require_admin(current_user)

    sql = text(
        """
        SELECT
            a.id,
            a.table_name,
            a.action,
            a.records_count,
            a.performed_by AS performed_by_id,
            u.name AS performed_by_name,
            a.created_at,
            a.details
        FROM dr_data_audit_log a
        LEFT JOIN users u ON u.id = a.performed_by
        ORDER BY a.created_at DESC
        LIMIT :lim
        """
    )
    rows = (await db.execute(sql, {"lim": limit})).all()
    return [
        AuditLogRow(
            id=r.id,
            table_name=r.table_name or "",
            action=r.action or "",
            records_count=r.records_count or 0,
            performed_by_id=r.performed_by_id,
            performed_by_name=r.performed_by_name,
            created_at=r.created_at,
            details=r.details if isinstance(r.details, dict) else None,
        )
        for r in rows
    ]
