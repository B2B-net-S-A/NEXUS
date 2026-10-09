"""Plik rekrutacji albo niedokończonego formularza „Nowa rekrutacja” — 0428.

Kolumny i powód istnienia: ``app/services/job_file_schema.py``.
Trasy: ``app/api/job_files.py`` (rekrutacja) i ``app/api/job_intake_forms.py``
(formularz przed utworzeniem rekrutacji).
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin


class JobFile(Base, TimestampMixin):
    __tablename__ = "job_files"
    __table_args__ = (
        CheckConstraint("source IN ('request', 'upload')", name="ck_job_files_source"),
        Index(
            "ix_job_files_job", "job_id", postgresql_where=text("job_id IS NOT NULL")
        ),
        Index(
            "ix_job_files_intake_form",
            "intake_form_id",
            postgresql_where=text("intake_form_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=True
    )
    intake_form_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("job_intake_forms.id", ondelete="SET NULL"), nullable=True
    )
    # „request” = plik requestu klienta z kroku 1, „upload” = dodany ręcznie.
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, default="upload", server_default=text("'upload'")
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    size_bytes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    uploaded_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
