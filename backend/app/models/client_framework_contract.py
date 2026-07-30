"""Klient-poziomowa umowa ramowa (MSA) — PDF + status + okres obowiązywania.

Każdy klient może mieć wiele umów ramowych w czasie (stara wygasła, nowa
podpisana, aneksy do każdej). `parent_contract_id` (self-FK) wiąże nową
wersję ze starą — UI pokazuje historię wersjonowania.

Linkowanie do `ClientContractTerms` (opcjonalne) — strukturalne metadane
(off-limits, payment net itp.) zostają w osobnej tabeli, ale można je
"przypiąć" do konkretnej wersji umowy. Jeden klient = jedna `ClientContractTerms`,
ale może mieć wiele `ClientFrameworkContract`.

Plik (PDF) trzymany poza DB przez storage_service (`save_client_framework_contract`)
— `file_path` analogiczny jak w `ClientRequiredDocument`.
"""

from __future__ import annotations

import enum
from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin


class FrameworkContractStatus(str, enum.Enum):
    """Lifecycle umowy ramowej z perspektywy NEXUSa.

    ``draft`` — utworzony rekord, plik może być wgrany lub nie, jeszcze nie
        wysłany do podpisu / niepodpisany.
    ``pending_signature`` — wysłany przez Autenti (wewnętrzny lub klient
        czeka na podpis).
    ``active`` — obowiązuje (signed + effective_date <= today).
    ``expired`` — wygasł (expiry_date < today). Scheduler flippuje status.
    ``terminated`` — rozwiązany przed expiry (manualny override).
    ``superseded`` — zastąpiony przez nowszą wersję (`parent_contract_id`
        wskazuje na nas z drugiej strony).
    """

    draft = "draft"
    pending_signature = "pending_signature"
    active = "active"
    expired = "expired"
    terminated = "terminated"
    superseded = "superseded"


class FrameworkContractSignedVia(str, enum.Enum):
    """Sposób w jaki umowa została podpisana."""

    upload = "upload"  # Skan/PDF już podpisany poza systemem
    autenti = "autenti"  # E-podpis przez Autenti
    legacy_import = "legacy_import"  # Zakres dat zaimportowany bez pliku PDF


class ClientFrameworkContract(Base, TimestampMixin):
    """Umowa ramowa (MSA) per klient — PDF + okres obowiązywania."""

    __tablename__ = "client_framework_contracts"
    __table_args__ = (
        CheckConstraint(
            "effective_date IS NULL OR expiry_date IS NULL "
            "OR expiry_date >= effective_date",
            name="ck_client_framework_contracts_dates",
        ),
        CheckConstraint(
            "char_length(btrim(source_system)) > 0",
            name="ck_client_framework_contracts_source_system_nonempty",
        ),
        CheckConstraint(
            "source_key IS NULL OR char_length(btrim(source_key)) > 0",
            name="ck_client_framework_contracts_source_key_nonempty",
        ),
        Index(
            "ux_client_framework_contracts_source_key",
            "source_system",
            "source_key",
            unique=True,
            postgresql_where=text("source_key IS NOT NULL"),
            sqlite_where=text("source_key IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    """Display name, np. ``MSA 2026 - rev. 2``."""

    status: Mapped[FrameworkContractStatus] = mapped_column(
        Enum(
            FrameworkContractStatus,
            name="frameworkcontractstatus",
            create_type=False,
        ),
        nullable=False,
        default=FrameworkContractStatus.draft,
        server_default="draft",
        index=True,
    )

    effective_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    expiry_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True, index=True)
    """Data wygaśnięcia — ``NULL`` = bezterminowa.

    Indeksowana — scheduler skanuje rekordy z ``expiry_date BETWEEN today
    AND today+30``.
    """

    signed_via: Mapped[FrameworkContractSignedVia] = mapped_column(
        Enum(
            FrameworkContractSignedVia,
            name="frameworkcontractsignedvia",
            create_type=False,
        ),
        nullable=False,
        default=FrameworkContractSignedVia.upload,
        server_default="upload",
    )

    currency: Mapped[Optional[str]] = mapped_column(String(3), nullable=True)
    """Default waluta dla orderów pod tą MSA (np. PLN/EUR)."""

    # Wersjonowanie — nowa MSA może zastąpić starą
    parent_contract_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("client_framework_contracts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    contract_terms_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("client_contract_terms.id", ondelete="SET NULL"), nullable=True
    )

    # File metadata (storage_service pattern)
    filename: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    file_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    content_type: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    size_bytes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    uploaded_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    uploaded_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Import provenance. ``source_key`` is stable within ``source_system`` and
    # makes re-applying the same reviewed Excel row idempotent.
    source_system: Mapped[str] = mapped_column(
        String(32), nullable=False, default="manual", server_default="manual"
    )
    source_key: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    import_run_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("client_import_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Relationships
    client = relationship("Client", backref="framework_contracts")
    parent_contract = relationship(
        "ClientFrameworkContract", remote_side=[id], foreign_keys=[parent_contract_id]
    )
    contract_terms = relationship(
        "ClientContractTerms", foreign_keys=[contract_terms_id]
    )
    uploader = relationship("User", foreign_keys=[uploaded_by])
    import_run = relationship("ClientImportRun", back_populates="framework_contracts")
    portfolio_scopes = relationship(
        "ClientPortfolioScope", back_populates="framework_contract"
    )
    amendments = relationship(
        "ClientContractAmendment",
        back_populates="framework_contract",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ClientContractAmendment.effective_date.desc()",
    )
    orders = relationship(
        "ClientOrder",
        back_populates="framework_contract",
        order_by="ClientOrder.start_date.desc()",
    )

    def __repr__(self) -> str:
        return (
            f"<ClientFrameworkContract id={self.id} client={self.client_id} "
            f"name={self.name!r} status={self.status}>"
        )
