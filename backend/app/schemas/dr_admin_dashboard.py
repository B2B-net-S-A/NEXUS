"""Pydantic schemas dla DynaReporter Admin dashboard.

Port `/admin` z artur-t-96/InfraReporter
(`server/src/routes/upload.ts` + `server/src/routes/placements.ts` +
`client/src/pages/AdminPanel.tsx`).

Tylko `admin` role w nexus może oglądać.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class AdminUserRow(BaseModel):
    """Pojedynczy user w widoku admina."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    role: str
    is_active: bool
    allowed_sections: list[str] = Field(default_factory=list)
    dynareporter_legacy_id: Optional[int] = None
    kpi_entries_count: int = Field(
        default=0, description="Liczba wpisów w dr_kpi_body_leasing"
    )


class UploadHistoryRow(BaseModel):
    """Pojedynczy upload w historii."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    uploaded_by_id: int
    uploaded_by_name: str
    file_type: str
    file_name: str
    records_count: int
    status: str
    error_message: Optional[str] = None
    created_at: datetime


class AuditLogRow(BaseModel):
    """Pojedynczy audit log entry."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    table_name: str
    action: str
    records_count: int
    performed_by_id: Optional[int] = None
    performed_by_name: Optional[str] = None
    created_at: datetime
    details: Optional[dict] = None
