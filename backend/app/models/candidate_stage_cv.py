"""CV per rekrutacja — snapshot oryginalnego + edytowalna brandowana wersja.

Każdy `CandidateStage` ma 1:1 swój wpis w `candidate_stage_cvs`:

* `original_*` — niemutowalna migawka CV kandydata z momentu utworzenia
  CandidateStage. Klient w danej rekrutacji widzi DOKŁADNIE to CV, niezależnie
  od późniejszych zmian na profilu kandydata. Rozwiązuje pain point z Traffit
  ("ostatnio wgrane CV" myli rekruterów gdy kandydat jest na kilku req naraz).

* `branded_*` — opcjonalna brandowana prezentacja (Tiptap HTML, lazy-rendered
  z `_generate_cv_html()` przy pierwszym GET). Lifecycle: `none → draft →
  finalized`. Po finalize HTML idzie do storage_service (immutable snapshot)
  i można go udostępnić klientowi przez `CVShareToken`.

Mirror Phase 16 Contract Draft: `Contract.draft_content_html / draft_template_id
/ draft_updated_at / draft_updated_by + ContractDocument(doc_type=contract)`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.database import Base

if TYPE_CHECKING:  # pragma: no cover
    from app.models.candidate import Candidate
    from app.models.recruitment_pipeline import CandidateStage
    from app.models.user import User


class CandidateStageCV(Base):
    __tablename__ = "candidate_stage_cvs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # 1:1 z CandidateStage — UNIQUE constraint dba o niezduplikowanie.
    candidate_stage_id: Mapped[int] = mapped_column(
        ForeignKey("candidate_stages.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    # Denormalizacja — pozwala szybkie zapytania "wszystkie snapshoty per
    # kandydat" bez JOIN przez candidate_stages.
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ── Snapshot oryginalnego CV (niemutowalny po insert) ──────────────────
    original_cv_filename: Mapped[Optional[str]] = mapped_column(
        String(500), nullable=True
    )
    original_cv_content: Mapped[Optional[bytes]] = mapped_column(
        LargeBinary, nullable=True
    )
    original_cv_language: Mapped[Optional[str]] = mapped_column(
        String(10), nullable=True
    )
    original_snapshot_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # "auto_create" przy POST do pipeline / "backfill_0070" przy migracji /
    # "manual_refresh" gdy rekruter klika "Aktualizuj snapshot z bieżącego CV".
    original_snapshot_source: Mapped[Optional[str]] = mapped_column(
        String(20), nullable=True
    )

    # ── Brandowane CV — draft (Tiptap edit) i finalized (storage snapshot) ─
    # Status: 'none' (nigdy nie wygenerowane) | 'draft' (lazy-rendered, edytowalne)
    # | 'finalized' (snapshot do storage, immutable, można udostępnić klientowi).
    branded_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default="none",
        default="none",
    )
    branded_draft_html: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    edit_revision: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    branded_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    branded_template: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    branded_language: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    branded_updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    branded_updated_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    branded_finalized_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    branded_finalized_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # Po finalize: ścieżka i metadane pliku w storage_service (mirror
    # ContractDocument.file_path / file_name / size).
    branded_snapshot_path: Mapped[Optional[str]] = mapped_column(
        String(512), nullable=True
    )
    branded_snapshot_filename: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    branded_snapshot_size_bytes: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )

    # ── Audit ──────────────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # ── Relationships ──────────────────────────────────────────────────────
    candidate_stage: Mapped["CandidateStage"] = relationship(
        "CandidateStage", back_populates="cv_instance"
    )
    candidate: Mapped["Candidate"] = relationship("Candidate", lazy="select")
    branded_updated_by_user: Mapped[Optional["User"]] = relationship(
        "User", foreign_keys=[branded_updated_by], lazy="select"
    )
    branded_finalized_by_user: Mapped[Optional["User"]] = relationship(
        "User", foreign_keys=[branded_finalized_by], lazy="select"
    )

    def __repr__(self) -> str:
        return (
            f"<CandidateStageCV stage={self.candidate_stage_id} "
            f"branded_status={self.branded_status}>"
        )
