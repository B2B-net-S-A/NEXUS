"""Log wygenerowanych CV B2B — lista „Wygenerowane CV" w panelu Generatora.

Każda udana generacja (New i Old mode) zapisuje tu wiersz z ``render_payload``
(= ``candidate_data`` z pipeline'u). Pozwala to odtworzyć i pobrać/podejrzeć
DOCX ponownie z poziomu panelu BEZ ponownego (płatnego) wywołania Claude —
render jest deterministyczny. Wzorzec 1:1 jak ``B2BGeneratedContract`` (#501).

Dzięki temu wynik nie ginie w folderze „Pobrane": rekruter generuje kilka CV
pod rząd, przegląda innych kandydatów, a wygenerowane dokumenty zostają na
liście (opisane kandydatem + kto + kiedy), zamiast lądować jako bezimienne
pliki w „Pobranych".
"""

from typing import Optional

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin


class CvGeneratedDocument(Base, TimestampMixin):
    __tablename__ = "cv_generated_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    # New mode → realny kandydat/rekrutacja; Old mode (upload) → NULL.
    candidate_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("candidates.id", ondelete="SET NULL"), nullable=True, index=True
    )
    job_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True
    )
    # Zdenormalizowane do listy (działa też dla Old mode bez kandydata w DB).
    candidate_name: Mapped[str] = mapped_column(String(300), nullable=False)
    position: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    language: Mapped[str] = mapped_column(String(2), default="pl", nullable=False)
    blind: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # UWAGA: `mode` to ścieżka generacji ("new" = z profilu kandydata /
    # "upload" = z wgranych plików) — NIE tryb obróbki treści. Ten drugi
    # siedzi w `content_mode` niżej; pomylenie ich zepsułoby badge "Upload"
    # na liście wygenerowanych CV.
    mode: Mapped[str] = mapped_column(String(10), default="new", nullable=False)
    # Ile obróbki prezentacyjnej zastosowano: "basic" | "polished" | "tailored".
    # Zapisywane przy każdej generacji, żeby przy sporze z klientem dało się
    # wykazać, którym trybem powstał konkretny wysłany dokument.
    # server_default="tailored" jest prawdziwościowym backfillem historii —
    # wiersze sprzed tej funkcji powstały z pełnym pozycjonowaniem pod ofertę.
    content_mode: Mapped[str] = mapped_column(
        String(16), server_default="tailored", default="polished", nullable=False
    )
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    # Async-generation status. Generacja leci w tle (BackgroundTasks), więc wynik
    # nie ginie gdy rekruter zamknie kartę w trakcie tych 60-90 s:
    #   * "processing" — zadanie w toku (render_payload jeszcze NULL),
    #   * "ready"      — gotowe, DOCX odtwarzalny z render_payload,
    #   * "failed"     — błąd generacji (powód w error_message).
    # Wiersze sprzed async-generacji były zawsze ukończone → server_default "ready".
    status: Mapped[str] = mapped_column(
        String(20), default="ready", server_default="ready", nullable=False, index=True
    )
    # Powód niepowodzenia (StandaloneGenerationError.message) gdy status="failed".
    error_message: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    # candidate_data do ponownego renderu DOCX. NULL = wiersz sprzed tej funkcji
    # LUB nadal "processing"/"failed" → re-download niedostępny. JSON+wariant
    # JSONB, by tabela tworzyła się też na SQLite w testach.
    render_payload: Mapped[Optional[dict]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=True
    )
    # Uwagi Claude + seatbelt (fabrykacja / nakładające się daty). Wcześniej
    # wracały nagłówkiem X-Generator-Warnings; przy generacji w tle nie ma już
    # inline-response, więc utrwalamy je tu, by lista mogła je pokazać po fakcie.
    warnings: Mapped[Optional[list]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=True
    )
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    def __repr__(self) -> str:
        return f"<CvGeneratedDocument id={self.id} name={self.candidate_name!r}>"
