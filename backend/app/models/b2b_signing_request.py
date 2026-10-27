"""Wniosek o podpis umowy B2B w NEXUSIE (0499, decyzja Artura 21.10.2026).

Droga „podpis w NEXUSIE” obok zwykłej (mail i „Oznacz jako podpisaną”).
Jeden wiersz = jedna wysyłka umowy z rejestru Generatora do podpisu
kwalifikowanego obu stron: najpierw kontraktor (link z maila, bez konta),
potem reprezentant B2B Network (w NEXUSIE). Umowa przenosi autorskie prawa
majątkowe (art. 53 pr. aut. — forma pisemna), więc KAŻDY podpis musi być
kwalifikowany; zwykłego ani zaawansowanego ta droga nie zna.

Podpisywany jest PDF zrobiony z TEGO SAMEGO Worda co „Pobierz DOCX”, zamrożony
przy wysyłce (odcisk SHA-256 + długość). Każdy wgrany plik musi zaczynać się
bajtami poprzedniej wersji — podpis kwalifikowany PAdES dokłada się na końcu
pliku, więc zmiana treści albo „zapisz jako nowy PDF” odpada.

Kontrakt NIE powstaje przy wysyłce: dopiero podpis obu stron woła tę samą
automatykę co „Oznacz jako podpisaną” (reguła „jedna droga do kontraktu”).

Stany: ``sent`` → ``contractor_signed`` → ``completed``; z dwóch pierwszych
także ``withdrawn`` (nadawca wycofał / przejście na drogę zwykłą) i ``expired``.
Na wiersz rejestru żyje najwyżej jeden wniosek w toku (indeks częściowy).
"""

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin

SIGNING_STATUSES = (
    "sent",
    "contractor_signed",
    "completed",
    "withdrawn",
    "expired",
)
#: Stany, w których wniosek jeszcze żyje (link albo podpis firmy przed nami).
OPEN_STATUSES = ("sent", "contractor_signed")


class B2BSigningRequest(Base, TimestampMixin):
    __tablename__ = "b2b_signing_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('sent', 'contractor_signed', 'completed', 'withdrawn', 'expired')",
            name="ck_b2b_signing_requests_status",
        ),
        Index(
            "uq_b2b_signing_requests_open_per_row",
            "generated_contract_id",
            unique=True,
            postgresql_where=text("status IN ('sent', 'contractor_signed')"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    generated_contract_id: Mapped[int] = mapped_column(
        ForeignKey("b2b_generated_contracts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="sent")

    # Kontraktor — z karty kandydata, poprawiany w oknie wysyłki (spółka:
    # osoba z KRS). Nazwisko musi się zgadzać z podmiotem certyfikatu.
    contractor_name: Mapped[str] = mapped_column(String(255), nullable=False)
    contractor_email: Mapped[str] = mapped_column(String(255), nullable=False)
    # Skrót SHA-256 jednorazowego tokenu linku — sam token żyje tylko w mailu.
    contractor_token_hash: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, unique=True
    )
    # Nieudane wgrania z linku (zły plik, podpis) — po ``MAX_FAILED_ATTEMPTS``
    # link przestaje przyjmować pliki (każde wgranie to do 30 s walidacji).
    contractor_failed_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    # Reprezentant B2B Network (konto w NEXUSIE) — podpisuje drugi.
    company_signer_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Wersje pliku: wydana do podpisu → po podpisie kontraktora → po obu.
    source_pdf_path: Mapped[str] = mapped_column(String(512), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_size: Mapped[int] = mapped_column(Integer, nullable=False)
    contractor_pdf_path: Mapped[Optional[str]] = mapped_column(
        String(512), nullable=True
    )
    contractor_sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    contractor_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    final_pdf_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    # Raporty walidacji każdego wgrania (``contractor`` / ``company``).
    validation: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)

    sent_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    contractor_signed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    closed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    closed_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    close_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_reminder_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Odcisk danych umowy przy wysyłce (``service.payload_fingerprint``) —
    # „Wyślij nowy link” na tym samym PDF-ie tylko przy niezmienionej umowie.
    source_payload_sha256: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    # Zdarzenia, których nie da się odczytać z pól stanu (0531, 27.10.2026):
    # przedłużenie, nowy link, prośba kontraktora o link, wygaśnięcie
    # i przypomnienie sprzed kolejnego terminu. Wpis: ``{"kind", "at", …}``.
    events: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
