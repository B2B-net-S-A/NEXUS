"""Dni robocze użytkownika w oknie czasu — mianownik wskaźników „na dzień".

Do 2026-08-31 Power Calling dzielił tygodniową liczbę weryfikacji przez stałą
``5`` i publikował imienną listę „poniżej progu" — więc osoba na urlopie
lądowała na niej pod nazwiskiem. NEXUS nie zna nieobecności; ta tabela je
przechowuje, zaciągane z COMPASSA (decyzja D5).

CO TU TRAFIA, A CO NIE
----------------------
Wyłącznie LICZBY DNI. Nigdy typ nieobecności ani notatka: ``leave_type``
w COMPASSIE przyjmuje ``sick_leave`` i ``parental_leave`` (dane o zdrowiu),
a pole ``note`` zawiera w produkcji wolny tekst medyczny. Kontrakt jest
wymuszony po obu stronach — endpoint eksportu w COMPASSIE też ich nie oddaje.

DLACZEGO „dni robocze minus urlop", A NIE „dni przepracowane"
-------------------------------------------------------------
Chorobowe dla B2B jest w COMPASSIE strukturalnie niezapisywalne (trigger
Phase 29), a rekruterzy są w większości B2B. Kolumna ``basis`` niesie tę
prawdę do UI, żeby kafel podpisał liczbę tym, czym ona jest. Podpisanie jej
jako „dni przepracowane" odtworzyłoby defekt, który D5 naprawia — tylko
z ładniejszym mianownikiem.
"""

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class UserWorkdayPeriod(Base):
    """Dni robocze i nieobecności jednej osoby w jednym oknie czasu."""

    __tablename__ = "user_workday_periods"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "period_start", "period_end", name="uq_user_workday_period"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Okno DOMKNIĘTE [start, end] — tak, jak zwraca je COMPASS. Świadomie NIE
    # sam miesiąc: Power Calling raportuje TYDZIEŃ ISO, a wskaźniki MD miesiąc,
    # więc jedna tabela musi udźwignąć obie granulacje. Przybliżanie tygodnia
    # z miesięcznej średniej byłoby zgadywaniem — czyli tym samym defektem
    # co dzielenie przez sztywne 5, tylko z ładniejszym mianownikiem.
    period_start: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    period_end: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    business_days: Mapped[int] = mapped_column(Integer, nullable=False)
    # NUMERIC, nie INTEGER: COMPASS dopuszcza pół dnia urlopu (`half_day`),
    # więc zaokrąglenie do liczby całkowitej cicho gubiłoby połówki.
    absence_days: Mapped[float] = mapped_column(Numeric(5, 1), nullable=False)
    working_days: Mapped[float] = mapped_column(Numeric(5, 1), nullable=False)

    # Czym ta liczba JEST — jedzie do UI razem z nią.
    basis: Mapped[str] = mapped_column(
        String(64), nullable=False, default="business_days_minus_approved_leave"
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="compass")
    synced_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
