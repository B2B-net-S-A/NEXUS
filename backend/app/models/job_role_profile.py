"""Profil „Kogo szukamy” rekrutacji (0728) — DDL w ``services/job_role_profile_schema.py``."""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class JobRoleProfile(Base):
    __tablename__ = "job_role_profiles"

    job_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[Optional[str]] = mapped_column(String(120))
    specialty: Mapped[Optional[str]] = mapped_column(String(120))
    technology: Mapped[Optional[str]] = mapped_column(String(120))
    level: Mapped[str] = mapped_column(
        String(16), nullable=False, default="dowolny", server_default="dowolny"
    )
    # Etykiety „Nie proponujemy” wpisane ręcznie (tekst, jak wpisał człowiek).
    excluded: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # Etykiety z odrzuceń zdjęte z listy (klucze casefold).
    dismissed: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    updated_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
