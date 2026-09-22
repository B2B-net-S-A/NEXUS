"""Publiczny opis rekrutacji na stronie kariery (0339).

1:1 z rekrutacją. Tekst powstaje ze szkicu AI i rekruter go ZATWIERDZA —
dopiero zatwierdzony opis jest widoczny pod ``/r/<slug>``. ``approved_hash``
to skrót treści w chwili zatwierdzenia: każda późniejsza zmiana treści daje
inny skrót, więc opis wraca do szkicu bez osobnej flagi do pilnowania.

Na stronie nigdy nie ma nazwy klienta ani stawki — pilnuje tego
deterministyczna kontrola ``services/public_profile_lint.py`` przy
zatwierdzeniu, a projekcja publiczna nie czyta ani klienta, ani kwot.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

DEFAULT_PUBLIC_SECTIONS = {"must": True, "nice": True, "params": True, "process": True}


class JobPublicProfile(Base):
    __tablename__ = "job_public_profiles"

    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True
    )
    subtitle: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    about: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sections: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default='{"must": true, "nice": true, "params": true, "process": true}',
        default=lambda: dict(DEFAULT_PUBLIC_SECTIONS),
    )
    show_on_recruiter_page: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true", default=True
    )
    approved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    approved_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    updated_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
