"""Kampania rekrutacyjna — cel netto na oknie czasu, liczony przy odczycie.

DynaReporter renderował baner kampanii („Wakacyjna integracja…", 1 lipca –
30 września 2026, cel +60 kontraktorów netto) z liczb wpisywanych ręcznie.
NEXUS nie ma pojęcia kampanii w ogóle — ta tabela je wprowadza.

CO TU TRAFIA, A CO NIE
----------------------
Wyłącznie DEFINICJA kampanii: nazwa, emoji, okno i cel. Liczniki
(``placements``, ``resignations``, ``net``) są LICZONE przy odczycie
z ``analytics_first_milestones`` i z ``contracts`` — nigdy przechowywane.

Przechowana liczba przestaje być prawdą w chwili, w której ktoś przesunie
etap albo zakończy kontrakt wstecz, a nic w systemie tego nie zauważy:
baner pokazywałby wtedy „30 / 60" pod nagłówkiem kampanii, w której naprawdę
jest 27 — i nie byłoby żadnego błędu do zdiagnozowania. Ta sama zasada, która
każe liczyć placement z widoku, a nie trzymać go w kolumnie.

DLACZEGO ``is_active`` JEST FLAGĄ, A NIE WYNIKIEM PORÓWNANIA DAT
----------------------------------------------------------------
Data zakończenia kampanii nie jest momentem, w którym przestaje ona kogokolwiek
obchodzić — pierwszego dnia po zamknięciu wynik interesuje najbardziej. Gdyby
widoczność banera wynikała z dat, ekran gasłby dokładnie wtedy, gdy ludzie
przychodzą po wynik. Flagą steruje operator: kampania gaśnie, kiedy on tak
zdecyduje, a nie kiedy minie północ.
"""

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class RecruitmentCampaign(Base):
    """Jedna kampania: okno, cel netto i przełącznik widoczności banera."""

    __tablename__ = "recruitment_campaigns"
    __table_args__ = (
        # Indeks deklarowany WPROST, dokładnie tak jak tworzy go migracja 0259.
        # `index=True` na kolumnie dałoby indeks o innej nazwie i `dryf`
        # wychodziłby w `test_schema_drift_report` — model i migracja muszą
        # mówić to samo.
        Index("ix_recruitment_campaigns_active", "is_active", "start_date"),
        # Okno odwrócone daje pusty przedział, więc baner pokazałby „0 z N"
        # i „0 dni do końca" — liczby poprawne arytmetycznie, opisujące
        # nieistniejącą kampanię.
        CheckConstraint(
            "end_date >= start_date",
            name="ck_recruitment_campaigns_window",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Emoji jest OPCJONALNE i celowo `String`, nie osobna tabela ikon: baner
    # ma jedną ozdobę, a brak emoji nie może blokować założenia kampanii.
    # 16 znaków, bo emoji złożone (ZWJ, modyfikatory koloru skóry) potrafią
    # zająć kilka punktów kodowych — limit 1-2 obciąłby je w połowie sekwencji.
    emoji: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    # Cel NETTO (placementy − rezygnacje). `Integer`, bo cel jest liczbą osób.
    # `server_default` obok `default`, tak jak `is_active` niżej: bez niego
    # tabela założona awaryjnie przez `Base.metadata.create_all` nie dostanie
    # `DEFAULT 0`, więc INSERT pomijający kolumnę odbije się od `NOT NULL`.
    # `test_schema_drift_report` tego nie złapie — raport porównuje tabele,
    # kolumny, nullability, enumy, indeksy i FK, ale NIE defaulty.
    target_net: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # `SET NULL`, nie `CASCADE`: usunięcie konta autora nie może skasować
    # trwającej kampanii. Ginie wyłącznie atrybucja.
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
