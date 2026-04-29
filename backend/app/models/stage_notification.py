"""Konfigurowalne powiadomienia per stage transition.

Dwa modele:

- ``StageNotificationRule`` — baseline reguły wiszące na ``PipelineStageDef``.
  Definiują "kto ma dostać powiadomienie kiedy kandydat wchodzi na ten stage,
  jakim kanałem". Reguły wiszą przy template'ach pipeline'u.
- ``ClientStageNotificationOverride`` — override per klient. Jeśli klient
  ma ≥1 aktywny override dla pary ``(client_id, stage_def_id)``, baseline
  rules są pominięte całkowicie (deterministyczne; bez magic merging).

Resolver i emitter żyją w ``app.services.stage_notification_*``.
Migracja zakłada tabele + enum ``recipienttype`` + seed:
``backend/alembic/versions/0066_stage_notification_rules.py``.
"""

from datetime import datetime
from enum import Enum as PyEnum
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class RecipientType(str, PyEnum):
    """Typ adresata reguły powiadomień stage'a.

    Resolwer mapuje typ na konkretny ``user_id`` w czasie ruchu kandydata:
    - ``job_delivery_lead`` → ``Job.delivery_lead_id``
    - ``job_recruiter`` → ``Job.recruiter_id``
    - ``client_head_dl`` → DL z ``DeliveryLeadClientAssignment.is_head=TRUE``
    - ``client_primary_tac`` → TAC z ``ClientTacAssignment.is_primary=TRUE``
    - ``specific_user`` → ``rule.specific_user_id`` (wymagane gdy ten typ)
    - ``role`` → wszyscy aktywni userzy z daną rolą (multi-recipient)
    - ``candidate_creator`` → ``Candidate.created_by``
    """

    job_delivery_lead = "job_delivery_lead"
    job_recruiter = "job_recruiter"
    client_head_dl = "client_head_dl"
    client_primary_tac = "client_primary_tac"
    specific_user = "specific_user"
    role = "role"
    candidate_creator = "candidate_creator"


# Wspólny PG enum (utworzony przez migrację 0066). Używamy ``create_type=False``
# żeby SQLAlchemy nie próbował go re-tworzyć — jest stworzony w `op.execute`.
_RECIPIENT_TYPE_ENUM = Enum(
    RecipientType,
    name="recipienttype",
    native_enum=True,
    create_type=False,
    values_callable=lambda enum_cls: [member.value for member in enum_cls],
)


class StageNotificationRule(Base):
    """Baseline reguła powiadomień dla stage'a w template'cie pipeline'u."""

    __tablename__ = "stage_notification_rules"
    __table_args__ = (
        CheckConstraint(
            "(recipient_type = 'specific_user' AND specific_user_id IS NOT NULL) "
            "OR (recipient_type <> 'specific_user' AND specific_user_id IS NULL)",
            name="ck_stage_notif_specific_user",
        ),
        CheckConstraint(
            "(recipient_type = 'role' AND role IS NOT NULL) "
            "OR (recipient_type <> 'role' AND role IS NULL)",
            name="ck_stage_notif_role",
        ),
        Index("ix_stage_notif_rule_stage", "stage_def_id"),
        Index("ix_stage_notif_rule_active", "is_active"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    stage_def_id: Mapped[int] = mapped_column(
        ForeignKey("pipeline_stage_defs.id", ondelete="CASCADE"),
        nullable=False,
    )
    recipient_type: Mapped[RecipientType] = mapped_column(
        _RECIPIENT_TYPE_ENUM, nullable=False
    )
    specific_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    role: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    notify_inapp: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("TRUE"), default=True
    )
    notify_email: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("FALSE"), default=False
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("TRUE"), default=True
    )
    created_by: Mapped[Optional[int]] = mapped_column(
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

    stage_def = relationship("PipelineStageDef", foreign_keys=[stage_def_id])
    specific_user = relationship("User", foreign_keys=[specific_user_id])
    created_by_user = relationship("User", foreign_keys=[created_by])

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<StageNotificationRule id={self.id} stage_def={self.stage_def_id} "
            f"recipient={self.recipient_type.value} "
            f"inapp={self.notify_inapp} email={self.notify_email}>"
        )


class ClientStageNotificationOverride(Base):
    """Override per klient — wypiera baseline dla pary (client, stage_def).

    Override **całkowicie wypiera** baseline jeśli istnieje ≥1 aktywny rekord
    dla pary ``(client_id, stage_def_id)``. Jeśli wszystkie wpisy są
    ``is_active=FALSE`` lub brak wpisów → fallback do baseline rules.
    """

    __tablename__ = "client_stage_notification_overrides"
    __table_args__ = (
        CheckConstraint(
            "(recipient_type = 'specific_user' AND specific_user_id IS NOT NULL) "
            "OR (recipient_type <> 'specific_user' AND specific_user_id IS NULL)",
            name="ck_client_override_specific_user",
        ),
        CheckConstraint(
            "(recipient_type = 'role' AND role IS NOT NULL) "
            "OR (recipient_type <> 'role' AND role IS NULL)",
            name="ck_client_override_role",
        ),
        # NOTE: COALESCE-based UNIQUE jest tworzony bezpośrednio w migracji
        # (0066). SQLAlchemy nie wspiera COALESCE w UniqueConstraint, więc
        # tutaj nie deklarujemy go — ORM widzi tabelę "wystarczająco dobrze"
        # bez tego, a faktyczne wymuszenie dzieje się w PG.
        Index("ix_client_override_client_stage", "client_id", "stage_def_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    stage_def_id: Mapped[int] = mapped_column(
        ForeignKey("pipeline_stage_defs.id", ondelete="CASCADE"),
        nullable=False,
    )
    recipient_type: Mapped[RecipientType] = mapped_column(
        _RECIPIENT_TYPE_ENUM, nullable=False
    )
    specific_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    role: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    notify_inapp: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("TRUE"), default=True
    )
    notify_email: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("FALSE"), default=False
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("TRUE"), default=True
    )
    created_by: Mapped[Optional[int]] = mapped_column(
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

    client = relationship("Client", foreign_keys=[client_id])
    stage_def = relationship("PipelineStageDef", foreign_keys=[stage_def_id])
    specific_user = relationship("User", foreign_keys=[specific_user_id])
    created_by_user = relationship("User", foreign_keys=[created_by])

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<ClientStageNotificationOverride id={self.id} "
            f"client={self.client_id} stage_def={self.stage_def_id} "
            f"recipient={self.recipient_type.value}>"
        )
