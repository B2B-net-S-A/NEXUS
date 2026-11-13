"""Panel konsultanta, pierwsza wersja — modele (0648).

CHECK-i i indeksy muszą być identyczne z ``app/services/consultant_panel_schema.py``
(strażnik dryfu schematu porównuje model z bazą po migracji).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.services import consultant_panel_schema as schema


class CpActivation(Base):
    __tablename__ = "cp_activations"
    __table_args__ = (
        UniqueConstraint("contract_id", name="uq_cp_activations_contract"),
        Index(
            "ix_cp_activations_active",
            "contract_id",
            postgresql_where=text("deactivated_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contract_id: Mapped[int] = mapped_column(
        ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    activated_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    activated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    deactivated_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    deactivated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class ClientOnboardingMaterial(Base):
    __tablename__ = "client_onboarding_materials"
    __table_args__ = (
        CheckConstraint(
            schema.CK_MATERIAL_KIND, name="ck_client_onboarding_materials_kind"
        ),
        CheckConstraint(
            schema.CK_MATERIAL_TITLE, name="ck_client_onboarding_materials_title"
        ),
        CheckConstraint(
            schema.CK_MATERIAL_SOURCE, name="ck_client_onboarding_materials_source"
        ),
        Index("ix_client_onboarding_materials_client", "client_id", "position"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=True
    )
    title: Mapped[str] = mapped_column(
        String(schema.MATERIAL_TITLE_MAX), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(8), nullable=False)
    url: Mapped[Optional[str]] = mapped_column(
        String(schema.MATERIAL_URL_MAX), nullable=True
    )
    file_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    file_name: Mapped[Optional[str]] = mapped_column(
        String(schema.FILE_NAME_MAX), nullable=True
    )
    mime: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    size_bytes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    position: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default="0", default=0
    )
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true"), default=True
    )
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


class CpActivationMaterial(Base):
    __tablename__ = "cp_activation_materials"
    __table_args__ = (Index("ix_cp_activation_materials_material", "material_id"),)

    activation_id: Mapped[int] = mapped_column(
        ForeignKey("cp_activations.id", ondelete="CASCADE"), primary_key=True
    )
    material_id: Mapped[int] = mapped_column(
        ForeignKey("client_onboarding_materials.id", ondelete="CASCADE"),
        primary_key=True,
    )


class ClientSettlementRule(Base):
    __tablename__ = "client_settlement_rules"
    __table_args__ = (
        CheckConstraint(
            schema.CK_SETTLEMENT_MODE, name="ck_client_settlement_rules_mode"
        ),
    )

    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), primary_key=True
    )
    mode: Mapped[str] = mapped_column(String(24), nullable=False)
    instructions: Mapped[str] = mapped_column(
        String(schema.INSTRUCTIONS_MAX), nullable=False, server_default="", default=""
    )
    updated_by: Mapped[Optional[int]] = mapped_column(
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


class CpTrainerApplication(Base):
    __tablename__ = "cp_trainer_applications"
    __table_args__ = (
        UniqueConstraint("contract_id", name="uq_cp_trainer_applications_contract"),
        CheckConstraint(schema.CK_TRAINER_FORM, name="ck_cp_trainer_applications_form"),
        CheckConstraint(
            schema.CK_TRAINER_TOPICS, name="ck_cp_trainer_applications_topics"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contract_id: Mapped[int] = mapped_column(
        ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False
    )
    case_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("admin_cases.id", ondelete="SET NULL"), nullable=True
    )
    topics: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb"), default=list
    )
    experience: Mapped[str] = mapped_column(
        String(schema.TRAINER_TEXT_MAX), nullable=False, server_default="", default=""
    )
    form: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default="online_or_onsite",
        default="online_or_onsite",
    )
    day_rate: Mapped[str] = mapped_column(
        String(schema.TRAINER_SHORT_MAX), nullable=False, server_default="", default=""
    )
    availability: Mapped[str] = mapped_column(
        String(schema.TRAINER_SHORT_MAX), nullable=False, server_default="", default=""
    )
    materials: Mapped[str] = mapped_column(
        String(schema.MATERIAL_URL_MAX), nullable=False, server_default="", default=""
    )
    # 0693 (13.11.2026): zgłoszenie zgodne z umową szkoleniową.
    proposal_title: Mapped[str] = mapped_column(
        String(200), nullable=False, server_default="", default=""
    )
    proposal_hours: Mapped[str] = mapped_column(
        String(schema.TRAINER_SHORT_MAX), nullable=False, server_default="", default=""
    )
    audience: Mapped[str] = mapped_column(
        String(schema.TRAINER_SHORT_MAX), nullable=False, server_default="", default=""
    )
    sample_path: Mapped[Optional[str]] = mapped_column(
        String(schema.MATERIAL_URL_MAX), nullable=True
    )
    sample_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    sample_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
