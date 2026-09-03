"""Historia zmian karty klienta (migracja 0272).

Jeden wiersz na zapis zmieniający treść: diff pól, kto, kiedy.
``playbook_version`` wiąże zdarzenie z numerem wersji karty. FK po
``client_id``, nie po ``client_playbooks.id`` — historia przeżywa usunięcie
i ponowne założenie karty; kasuje ją dopiero usunięcie klienta (CASCADE).
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ClientPlaybookEvent(Base):
    __tablename__ = "client_playbook_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    playbook_version: Mapped[int] = mapped_column(Integer, nullable=False)
    # saved (MVP: jedyna akcja; bez delete/copy)
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
