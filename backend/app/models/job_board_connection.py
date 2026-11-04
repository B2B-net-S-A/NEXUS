"""Połączone konto firmy u dostawcy portali ogłoszeniowych (0381).

Jeden wiersz na dostawcę (dziś ``jjit`` — Employer Public API obsługujące
JustJoin.IT i RocketJobs). Tokeny OAuth leżą zaszyfrowane
(``core.encryption.get_token_cipher``); odświeżenie tokenu robi się pod
``FOR UPDATE`` tego wiersza, bo przy deployu żyją dwa procesy i oba mogą
chcieć odświeżyć naraz (dostawca unieważnia stary refresh token).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin

PROVIDER_JJIT = "jjit"

STATUS_ACTIVE = "active"
STATUS_RECONNECT_REQUIRED = "reconnect_required"


class JobBoardConnection(Base, TimestampMixin):
    __tablename__ = "job_board_connections"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'reconnect_required')",
            name="ck_job_board_connections_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=STATUS_ACTIVE, server_default=STATUS_ACTIVE
    )
    access_token_ct: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    refresh_token_ct: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # {"justjoinit": "<organizationUnitId>", "rocketjobs": "<organizationUnitId>"}
    organization_units: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    account_label: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    connected_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    connected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    last_refresh_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
