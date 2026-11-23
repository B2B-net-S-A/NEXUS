"""Sesja zdalnego podpisu przez API CSC (0759, E1, kierunek K1 z 22.11.2026).

Jedna sesja = jedno zatwierdzenie u dostawcy usług zaufania: kontraktor
podpisuje umowę i wybrane dokumenty paczki jednego wniosku, reprezentant
B2Bnetwork umowy kilku wniosków. Sesja wiąże ``state`` z przekierowania OAuth
(w bazie tylko skrót SHA-256), żyje ``remote.SESSION_MINUTES`` minut i działa
raz. Kod autoryzacji i token dostępu dostawcy nie trafiają do bazy.

Stany: ``waiting_for_user`` → ``signing`` → ``done`` / ``failed``; z pierwszego
także ``cancelled`` (rezygnacja u dostawcy albo koniec czasu). Wniosek
o podpis zmienia się tylko w ``done``. DDL: ``services/b2b_esign/remote_schema.py``.
"""

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin


class B2BEsignRemoteSession(Base, TimestampMixin):
    __tablename__ = "b2b_esign_remote_sessions"
    __table_args__ = (
        CheckConstraint(
            "party IN ('contractor', 'company')",
            name="ck_b2b_esign_remote_sessions_party",
        ),
        CheckConstraint(
            "status IN ('waiting_for_user', 'signing', 'done', 'failed', 'cancelled')",
            name="ck_b2b_esign_remote_sessions_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Identyfikator w API i w adresie powrotu (``?remote=…``), nie ``state``.
    public_id: Mapped[str] = mapped_column(String(43), nullable=False, unique=True)
    # ``contractor`` (link z maila) albo ``company`` (reprezentant w NEXUSIE).
    party: Mapped[str] = mapped_column(String(16), nullable=False)
    request_ids: Mapped[list[int]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # Dokumenty paczki podpisywane obok umowy (tylko kontraktor).
    document_ids: Mapped[list[int]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # ``own_certificate`` albo ``one_time`` — wybór kontraktora.
    method: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    # Reprezentant, który rozpoczął sesję (tylko ``company``).
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    state_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    # PKCE (RFC 7636): potrzebny tylko przy wymianie kodu, potem kasowany.
    code_verifier: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    # Token linku kontraktora zaszyfrowany kluczem z ``state`` — potrzebny
    # tylko do adresu powrotu; kasowany przy powrocie i po czasie sesji.
    sealed_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="waiting_for_user"
    )
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    done_request_ids: Mapped[list[int]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # Ślad podpisu bez sekretów: dostawca, credentialID, certyfikat, liczba plików.
    evidence: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    callback_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
