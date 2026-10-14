"""Szkic CV etapu sprzed podmiany nową generacją (Edytor CV 3, PR 5, 0444).

Do 14.10.2026 „Wygeneruj ponownie” nadpisywało niezatwierdzony szkic bez
śladu (zatwierdzona wersja zostawała w `cv_document_versions`). Migawka
trzyma treść i pochodzenie szkicu — „Wróć do poprzedniej” wraca do niej
jednym kliknięciem, a następne „Napisz od nowa” wie, co rekruter poprawiał.
"""

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

# `replaced` — szkic przed nową generacją; `restore` — wersja zdjęta przez
# „Wróć do poprzedniej” (nic nie ginie, ale tej nie przywracamy przyciskiem).
SNAPSHOT_REASONS = ("replaced", "restore")


class CvStageDraftSnapshot(Base):
    __tablename__ = "cv_stage_draft_snapshots"
    __table_args__ = (
        CheckConstraint(
            "reason IN ('replaced', 'restore')",
            name="ck_cv_stage_draft_snapshots_reason",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_stage_cv_id: Mapped[int] = mapped_column(
        ForeignKey("candidate_stage_cvs.id", ondelete="CASCADE"), nullable=False
    )
    content_html: Mapped[str] = mapped_column(Text, nullable=False)
    generated_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("cv_generated_documents.id", ondelete="SET NULL"), nullable=True
    )
    branded_from_generator: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    render_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    edit_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    restored_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    restored_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
