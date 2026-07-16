"""Wersjonowane workflow rekrutacji (M4 audyt P0.2/P1.2, plan PR-05).

Shadow-tabele obok legacy ``pipeline_templates``/``pipeline_stage_defs`` —
w tym PR NIC nie czyta z nich w runtime; są fundamentem pod
``RecruitmentProcess`` (PR-06) i command service (PR-07):

- ``WorkflowDefinition`` — stabilna tożsamość workflow, 1:1 bridge do
  legacy template (``template_id`` UNIQUE),
- ``WorkflowRevision`` — immutable po publikacji; edycja = nowy draft;
  najwyżej JEDNA opublikowana rewizja per workflow (partial unique),
- ``StageRevision`` — etap w rewizji ze stabilnym ``semantic_key``
  (rejestr: ``app/services/semantic_states.py``); ``source_stage_def_id``
  wiąże z legacy stage'em na czas migracji,
- ``WorkflowEdge`` — dozwolone przejścia w rewizji.

Bootstrap (``workflow_registry_service``) generuje rewizję 1 dla każdego
aktywnego template'u: mapping legacy→semantic albo kwarantanna ``unmapped``
(nigdy zgadywanie — wymóg planu), krawędzie = pełny digraf (parity z dzisiaj:
move nie waliduje przejść; zaostrzanie przyjdzie nowymi rewizjami).
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin


class WorkflowRevisionStatus(str, enum.Enum):
    draft = "draft"
    published = "published"
    archived = "archived"


class WorkflowDefinition(Base, TimestampMixin):
    __tablename__ = "workflow_definitions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # 1:1 bridge do legacy — dopóki template istnieje, workflow dziedziczy
    # jego tożsamość (nazwa/klient mogą się rozjechać dopiero po cutoverze).
    template_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("pipeline_templates.id", ondelete="SET NULL"),
        nullable=True,
        unique=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    client_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("clients.id", ondelete="SET NULL"), nullable=True, index=True
    )
    archived: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    revisions = relationship(
        "WorkflowRevision",
        back_populates="workflow",
        cascade="all, delete-orphan",
        order_by="WorkflowRevision.revision_no",
    )


class WorkflowRevision(Base, TimestampMixin):
    __tablename__ = "workflow_revisions"
    __table_args__ = (
        UniqueConstraint("workflow_id", "revision_no", name="uq_workflow_rev_no"),
        # Najwyżej jedna OPUBLIKOWANA rewizja per workflow.
        Index(
            "ux_workflow_one_published",
            "workflow_id",
            unique=True,
            postgresql_where=text("status = 'published'"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workflow_id: Mapped[int] = mapped_column(
        ForeignKey("workflow_definitions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[WorkflowRevisionStatus] = mapped_column(
        Enum(WorkflowRevisionStatus, name="workflowrevisionstatus"),
        nullable=False,
        default=WorkflowRevisionStatus.draft,
    )
    # Skąd wzięła się rewizja (bootstrap / draft-from / editor) + wersja
    # rejestru semantycznego użyta przy tworzeniu — audytowalność mappingu.
    source: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    registry_version: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    published_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    published_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    workflow = relationship("WorkflowDefinition", back_populates="revisions")
    stages = relationship(
        "StageRevision",
        back_populates="revision",
        cascade="all, delete-orphan",
        order_by="StageRevision.order",
    )
    edges = relationship(
        "WorkflowEdge",
        back_populates="revision",
        cascade="all, delete-orphan",
    )


class StageRevision(Base):
    __tablename__ = "stage_revisions"
    __table_args__ = (
        UniqueConstraint("workflow_revision_id", "order", name="uq_stage_rev_order"),
        UniqueConstraint("workflow_revision_id", "name", name="uq_stage_rev_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workflow_revision_id: Mapped[int] = mapped_column(
        ForeignKey("workflow_revisions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Bridge do legacy stage'a (na czas migracji; SET NULL po ew. usunięciu).
    source_stage_def_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("pipeline_stage_defs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    order: Mapped[int] = mapped_column(Integer, nullable=False)
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    semantic_key: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    is_terminal: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )
    terminal_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    tracker_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )
    tracker_public_name: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True
    )
    sla_max_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    scorecard_schema: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    revision = relationship("WorkflowRevision", back_populates="stages")


class WorkflowEdge(Base):
    __tablename__ = "workflow_edges"
    __table_args__ = (
        UniqueConstraint(
            "workflow_revision_id",
            "from_stage_revision_id",
            "to_stage_revision_id",
            name="uq_workflow_edge",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workflow_revision_id: Mapped[int] = mapped_column(
        ForeignKey("workflow_revisions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # NULL = krawędź wejściowa (utworzenie procesu na tym etapie).
    from_stage_revision_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("stage_revisions.id", ondelete="CASCADE"), nullable=True
    )
    to_stage_revision_id: Mapped[int] = mapped_column(
        ForeignKey("stage_revisions.id", ondelete="CASCADE"), nullable=False
    )

    revision = relationship("WorkflowRevision", back_populates="edges")
