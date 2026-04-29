"""Macierze organizacyjne zespołu rekrutacji.

Ported pattern z InfraReportera (dynareporter) — 3 tabele przypisań:
  - TacDeliveryLeadAssignment: TAC → DL (1:1)
  - TacLinkedInFarming: TAC × kategoria kompetencji (M:N) — którą kategorię
    TAC „farmuje" na LinkedIn (organizacyjnie, bez metryki wiadomości)
  - DeliveryLeadClientAssignment: DL × klient (M:N) z flagą `is_head`
    (główny vs wspierający opiekun klienta)

Sourcer → kategoria kompetencji (z priorytetem 1/2) jest rozszerzeniem
istniejącej tabeli `user_competence_categories` o kolumnę `priority` —
nie nową tabelą (DRY).
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class TacDeliveryLeadAssignment(Base):
    """Przypisanie TAC do Delivery Leada. Jeden TAC → jeden DL."""

    __tablename__ = "tac_delivery_lead_assignments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tac_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    delivery_lead_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
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

    tac = relationship("User", foreign_keys=[tac_user_id])
    delivery_lead = relationship("User", foreign_keys=[delivery_lead_user_id])

    def __repr__(self) -> str:
        return (
            f"<TacDeliveryLeadAssignment tac={self.tac_user_id} "
            f"dl={self.delivery_lead_user_id}>"
        )


class TacLinkedInFarming(Base):
    """TAC × kategoria kompetencji — którą farmuje na LinkedIn (organizacja)."""

    __tablename__ = "tac_linkedin_farming"
    __table_args__ = (
        UniqueConstraint(
            "tac_user_id", "competence_category_id", name="uq_tac_linkedin_farming"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tac_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    competence_category_id: Mapped[int] = mapped_column(
        ForeignKey("competence_categories.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    tac = relationship("User", foreign_keys=[tac_user_id])
    competence_category = relationship("CompetenceCategory")

    def __repr__(self) -> str:
        return (
            f"<TacLinkedInFarming tac={self.tac_user_id} "
            f"cc={self.competence_category_id}>"
        )


class DeliveryLeadClientAssignment(Base):
    """DL × klient. `is_head=True` = główny opiekun (max 1 per klient)."""

    __tablename__ = "delivery_lead_client_assignments"
    __table_args__ = (
        UniqueConstraint("delivery_lead_user_id", "client_id", name="uq_dl_client"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    delivery_lead_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    is_head: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    delivery_lead = relationship("User", foreign_keys=[delivery_lead_user_id])
    client = relationship("Client", foreign_keys=[client_id])

    def __repr__(self) -> str:
        return (
            f"<DeliveryLeadClientAssignment dl={self.delivery_lead_user_id} "
            f"client={self.client_id} head={self.is_head}>"
        )


class ClientTacAssignment(Base):
    """TAC × klient. `is_primary=True` = główny opiekun (max 1/klient).

    Enforcement max-1-primary: partial unique index `uq_client_primary_tac`
    na `(client_id) WHERE is_primary = TRUE` (migracja 0060). API musi
    przed insertem z `is_primary=True` zrobić UPDATE poprzedniego primary
    na `False` — wzorzec `toggle_dl_client_head`.
    """

    __tablename__ = "client_tac_assignments"
    __table_args__ = (
        UniqueConstraint("tac_user_id", "client_id", name="uq_client_tac"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tac_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    tac = relationship("User", foreign_keys=[tac_user_id])
    client = relationship(
        "Client", foreign_keys=[client_id], back_populates="tac_assignments"
    )

    def __repr__(self) -> str:
        return (
            f"<ClientTacAssignment tac={self.tac_user_id} "
            f"client={self.client_id} primary={self.is_primary}>"
        )
