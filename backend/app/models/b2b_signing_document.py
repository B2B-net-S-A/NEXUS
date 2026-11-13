"""Dokument w paczce do podpisu obok umowy B2B (0687, decyzja Artura 13.11.2026).

Kontraktor podpisuje pod jednym linkiem umowę i wzory z listy klienta
„Dokumenty do startu” (NDA, oświadczenie o niekaralności i inne). Dokument
podpisuje tylko kontraktor, kwalifikowanym podpisem, w PDF-ie zamrożonym przy
wysyłce (odcisk SHA-256 + długość, jak umowa). Podpisany plik od razu trafia
do pozycji pary w „Dokumentach do startu”. DDL:
``services/b2b_esign/documents_schema.py``.
"""

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import DateTime, ForeignKey, Integer, SmallInteger, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin


class B2BSigningDocument(Base, TimestampMixin):
    __tablename__ = "b2b_signing_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_id: Mapped[int] = mapped_column(
        ForeignKey("b2b_signing_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Pozycja listy klienta, z której wzięto wzór (usunięcie pozycji zostawia
    # dokument w paczce).
    start_document_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("client_start_documents.id", ondelete="SET NULL"), nullable=True
    )
    position: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, server_default="0"
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    source_pdf_path: Mapped[str] = mapped_column(String(512), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_size: Mapped[int] = mapped_column(Integer, nullable=False)
    signed_pdf_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    signed_sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    signed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    validation: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
