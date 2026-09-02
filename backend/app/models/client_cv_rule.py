"""Reguły CV per klient — nazwa pliku, język, dodatki wymagane przez klienta.

Źródłem tych reguł są szablony „Profil Championa" trzymane w Pomocy
(``help_materials``, kategoria „Profile Championa — per klient", migracja
``0219``). Każdy z nich ma sekcję „7. STANDARDY REKRUTACJI KLIENTA" mówiącą
wprost, jak ma się nazywać plik CV i w jakim ma być języku — a generator CV
do tej pory nie wiedział o tym nic i składał jedną, globalną nazwę
``{rola}_{imię nazwisko}.docx``, niezgodną z żadnym z 14 wymagań.

**Treść reguł jest wpisywana ręcznie, nie parsowana z DOCX-a.** Sekcja 7 to
wolny tekst mieszający reguły CV z delegacjami i adresami biur; u Credit
Agricole w ogóle nie istnieje (standardy siedzą w sekcji 6), a szablon PFRON-u
niesie błąd copy-paste z Nordei. Parser oparty na numerze nagłówka nie
znalazłby tego pierwszego i utrwalił drugi — po cichu, w obie strony.

``confirmed_at IS NULL`` znaczy **propozycja, która NIE obowiązuje**. Migracja
zasiewa 14 reguł, ale dopasowanie szablonu do wiersza w ``clients`` nie jest
1:1 (samych bytów „BNP" jest w bazie siedem), więc zasiane reguły czekają na
zatwierdzenie przez człowieka. To jest cały mechanizm „ekranu weryfikacji" —
jedna kolumna nullable zamiast osobnego stanu.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin


class ClientCvRule(Base, TimestampMixin):
    """Jedna reguła na klienta (1:1, wymuszone UNIQUE na ``client_id``)."""

    __tablename__ = "client_cv_rules"
    __table_args__ = (
        CheckConstraint(
            "cv_language IS NULL OR cv_language IN ('pl', 'en')",
            name="ck_client_cv_rules_language",
        ),
        CheckConstraint(
            "content_mode IS NULL OR content_mode IN ('basic', 'polished', 'tailored')",
            name="ck_client_cv_rules_content_mode",
        ),
        CheckConstraint(
            "date_format IS NULL OR date_format IN "
            "('MM.YYYY', 'MM/YYYY', 'YYYY-MM', 'YYYY')",
            name="ck_client_cv_rules_date_format",
        ),
        CheckConstraint(
            "(max_roles IS NULL OR max_roles > 0) AND "
            "(max_bullets_per_role IS NULL OR max_bullets_per_role > 0) AND "
            "(max_bullet_chars IS NULL OR max_bullet_chars >= 40) AND "
            "(why_points_max IS NULL OR why_points_max > 0) AND "
            "(require_screening_notes_min_chars IS NULL "
            "OR require_screening_notes_min_chars >= 0)",
            name="ck_client_cv_rules_limits_positive",
        ),
        # Świadomie BEZ więzu „confirmed_at i confirmed_by naraz albo wcale":
        # `confirmed_by` ma ON DELETE SET NULL, więc usunięcie konta osoby,
        # która regułę zatwierdziła, zerwałoby taki CHECK i zablokowało DELETE
        # użytkownika. Autorstwo zatwierdzenia może wyblaknąć; sam fakt
        # zatwierdzenia (`confirmed_at`) jest tym, co steruje runtime'em.
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    # Wzór nazwy pliku z tokenami {STANOWISKO} {IMIE_NAZWISKO} {PROJEKT} {DATA}.
    # NULL = ten klient nie ma własnego wzoru → globalny fallback generatora.
    filename_pattern: Mapped[Optional[str]] = mapped_column(String(300))

    # Czy spacje WEWNĄTRZ podstawionej wartości zamieniamy na "_". Razem
    # z czterema tokenami wyżej ta jedna flaga pokrywa wszystkie 14 wzorów:
    # „Jan Kowalski" → „Jan_Kowalski" daje `Imię_Nazwisko` bez potrzeby
    # osobnych tokenów na imię i nazwisko.
    spaces_to_underscores: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    # Wymuszony język CV ("pl" | "en"). NULL = klient nie stawia wymogu i
    # decyduje rekruter. Nordea jest jedynym klientem wymagającym wyłącznie EN,
    # więc dla niej domyślne "pl" generatora było zawsze złym wyborem.
    cv_language: Mapped[Optional[str]] = mapped_column(String(8))

    # Klient oczekuje OBU wersji językowych (ALIOR, BIK, BNP, SANTANDER).
    # Świadomie nie uruchamia drugiej generacji automatycznie — to najdroższe
    # wywołanie modelu w produkcie. Zamiast tego rekruter dostaje przypomnienie.
    requires_en_copy: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    # Klient wymaga bloku ze zgodą kandydata na przetwarzanie danych na końcu
    # dokumentu (dziś wyłącznie PKO BP). To jedyny standard z 14, który zmienia
    # ZAWARTOŚĆ pliku, a nie tylko jego nazwę czy język.
    requires_rodo_consent_block: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    # Notatka DL o standardach klienta: SLA, off-limit, limity rekomendacji,
    # co klient ceni. Widzi ją rekruter w generatorze, a od 02.09.2026
    # (decyzja Artura) TAKŻE model — w osobnym bloku `<client_notes>` pod tą
    # samą granicą co instrukcje: kontekst do doboru akcentów wśród faktów
    # ze źródła, nigdy nowe fakty („klient ceni bankowość" = pokaż bankowe
    # projekty wyżej, jeśli są; nie: napisz, że są).
    notes: Mapped[Optional[str]] = mapped_column(Text)

    # Instrukcje dla generatora AI (migracja 0266) — jedyne pole reguły, które
    # TRAFIA do promptu. Wolny tekst Delivery Leada o PREZENTACJI: co pominąć,
    # co wyeksponować, jak długo, jakim stylem. Prompt systemowy ogranicza ich
    # moc do doboru i formy faktów już obecnych w źródle — polecenie, które
    # wymagałoby dopisania technologii, obowiązku, lat czy certyfikatu, model
    # ignoruje i zgłasza w ``warnings``. Idą w wiadomości użytkownika, nie
    # w systemowym prompcie (ten jest cache'owany i musi zostać statyczny).
    generator_instructions: Mapped[Optional[str]] = mapped_column(Text)

    # Wariant instrukcji dla CV angielskiego (migracja 0267). Pusty = dla EN
    # idzie treść podstawowa. Klienci z „obiema wersjami" bywają precyzyjni
    # co do angielskiego nazewnictwa ról, a jedna treść w dwóch językach
    # zmuszała DL do pisania po polsku o angielskim dokumencie.
    generator_instructions_en: Mapped[Optional[str]] = mapped_column(Text)

    # ── Blokady (migracja 0267): rekruter przestaje wybierać ──────────────
    # Tryb obróbki treści: NULL = wolny wybór rekrutera (w granicach sufitu
    # `Client.cv_content_mode_cap`); wartość + `content_mode_locked=false` =
    # domyślnie zaznaczony, rekruter może zmienić; wartość + locked = zawsze
    # ten tryb, serwer NADPISUJE żądanie. Wartość może być tylko trybem
    # z katalogu (CHECK), sufit z karty klienta nadal wygrywa z blokadą.
    content_mode: Mapped[Optional[str]] = mapped_column(String(16))
    content_mode_locked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # Wymagane wejścia — brak blokuje generację czytelnym 422 PRZED
    # naliczeniem kwoty (ten sam wzorzec co zrzut zgody u PKO BP). Minimalna
    # długość notatek: NULL/0 = bez wymogu. Reszta to flagi.
    require_screening_notes_min_chars: Mapped[Optional[int]] = mapped_column(Integer)
    require_project_ref: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    require_position: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    require_champion: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # Druga wersja językowa generowana AUTOMATYCZNIE po pierwszej (tylko gdy
    # `requires_en_copy` i bez wymuszonego języka). Druga generacja to drugie
    # wywołanie najdroższego modelu w produkcie — dlatego decyzja DL, nie
    # domyślne zachowanie.
    auto_second_language: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    # ── Polityka prezentacji egzekwowana w kodzie (migracja 0267) ────────
    # Klocki, które renderer domyka deterministycznie PO odpowiedzi modelu.
    # Model dostaje je też jako instrukcje, ale prośba nie jest gwarancją —
    # a „maks. 3 punkty" wypełnione czterema wygląda dla klienta jak
    # zignorowane wymaganie. Sekcje: education | certifications | languages
    # | skills. Słownik: lista {"from": ..., "to": ...} stosowana do
    # słownictwa całymi słowami, bez zmiany faktów.
    omit_sections: Mapped[Optional[list]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql")
    )
    max_roles: Mapped[Optional[int]] = mapped_column(Integer)
    max_bullets_per_role: Mapped[Optional[int]] = mapped_column(Integer)
    max_bullet_chars: Mapped[Optional[int]] = mapped_column(Integer)
    why_points_max: Mapped[Optional[int]] = mapped_column(Integer)
    date_format: Mapped[Optional[str]] = mapped_column(String(16))
    glossary: Mapped[Optional[list]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql")
    )

    # Numer wersji bumpowany przy KAŻDYM zapisie zmieniającym treść reguły.
    # Stemplowany na wygenerowanym CV (`cv_generated_documents.
    # client_rule_version`) — bez tego nie da się odpowiedzieć, którą wersją
    # reguły powstał dokument, na który klient się skarży.
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )

    # Slug szablonu z ``help_materials``, z którego regułę zasiano. Pozwala
    # ekranowi weryfikacji pokazać link do dokumentu źródłowego bez dokładania
    # ``client_id`` do ``help_materials``.
    seed_key: Mapped[Optional[str]] = mapped_column(String(64), index=True)

    # NULL = propozycja z seeda; runtime takiej reguły NIE stosuje.
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), index=True
    )
    confirmed_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    client = relationship("Client")
    confirmed_by_user = relationship("User", foreign_keys=[confirmed_by])

    @property
    def is_active(self) -> bool:
        """Czy reguła obowiązuje (została zatwierdzona przez człowieka)."""
        return self.confirmed_at is not None

    def __repr__(self) -> str:
        state = "active" if self.is_active else "proposed"
        return f"<ClientCvRule client_id={self.client_id} {state}>"
