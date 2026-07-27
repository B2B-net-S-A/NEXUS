"""
Pipeline templates — replace hardcoded PipelineStage enum with elastic templates.

Architecture:
- PipelineTemplate holds a reusable definition ("Default B2B", "Sales", ...)
- PipelineStageDef is an ordered stage within a template
- RejectionReason is a structured dropdown value for terminal moves

Each Job points at a template via jobs.pipeline_template_id. Each CandidateStage
move points at a specific StageDef via candidate_stages.stage_def_id.

Backward-compat strategy:
- Legacy CandidateStage.stage (enum) remains valid and is populated alongside
  stage_def_id (mirror). PipelineStageDef.legacy_enum_value lets us translate
  between them in both directions until the enum column is dropped in Phase 3.
"""

import enum
from typing import Optional

from sqlalchemy import (
    Boolean,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
    text,
    true,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin


class StageCategoryEnum(str, enum.Enum):
    """Internal recruiter stage / external client-facing stage / terminal."""

    internal = "internal"
    external = "external"
    terminal = "terminal"


class TerminalType(str, enum.Enum):
    """Kind of terminal move — drives required rejection_reason_id."""

    hired = "hired"
    rejected = "rejected"
    withdrawn = "withdrawn"


class PipelineTemplate(Base, TimestampMixin):
    """A reusable pipeline definition that can be attached to jobs."""

    __tablename__ = "pipeline_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_default: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )
    archived: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))

    # Per-client default (Traffit gap #1, migracja 0090).
    # NULL = global template available to any job. When set, this template
    # becomes the preferred default for jobs of that client (resolved in
    # the job-create handler, not at the DB level — there is no UNIQUE
    # constraint on client_id since admins can keep variants).
    client_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("clients.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # External source tracking — Traffit / future imports.
    # Migracja 0074 dodaje partial unique index na (external_source, external_id).
    external_id: Mapped[Optional[str]] = mapped_column(String(100), index=True)
    external_source: Mapped[Optional[str]] = mapped_column(
        String(50), default="manual", index=True
    )

    stages = relationship(
        "PipelineStageDef",
        back_populates="template",
        cascade="all, delete-orphan",
        order_by="PipelineStageDef.order",
    )
    rejection_reasons = relationship(
        "RejectionReason",
        back_populates="template",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<PipelineTemplate id={self.id} name={self.name} default={self.is_default}>"


class PipelineStageDef(Base, TimestampMixin):
    """Ordered stage inside a PipelineTemplate."""

    __tablename__ = "pipeline_stage_defs"
    __table_args__ = (
        UniqueConstraint("template_id", "order", name="uq_stage_order_in_template"),
        UniqueConstraint("template_id", "name", name="uq_stage_name_in_template"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    template_id: Mapped[int] = mapped_column(
        ForeignKey("pipeline_templates.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    order: Mapped[int] = mapped_column(Integer, nullable=False)
    category: Mapped[StageCategoryEnum] = mapped_column(
        Enum(StageCategoryEnum, name="stagecategoryenum"), nullable=False
    )

    is_terminal: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )
    terminal_type: Mapped[Optional[TerminalType]] = mapped_column(
        Enum(TerminalType, name="terminaltype"), nullable=True
    )

    # Phase 3: public-facing candidate tracker
    tracker_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )
    tracker_public_name: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True
    )

    # Phase 3: SLA per stage (auto-notify when exceeded)
    sla_max_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Phase 3: stage-specific scorecards
    scorecard_schema: Mapped[Optional[dict]] = mapped_column(JSONB, default=dict)

    # Legacy enum value — populated only for the default B2B template; lets us
    # map the old PipelineStage enum to the new FK during Phase 1 + Phase 2.
    legacy_enum_value: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True, index=True
    )

    # External source tracking — Traffit workflow_state.id itp.
    # Migracja 0075 dodaje partial unique index na (external_source, external_id).
    external_id: Mapped[Optional[str]] = mapped_column(String(100), index=True)
    external_source: Mapped[Optional[str]] = mapped_column(
        String(50), default="manual", index=True
    )

    template = relationship("PipelineTemplate", back_populates="stages")

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<PipelineStageDef id={self.id} name={self.name} "
            f"order={self.order} category={self.category.value}>"
        )


class RejectionReason(Base, TimestampMixin):
    """Structured reason for a terminal (rejected/withdrawn) pipeline move."""

    __tablename__ = "rejection_reasons"
    __table_args__ = (
        UniqueConstraint("template_id", "name", "category", name="uq_rejection_reason"),
        Index(
            "ux_rejection_reasons_external_source_id",
            "external_source",
            "external_id",
            unique=True,
            postgresql_where=text("external_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    template_id: Mapped[int] = mapped_column(
        ForeignKey("pipeline_templates.id"), nullable=False, index=True
    )
    stage_def_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("pipeline_stage_defs.id"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    order: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    category: Mapped[TerminalType] = mapped_column(
        Enum(TerminalType, name="terminaltype"), nullable=False
    )
    active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False
    )
    # Czy ten powód jest werdyktem o OSOBIE (a nie o sytuacji). Tylko oznaczone
    # powody blokują ponowne zgłoszenie kandydata do tego samego hiring managera
    # (`services/hiring_manager_verdicts`). „Nie spełnia wymagań technicznych" —
    # tak; „Za wysokie oczekiwania finansowe" / „Zatrudniony gdzie indziej" — nie,
    # bo nie mówią nic o przydatności kandydata przy następnej okazji.
    # Domyślnie False: nieznany powód nie blokuje (fail-open).
    disqualifies_person: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )
    # Stabilna tożsamość powodu odrzucenia w Traffit — outbound
    # `_move_to_reject_state` wymaga jawnego mappingu remote `rejection_id`.
    external_source: Mapped[Optional[str]] = mapped_column(
        String(50), default="manual", nullable=True, index=True
    )
    external_id: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True, index=True
    )

    template = relationship("PipelineTemplate", back_populates="rejection_reasons")

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<RejectionReason id={self.id} name={self.name} "
            f"category={self.category.value} active={self.active}>"
        )
