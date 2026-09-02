"""CV próbne dla reguły klienta (migracja 0267).

Delivery Lead widzi skutek reguły ZANIM rekruter cokolwiek wyśle: ten sam
kandydat i ta sama rekrutacja wygenerowane z regułą i bez niej, obok siebie.
Dwie generacje to 2-3 minuty — dłużej niż limit proxy na jedno żądanie —
więc podgląd jest liczony w tle, a interfejs odpytuje wiersz po ``id``.

Świadomie OSOBNA tabela, nie ``cv_generated_documents`` z flagą: podgląd nie
jest dokumentem do wysłania, nie ma pliku ani udostępniania, a na liście
„Wygenerowane CV" mieszałby się z realnymi generacjami.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ClientCvRulePreview(Base):
    __tablename__ = "client_cv_rule_previews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # CASCADE, nie SET NULL: wiersz niesie pełny `render_payload` kandydata
    # (nazwisko, pracodawcy, daty). Podgląd to artefakt jednorazowy — nie ma
    # powodu, żeby przeżył usunięcie osoby (RODO), w odróżnieniu od
    # `cv_generated_documents`, które są dokumentami wysłanymi klientowi.
    candidate_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), nullable=True
    )
    stage_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    language: Mapped[str] = mapped_column(
        String(2), nullable=False, default="pl", server_default="pl"
    )
    # processing | ready | failed
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="processing", server_default="processing"
    )
    # {"payload": candidate_data, "warnings": [...], "filename": ...}
    with_rule: Mapped[Optional[dict]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=True
    )
    without_rule: Mapped[Optional[dict]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=True
    )
    # Dokładny blok reguł, jaki dostał model — bez tajemnic.
    prompt_block: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
