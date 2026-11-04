"""Wzór „Karty przed CV” klienta (0626, Credit Agricole 29.10.2026).

Jeden wiersz na klienta; wiersz = karta włączona. Plik leży w bazie, bo ma
telefony opiekunów — nie może trafić do repo. DDL i powód osobnej tabeli:
``app/services/cover_sheet_schema.py``; odczyt i zapis pliku:
``app/services/cover_sheet.py``; trasy: ``app/api/cover_sheets.py``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import DateTime, ForeignKey, Integer, LargeBinary, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, deferred, mapped_column

from app.core.database import Base


class ClientCoverSheetTemplate(Base):
    __tablename__ = "client_cover_sheet_templates"

    client_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("clients.id", ondelete="CASCADE"), primary_key=True
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    # Odroczone: odczyt metadanych (edytor reguły, „czy karta włączona”) nie
    # ciągnie pliku.
    content: Mapped[bytes] = deferred(mapped_column(LargeBinary, nullable=False))
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    # Rozpoznane pola wzoru: [{"id", "label"}] — do pokazania w edytorze.
    fields: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    uploaded_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
