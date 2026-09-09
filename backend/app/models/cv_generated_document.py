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

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, LargeBinary
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
    # Klient, pod którego CV powstało. W trybie "new" wynika z `jobs.client_id`,
    # ale trzymamy go WPROST, bo tryb "upload" (99,9% ruchu) nie ma joba —
    # bez tej kolumny nie dałoby się ani zastosować reguł klienta, ani później
    # odpowiedzieć na pytanie, ile CV poszło pod kogo.
    client_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("clients.id", ondelete="SET NULL"), nullable=True, index=True
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
    docx_content: Mapped[Optional[bytes]] = mapped_column(LargeBinary, nullable=True)
    docx_sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # Uwagi Claude + seatbelt (fabrykacja / nakładające się daty). Wcześniej
    # wracały nagłówkiem X-Generator-Warnings; przy generacji w tle nie ma już
    # inline-response, więc utrwalamy je tu, by lista mogła je pokazać po fakcie.
    warnings: Mapped[Optional[list]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=True
    )
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # Wersja reguły CV klienta (`client_cv_rules.version`), z którą powstał
    # ten dokument (migracja 0267). NULL = bez reguły albo wiersz sprzed
    # stempla. To jest odpowiedź na „którą regułą powstało CV, na które
    # klient się skarży" — bez niej historia zmian reguły nic nie wyjaśnia.
    client_rule_version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # ── Interaktywna wersja CV (kafelki wymagań na publicznym linku) ────────
    # Mapa „wymaganie → dowody z doświadczenia" generowana JEDNYM dodatkowym
    # wywołaniem Claude tuż po udanej generacji (tylko mode="new" — upload nie
    # ma joba, więc nie ma wymagań). Kształt: {"items": [{"requirement", "kind"
    # (must|nice), "status" (met|partial|no_data), "evidence": [{
    # "experience_index", "quote"}]}]}. NULL = kafelki niedostępne (link nadal
    # działa w widoku classic). Cytaty są walidowane jako substring publicznego
    # payloadu, więc do klienta nie trafia nic spoza treści samego CV.
    requirement_map: Mapped[Optional[dict]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=True
    )
    # Cache-key regeneracji: sha256(prompt_version + model + payload + wymagania).
    requirement_map_input_hash: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    requirement_map_model: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    requirement_map_generated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        return f"<CvGeneratedDocument id={self.id} name={self.candidate_name!r}>"
