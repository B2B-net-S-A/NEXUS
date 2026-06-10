import enum
from typing import Optional

from sqlalchemy import Boolean, Enum, Integer, String, Text
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

    # External source tracking — Traffit / future imports.
    # Migracja 0071 dodaje partial unique index na (external_source, external_id).
    external_id: Mapped[Optional[str]] = mapped_column(String(100), index=True)
    external_source: Mapped[Optional[str]] = mapped_column(
        String(50), default="manual", index=True
    )

    # Relationships
    jobs = relationship("Job", back_populates="client")
    contracts = relationship("Contract", back_populates="client")
    tac_assignments = relationship(
        "ClientTacAssignment",
        back_populates="client",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Client id={self.id} name={self.name}>"
