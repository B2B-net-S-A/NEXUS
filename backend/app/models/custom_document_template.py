"""Wzory własne Generatora Umów B2B (0785, asystent prawny część B).

Wzór dodany w NEXUSIE, nie w kodzie: DOCX (szablon docxtpl) + lista pól.
Zatwierdza administrator; dopiero zatwierdzona wersja jest w „Nowy dokument”.
Wzór własny tylko tworzy dokument w rejestrze dokumentów Generatora — skutki
w kontraktach mają wyłącznie typy z rejestru programisty
(``services/b2b_documents/registry.py``). DDL: ``services/custom_templates/schema.py``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class CustomDocumentTemplate(Base):
    __tablename__ = "custom_document_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: Zatwierdzona wersja, z której wydaje się nowe dokumenty.
    active_version_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    withdrawn_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    withdrawn_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    withdrawn_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class CustomDocumentTemplateVersion(Base):
    __tablename__ = "custom_document_template_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    template_id: Mapped[int] = mapped_column(
        ForeignKey("custom_document_templates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="draft")
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="contract")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    client_scope: Mapped[str] = mapped_column(String(8), nullable=False, default="all")
    client_ids: Mapped[list[int]] = mapped_column(JSONB, nullable=False, default=list)
    signatories: Mapped[str] = mapped_column(String(24), nullable=False, default="both")
    signature_form: Mapped[str] = mapped_column(
        String(12), nullable=False, default="any"
    )
    origin: Mapped[str] = mapped_column(String(12), nullable=False)
    base_key: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    instruction: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    docx: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    docx_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    fields: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    changes: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    checks: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    warnings: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    ai_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    submitted_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    submitted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reviewed_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    review_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
