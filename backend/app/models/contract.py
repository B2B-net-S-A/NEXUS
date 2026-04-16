import enum
from datetime import date
from typing import Optional

from sqlalchemy import Date, Enum, ForeignKey, Integer, String, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin


class ContractType(str, enum.Enum):
    b2b = "b2b"
    uop = "uop"  # Umowa o pracę
    uzlecenie = "uzlecenie"  # Umowa zlecenie


class ContractStatus(str, enum.Enum):
    draft = "draft"
    active = "active"
    ending = "ending"  # < 30 dni do końca
    ended = "ended"


class Contract(Base, TimestampMixin):
    """
    Kontrakt body-leasingowy — łączy kandydata z klientem przez ofertę.
    Marża obliczana automatycznie: rate_client - rate_candidate.
    """

    __tablename__ = "contracts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # Strony kontraktu
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id"), nullable=False, index=True
    )
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id"), nullable=False, index=True
    )
    job_id: Mapped[Optional[int]] = mapped_column(ForeignKey("jobs.id"), index=True)

    # Daty
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[Optional[date]] = mapped_column(Date)

    # Stawki finansowe
    rate_candidate: Mapped[Optional[int]] = mapped_column(
        Integer
    )  # stawka dla kandydata (PLN/h lub mies.)
    rate_client: Mapped[Optional[int]] = mapped_column(Integer)  # stawka dla klienta
    currency: Mapped[str] = mapped_column(String(3), default="PLN")

    # Marża — obliczana automatycznie (rate_client - rate_candidate)
    margin: Mapped[Optional[int]] = mapped_column(Integer)

    contract_type: Mapped[ContractType] = mapped_column(
        Enum(ContractType), default=ContractType.b2b, nullable=False
    )

    status: Mapped[ContractStatus] = mapped_column(
        Enum(ContractStatus), default=ContractStatus.draft, nullable=False, index=True
    )

    # Załączniki/dokumenty (lista URL lub metadanych)
    documents: Mapped[Optional[dict]] = mapped_column(JSONB, default=list)

    # Relationships
    candidate = relationship("Candidate", back_populates="contracts")
    client = relationship("Client", back_populates="contracts")
    job = relationship("Job", back_populates="contracts")

    def calculate_margin(self) -> Optional[int]:
        """Oblicz marżę: stawka klienta - stawka kandydata."""
        if self.rate_client is not None and self.rate_candidate is not None:
            return self.rate_client - self.rate_candidate
        return None

    def __repr__(self) -> str:
        return f"<Contract id={self.id} candidate={self.candidate_id} client={self.client_id} status={self.status}>"


@event.listens_for(Contract, "before_insert")
@event.listens_for(Contract, "before_update")
def auto_calculate_margin(mapper, connection, target: Contract):
    """Automatically recalculate margin before save."""
    target.margin = target.calculate_margin()
