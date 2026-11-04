"""Nagrobki notatek z Traffita usuniętych w NEXUSIE (migracja 0391, runda 10).

Promocja aktywności Traffita do ``notes`` (``_PROMOTE_NOTES_SQL``) pomija
aktywność, której ``source_ref`` jest tutaj — inaczej pełny sync zakładałby
usuniętą notatkę od nowa (R10-N6-1). Wiersz nie niesie treści ani danych
osobowych, tylko identyfikator źródła.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class DeletedNoteSource(Base):
    __tablename__ = "deleted_note_sources"

    source_ref: Mapped[str] = mapped_column(String(255), primary_key=True)
    deleted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
