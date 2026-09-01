"""Plakietki ostrzeżeń przy osobie — zapis OCENY PRACOWNIKA widoczny zespołowi.

DynaReporter renderuje pod nazwiskiem czerwoną plakietkę „Słabe wyniki"
i bursztynową „Procedury", każdą z wolnym komentarzem („Skonsultuj się
z managerem. Za mała ilość weryfikacji."). NEXUS nie miał tego modelu w ogóle
(`grep warning_banner backend/` = 0 trafień).

To NIE jest zwykły słownik statusów. Wiersz w tej tabeli mówi imiennie
„ta osoba pracuje źle" i jest widoczny dla KAŻDEJ zalogowanej roli (decyzja
D7). Trzy konsekwencje wpisane wprost w schemat:

1. **Flagi się NIE KASUJE, tylko WYGASZA.** Nie ma ścieżki DELETE. Zdjęcie
   ostrzeżenia zostawia wiersz z `cleared_at` i `cleared_by`, bo pytanie „kto
   i kiedy postawił tę ocenę, i kto ją zdjął" musi mieć odpowiedź także pół
   roku później — przy rozmowie rocznej, przy sporze, przy odejściu. Skasowany
   wiersz odpowiada „nikt nigdy", i to jest odpowiedź nieprawdziwa.

2. **Autor jest obowiązkowy przy zapisie.** Anonimowa negatywna ocena widoczna
   całemu zespołowi jest nie do obrony. Kolumna jest NULLABLE wyłącznie dlatego,
   że FK ma `ON DELETE SET NULL` — usunięcie konta autora nie może skasować
   oceny ani wywrócić `DELETE FROM users`. Ginie atrybucja, nie treść. API
   zawsze stempluje `created_by` (nie da się zapisać flagi bez zalogowanego
   admina), więc NULL w tej kolumnie znaczy dokładnie „konto autora zniknęło".

3. **„Były pracownik" to NIE jest flaga.** Ten chip wyprowadza się z
   `User.is_active` i nie ma tu własnego typu. Zapisanie faktu odejścia jako
   „ostrzeżenia" wrzuciłoby zdarzenie kadrowe do jednego worka z oceną jakości
   pracy — a wtedy zdjęcie ostrzeżenia „przywracałoby" kogoś do pracy.

Opis plakietki („Bardzo słabe wyniki, wymagana nagła poprawa") jest STAŁY dla
typu i mieszka w kodzie (`app/api/insights_performance_flags.py`), nie w bazie.
W bazie jest tylko to, co człowiek napisał sam: `note`.
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class PerformanceFlagType(str, Enum):
    """Zamknięty katalog ostrzeżeń — lustro CHECK-a w migracji 0258.

    Katalog jest zamknięty świadomie: każdy typ ma stałą, uzgodnioną treść
    („co ta plakietka znaczy"), więc dorzucenie wartości to decyzja produktowa
    z tekstem do napisania, a nie wpis w słowniku.
    """

    weak_results = "weak_results"
    procedures = "procedures"


# Lustro dla CHECK-a i dla walidacji — jedna lista, żeby dodanie typu
# nie zostawiło rozjazdu między kodem a bazą.
PERFORMANCE_FLAG_TYPES: tuple[str, ...] = tuple(t.value for t in PerformanceFlagType)


class UserPerformanceFlag(Base):
    """Jedno ostrzeżenie przypięte do jednej osoby."""

    __tablename__ = "user_performance_flags"
    __table_args__ = (
        CheckConstraint(
            "flag_type IN ('weak_results', 'procedures')",
            name="ck_user_performance_flags_type",
        ),
        # Spójność wygaszenia wymuszona w BAZIE, nie tylko w API. Wiersz
        # „aktywny, ale z datą zdjęcia" renderowałby ostrzeżenie, które ktoś
        # już zdjął; wiersz „nieaktywny bez daty" gubi odpowiedź na „kiedy".
        # Oba stany są niereprezentowalne.
        #
        # `cleared_by` NIE jest tu wymagane przy wygaszeniu — FK ma
        # `ON DELETE SET NULL`, więc usunięcie konta osoby zdejmującej
        # wywróciłoby taki warunek i zablokowało kasowanie użytkownika.
        CheckConstraint(
            "(is_active AND cleared_at IS NULL AND cleared_by IS NULL)"
            " OR (NOT is_active AND cleared_at IS NOT NULL)",
            name="ck_user_performance_flags_clear_coherence",
        ),
        # Indeksy deklarowane WPROST, dokładnie tak jak tworzy je migracja 0258
        # — `index=True` na kolumnie dałoby inny zestaw niż migracja i taki
        # rozjazd łapie `test_schema_drift_report`.
        Index("ix_user_performance_flags_user_id", "user_id"),
        Index("ix_user_performance_flags_active", "user_id", "is_active"),
        # Jedna AKTYWNA flaga danego typu na osobę. Bez tego drugi zapis tego
        # samego typu renderuje tę samą plakietkę dwa razy, z dwoma różnymi
        # komentarzami — a intencją zapisu „jeszcze raz" jest poprawienie
        # komentarza, nie dołożenie bliźniaczego ostrzeżenia. Warunkowy, bo
        # wygaszonych flag tego samego typu może być w historii wiele.
        Index(
            "uq_user_performance_flags_active_type",
            "user_id",
            "flag_type",
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    flag_type: Mapped[str] = mapped_column(String(32), nullable=False)

    # Wolny komentarz autora — jedyna treść, której nie da się odtworzyć
    # z typu. Opcjonalny: sama plakietka bywa całą wiadomością.
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )

    # `SET NULL`, nie `CASCADE`: odejście autora nie może skasować oceny,
    # którą postawił. Patrz punkt 2 w docstringu modułu.
    created_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    cleared_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cleared_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
