"""Dedup maila potwierdzenia aplikacji (0358).

Jeden wiersz na (HMAC adresu, klucz linku); ``sent_at`` = ostatnia wysyłka.
Kolejny mail do tej samej pary dopiero po 24 h
(``services/application_confirmation_email.claim_send``). Bez jawnego
e-maila i bez kluczy obcych — wpisy starsze niż dwie doby są sprzątane przy
każdym zapisie, więc tabela nie trzyma niczego dłużej niż okno dedupu.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ApplicationConfirmationSend(Base):
    __tablename__ = "application_confirmation_sends"
    __table_args__ = (
        UniqueConstraint(
            "email_key", "link_key", name="uq_application_confirmation_sends_pair"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email_key: Mapped[str] = mapped_column(String(64), nullable=False)
    link_key: Mapped[str] = mapped_column(String(64), nullable=False)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
