import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin


class ClientStatus(str, enum.Enum):
    active = "active"
    inactive = "inactive"
    prospect = "prospect"


class Client(Base, TimestampMixin):
    """
    Klient/firma — podmiot zlecający rekrutacje.
    """

    __tablename__ = "clients"
    __table_args__ = (
        CheckConstraint(
            "merged_into_client_id IS NULL OR merged_into_client_id <> id",
            name="ck_clients_not_merged_into_self",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # Dane firmy
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    industry: Mapped[Optional[str]] = mapped_column(String(100))
    website: Mapped[Optional[str]] = mapped_column(String(500))
    address: Mapped[Optional[str]] = mapped_column(String(500))

    # Dane prawne klienta — używane przy generowaniu umów (migracja 0058)
    legal_name: Mapped[Optional[str]] = mapped_column(String(255))
    nip: Mapped[Optional[str]] = mapped_column(String(32))
    regon: Mapped[Optional[str]] = mapped_column(String(32))

    # Nadpisanie nazwy wyświetlanej w dropdownach (np. „Nordea Bank Abp").
    # ODPORNE na sync Traffita — importer NIE rusza tych pól (migracja 0127).
    # Pusty `display_name` → używamy `name`; `hidden` chowa zdublowane warianty.
    display_name: Mapped[Optional[str]] = mapped_column(String(255))
    hidden: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )

    # Status i umowy
    status: Mapped[ClientStatus] = mapped_column(
        Enum(ClientStatus), default=ClientStatus.prospect, nullable=False, index=True
    )
    nda_signed: Mapped[bool] = mapped_column(Boolean, default=False)
    contract_type: Mapped[Optional[str]] = mapped_column(
        String(100)
    )  # np. "ramowa", "jednorazowa"

    notes: Mapped[Optional[str]] = mapped_column(Text)

    # Sufit trybu obróbki CV wysyłanego do tego klienta:
    # "basic" | "polished" | "tailored"; NULL (domyślnie) = bez ograniczenia.
    # Ustawia się go, gdy klient zgłosi, że CV wyglądają na pisane pod jego
    # ogłoszenie — wtedy generator NIE pozwala wysłać wyżej niż sufit,
    # niezależnie od tego, co rekruter wybierze w UI. Bez tego obietnica
    # złożona klientowi zostaje deklaracją, którą znosi jeden checkbox.
    cv_content_mode_cap: Mapped[Optional[str]] = mapped_column(String(16))
    # Monotonic editor revision survives deletion/recreation of the recipe.
    cv_rule_edit_revision: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    # Czy hiring managerowie tego klienta widzą INTERAKTYWNĄ wersję CV na
    # publicznym linku (kafelki must/nice-have + chat). Domyślnie tak; flaga
    # jest świadomie NIEZALEŻNA od `cv_content_mode_cap` — kafelki pokazują
    # fakty z dowodami (cytaty z CV), nie sprzedażową narrację, więc sufit
    # trybu treści ich nie dotyczy. Wyłącz, gdy klient sobie nie życzy.
    cv_interactive_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    # External source tracking — Traffit / future imports.
    # Migracja 0071 dodaje partial unique index na (external_source, external_id).
    external_id: Mapped[Optional[str]] = mapped_column(String(100), index=True)
    external_source: Mapped[Optional[str]] = mapped_column(
        String(50), default="manual", index=True
    )

    # Local canonicalisation lifecycle. A duplicate can be archived and point
    # at the retained client while preserving (rather than deleting) history.
    # These fields are intentionally independent from Traffit's external
    # identity and from the legacy operational ``status``.
    merged_into_client_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("clients.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    archived_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    archived_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Relationships
    jobs = relationship("Job", back_populates="client")
    contracts = relationship("Contract", back_populates="client")
    tac_assignments = relationship(
        "ClientTacAssignment",
        back_populates="client",
        cascade="all, delete-orphan",
    )
    merged_into = relationship(
        "Client",
        remote_side=[id],
        foreign_keys=[merged_into_client_id],
        back_populates="merged_clients",
    )
    merged_clients = relationship(
        "Client",
        foreign_keys=[merged_into_client_id],
        back_populates="merged_into",
    )
    archived_by_user = relationship("User", foreign_keys=[archived_by])
    portfolio_scopes = relationship(
        "ClientPortfolioScope",
        back_populates="client",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    aliases = relationship(
        "ClientAlias",
        back_populates="client",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    import_rows = relationship("ClientImportRow", back_populates="matched_client")

    def __repr__(self) -> str:
        return f"<Client id={self.id} name={self.name}>"
