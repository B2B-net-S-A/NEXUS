"""Odczyt CV z podglądu „Dodaj kandydata” (0771).

Logika: ``app/services/cv_preview_cache.py``, DDL: ``cv_preview_reads_schema.py``.
Model jest dla metadanych (sonda i ``compare_metadata`` w ``/api/health/deep``);
zapis i odczyt idą surowym SQL-em.
"""

from datetime import datetime

from sqlalchemy import DateTime, LargeBinary, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class CvPreviewRead(Base):
    __tablename__ = "cv_preview_reads"

    sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    payload: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
