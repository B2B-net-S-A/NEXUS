"""Historia zmian reguły CV klienta (migracja 0267).

Jeden wiersz na zdarzenie: zapis (z diffem pól), zatwierdzenie, usunięcie,
skopiowanie z innego klienta. Bez tego reklamacja klienta („CV wyglądało
inaczej niż tydzień temu") kończy się na „ktoś coś zmienił". ``rule_version``
wiąże zdarzenie z numerem wersji stemplowanym na wygenerowanych CV.

Wiersze nie są kasowane razem z regułą — FK idzie po ``client_id``, nie po
``client_cv_rules.id``, więc usunięcie i ponowne założenie reguły zostawia
historię ciągłą. Kasuje je dopiero usunięcie klienta (CASCADE).
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ClientCvRuleEvent(Base):
    __tablename__ = "client_cv_rule_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rule_version: Mapped[int] = mapped_column(Integer, nullable=False)
    # saved | confirmed | deleted | copied
    action: Mapped[str] = mapped_column(String(24), nullable=False)
    # {"pole": {"from": ..., "to": ...}} — tylko pola, które się zmieniły.
    changes: Mapped[Optional[dict]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=True
    )
    actor_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # Zdenormalizowane — konto może zniknąć, historia nie.
    actor_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
