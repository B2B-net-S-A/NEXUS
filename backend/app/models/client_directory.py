"""Canonical client-directory, alias and import-audit models.

The directory category is deliberately separate from ``Client.status``.
``Client.status`` remains the legacy operational/Traffit-facing status, while
``ClientPortfolioScope`` is the local commercial view used by the Clients
directory.  A client may therefore have multiple rows when it has multiple
framework-contract (MSA) periods.

Excel ingestion is staged in ``ClientImportRun`` / ``ClientImportRow`` before
anything is applied.  This preserves the source evidence and gives ambiguous
name matches a durable review state instead of silently merging records.
"""

from __future__ import annotations

import enum
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin


class PortfolioCategory(str, enum.Enum):
    """Local commercial grouping shown in the Clients directory."""

    active = "active"
    relationship = "relationship"
    inactive = "inactive"


class ClientImportRunStatus(str, enum.Enum):
    """Lifecycle of one immutable source file import."""

    uploaded = "uploaded"
    reviewed = "reviewed"
    applying = "applying"
    applied = "applied"
    rolled_back = "rolled_back"
    failed = "failed"


class ClientImportRowStatus(str, enum.Enum):
    """Decision/outcome for one row of a client import."""

    pending = "pending"
    matched = "matched"
    create = "create"
    ambiguous = "ambiguous"
    ignored = "ignored"
    applied = "applied"
    failed = "failed"


_RUN_STATUSES = tuple(status.value for status in ClientImportRunStatus)
_ROW_STATUSES = tuple(status.value for status in ClientImportRowStatus)


