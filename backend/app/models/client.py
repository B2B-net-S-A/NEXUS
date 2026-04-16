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

    # Osoba kontaktowa
    contact_person: Mapped[Optional[str]] = mapped_column(String(255))
    contact_email: Mapped[Optional[str]] = mapped_column(String(255))
    contact_phone: Mapped[Optional[str]] = mapped_column(String(30))

    # Status i umowy
    status: Mapped[ClientStatus] = mapped_column(
        Enum(ClientStatus), default=ClientStatus.prospect, nullable=False, index=True
    )
    nda_signed: Mapped[bool] = mapped_column(Boolean, default=False)
    contract_type: Mapped[Optional[str]] = mapped_column(
        String(100)
    )  # np. "ramowa", "jednorazowa"

    notes: Mapped[Optional[str]] = mapped_column(Text)

    # Relationships
    jobs = relationship("Job", back_populates="client")
    contracts = relationship("Contract", back_populates="client")

    def __repr__(self) -> str:
        return f"<Client id={self.id} name={self.name}>"
