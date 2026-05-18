"""DynaReporter B.2.11 — Upload history model."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class DrUploadHistory(Base):
    """Audit log uploadów Excel (per user × plik × typ)."""

    __tablename__ = "dr_upload_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    uploaded_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    file_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # 'body_leasing' | 'sales' | 'finances' | 'mrr_monthly' | 'sales_weekly'
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    records_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    status: Mapped[str] = mapped_column(String(20), default="success", server_default="success")
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), nullable=False
    )