def _sql_values(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


class ClientImportRun(Base, TimestampMixin):
    """One reviewable, idempotent import of a source workbook."""

    __tablename__ = "client_import_runs"
    __table_args__ = (
        Index(
            "ux_client_import_runs_applied_source_sha256",
            "source_system",
            "source_sha256",
            unique=True,
            postgresql_where=text("status = 'applied'"),
            sqlite_where=text("status = 'applied'"),
        ),
        CheckConstraint(
            f"status IN ({_sql_values(_RUN_STATUSES)})",
            name="ck_client_import_runs_status",
        ),
        CheckConstraint(
            "char_length(btrim(source_system)) > 0",
            name="ck_client_import_runs_source_system_nonempty",
        ),
        CheckConstraint(
            "char_length(source_sha256) = 64",
            name="ck_client_import_runs_source_sha256",
        ),
        Index("ix_client_import_runs_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_system: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="client_excel",
        server_default="client_excel",
    )
    source_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[ClientImportRunStatus] = mapped_column(
        Enum(
            ClientImportRunStatus,
            name="clientimportrunstatus",
            native_enum=False,
            length=32,
            create_constraint=False,
        ),
        nullable=False,
        default=ClientImportRunStatus.uploaded,
        server_default=ClientImportRunStatus.uploaded.value,
    )
    summary: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text)

    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    applied_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    creator = relationship("User", foreign_keys=[created_by])
    approver = relationship("User", foreign_keys=[approved_by])
    rows = relationship(
        "ClientImportRow",
        back_populates="import_run",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ClientImportRow.id",
    )
    framework_contracts = relationship(
        "ClientFrameworkContract", back_populates="import_run"
    )


class ClientPortfolioScope(Base, TimestampMixin):
    """One directory row, optionally scoped to a concrete MSA period."""

    __tablename__ = "client_portfolio_scopes"
    __table_args__ = (
        CheckConstraint(
            "label IS NULL OR char_length(btrim(label)) > 0",
            name="ck_client_portfolio_scopes_label_nonempty",
        ),
        CheckConstraint(
            "char_length(btrim(source_system)) > 0",
            name="ck_client_portfolio_scopes_source_system_nonempty",
        ),
        CheckConstraint(
            "source_key IS NULL OR char_length(btrim(source_key)) > 0",
            name="ck_client_portfolio_scopes_source_key_nonempty",
        ),
        Index(
            "ux_client_portfolio_scopes_framework_contract_active",
            "framework_contract_id",
            unique=True,
            postgresql_where=text(
                "framework_contract_id IS NOT NULL AND archived_at IS NULL"
            ),
            sqlite_where=text(
                "framework_contract_id IS NOT NULL AND archived_at IS NULL"
            ),
        ),
        Index(
            "ux_client_portfolio_scopes_source_key_active",
            "source_system",
            "source_key",
            unique=True,
            postgresql_where=text("source_key IS NOT NULL AND archived_at IS NULL"),
            sqlite_where=text("source_key IS NOT NULL AND archived_at IS NULL"),
        ),
        Index(
            "ix_client_portfolio_scopes_category_label_active",
            "category",
            "label",
            postgresql_where=text("archived_at IS NULL"),
            sqlite_where=text("archived_at IS NULL"),
        ),
        Index("ix_client_portfolio_scopes_client_id", "client_id"),
        # Manual placement overrides must stay internally coherent, mirroring
        # the ``client_import_rows`` date check.
        CheckConstraint(
            "contract_start_override IS NULL "
            "OR contract_end_override IS NULL "
            "OR contract_end_override >= contract_start_override",
            name="ck_client_portfolio_scopes_override_dates",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    framework_contract_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("client_framework_contracts.id", ondelete="SET NULL"),
        nullable=True,
    )
    category: Mapped[PortfolioCategory] = mapped_column(
        Enum(
            PortfolioCategory,
            name="clientportfoliocategory",
            create_type=False,
        ),
        nullable=False,
        default=PortfolioCategory.inactive,
        server_default=PortfolioCategory.inactive.value,
    )
    label: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    source_system: Mapped[str] = mapped_column(
        String(32), nullable=False, default="manual", server_default="manual"
    )
    source_key: Mapped[Optional[str]] = mapped_column(String(255))
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # ── Manual placement overrides (UI-owned, manifest-invisible) ──────────────
    # The directory READ prefers these over ``category`` / the linked MSA dates,
    # but ``get_client_portfolio_import_health`` keeps reading the base columns,
    # so a manual move never breaks the manifest consistency invariant (no
    # ``applied_manifest_state_inconsistent`` drift, no /api/health/deep 503).
    # ``NULL`` means "follow the manifest / linked MSA"; a value pins a manual
    # placement.  The manifest apply never writes these.
    category_override: Mapped[Optional[PortfolioCategory]] = mapped_column(
        Enum(
            PortfolioCategory,
            name="clientportfoliocategory",
            create_type=False,
        ),
        nullable=True,
    )
    contract_start_override: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    contract_end_override: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    client = relationship("Client", back_populates="portfolio_scopes")
    framework_contract = relationship(
        "ClientFrameworkContract", back_populates="portfolio_scopes"
    )
    import_rows = relationship("ClientImportRow", back_populates="portfolio_scope")


class ClientAlias(Base, TimestampMixin):
    """A historical, shortened or source-specific name of a canonical client."""

    __tablename__ = "client_aliases"
    __table_args__ = (
        UniqueConstraint(
            "client_id",
            "normalized_alias",
            name="uq_client_aliases_client_normalized",
        ),
        CheckConstraint(
            "char_length(btrim(alias)) > 0",
            name="ck_client_aliases_alias_nonempty",
        ),
        CheckConstraint(
            "char_length(btrim(normalized_alias)) > 0",
            name="ck_client_aliases_normalized_nonempty",
        ),
        CheckConstraint(
            "char_length(btrim(source_system)) > 0",
            name="ck_client_aliases_source_system_nonempty",
        ),
        CheckConstraint(
            "source_key IS NULL OR char_length(btrim(source_key)) > 0",
            name="ck_client_aliases_source_key_nonempty",
        ),
        Index("ix_client_aliases_normalized_alias", "normalized_alias"),
        Index("ix_client_aliases_archived_at", "archived_at"),
        Index("ix_client_aliases_import_run_id", "import_run_id"),
        Index(
            "ux_client_aliases_source_key",
            "source_system",
            "source_key",
            unique=True,
            postgresql_where=text("source_key IS NOT NULL"),
            sqlite_where=text("source_key IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    alias: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_alias: Mapped[str] = mapped_column(String(255), nullable=False)
    source_system: Mapped[str] = mapped_column(
        String(32), nullable=False, default="manual", server_default="manual"
    )
    source_key: Mapped[Optional[str]] = mapped_column(String(255))
    import_run_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("client_import_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    client = relationship("Client", back_populates="aliases")
    import_run = relationship("ClientImportRun")


class ClientImportRow(Base, TimestampMixin):
    """Staged source row plus the reviewed match/application result."""

    __tablename__ = "client_import_rows"
    __table_args__ = (
        UniqueConstraint(
            "import_run_id",
            "sheet_name",
            "row_number",
            name="uq_client_import_rows_sheet_row",
        ),
        CheckConstraint(
            "row_number >= 1", name="ck_client_import_rows_row_number_positive"
        ),
        CheckConstraint(
            "char_length(btrim(source_name)) > 0",
            name="ck_client_import_rows_source_name_nonempty",
        ),
        CheckConstraint(
            f"status IN ({_sql_values(_ROW_STATUSES)})",
            name="ck_client_import_rows_status",
        ),
        CheckConstraint(
            "match_confidence IS NULL "
            "OR (match_confidence >= 0 AND match_confidence <= 1)",
            name="ck_client_import_rows_match_confidence",
        ),
        CheckConstraint(
            "start_date IS NULL OR end_date IS NULL OR end_date >= start_date",
            name="ck_client_import_rows_dates",
        ),
        Index("ix_client_import_rows_import_run_id", "import_run_id"),
        Index("ix_client_import_rows_matched_client_id", "matched_client_id"),
        Index("ix_client_import_rows_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    import_run_id: Mapped[int] = mapped_column(
        ForeignKey("client_import_runs.id", ondelete="CASCADE"), nullable=False
    )
    sheet_name: Mapped[str] = mapped_column(String(255), nullable=False)
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source_key: Mapped[Optional[str]] = mapped_column(String(255))
    source_name: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_name: Mapped[Optional[str]] = mapped_column(String(255))
    proposed_display_name: Mapped[Optional[str]] = mapped_column(String(255))
    proposed_legal_name: Mapped[Optional[str]] = mapped_column(String(255))
    category: Mapped[PortfolioCategory] = mapped_column(
        Enum(
            PortfolioCategory,
            name="clientportfoliocategory",
            create_type=False,
        ),
        nullable=False,
    )
    start_date: Mapped[Optional[date]] = mapped_column(Date)
    end_date: Mapped[Optional[date]] = mapped_column(Date)
    status: Mapped[ClientImportRowStatus] = mapped_column(
        Enum(
            ClientImportRowStatus,
            name="clientimportrowstatus",
            native_enum=False,
            length=32,
            create_constraint=False,
        ),
        nullable=False,
        default=ClientImportRowStatus.pending,
        server_default=ClientImportRowStatus.pending.value,
    )
    match_confidence: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 4))
    raw_payload: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    error_message: Mapped[Optional[str]] = mapped_column(Text)

    matched_client_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("clients.id", ondelete="SET NULL"), nullable=True
    )
    portfolio_scope_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("client_portfolio_scopes.id", ondelete="SET NULL"), nullable=True
    )
    framework_contract_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("client_framework_contracts.id", ondelete="SET NULL"),
        nullable=True,
    )
    resolved_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    import_run = relationship("ClientImportRun", back_populates="rows")
    matched_client = relationship("Client", back_populates="import_rows")
    portfolio_scope = relationship("ClientPortfolioScope", back_populates="import_rows")
    framework_contract = relationship("ClientFrameworkContract")
    resolver = relationship("User", foreign_keys=[resolved_by])
