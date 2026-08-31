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
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
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

    # Standardy „dla człowieka": SLA, off-limit, limity rekomendacji, dokumenty
    # onboardingowe. Świadomie NIE trafiają do promptu modelu — „kandydatów
    # z doświadczeniem w bankowości rozważamy w pierwszej kolejności" to reguła
    # SZUKANIA, a w prompcie generatora byłaby zaproszeniem do koloryzowania
    # doświadczenia bankowego.
    notes: Mapped[Optional[str]] = mapped_column(Text)

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
