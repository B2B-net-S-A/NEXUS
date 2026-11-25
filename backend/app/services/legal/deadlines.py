"""Terminy liczy kod, model pisze tylko zdania (decyzja Artura 25.11.2026).

Czyste funkcje według art. 110–116 KC (tekst jednolity Dz. U. 2026 poz. 795):

* art. 111 — termin w dniach kończy się z upływem ostatniego dnia; dnia
  zdarzenia (np. doręczenia) się nie liczy: 14 dni od 3 marca = 17 marca;
* art. 112 — termin w tygodniach, miesiącach, latach kończy się w dniu, który
  nazwą lub datą odpowiada dniowi początkowemu, a gdy takiego dnia w ostatnim
  miesiącu nie ma — w ostatnim dniu miesiąca: 31 stycznia + 1 miesiąc =
  28 (29) lutego;
* art. 113 — początek, środek, koniec miesiąca = 1., 15., ostatni dzień;
  pół miesiąca = 15 dni;
* art. 114 — gdy ciągłość terminu nie jest wymagana, miesiąc = 30 dni,
  rok = 365 dni;
* art. 115 — koniec terminu **do wykonania czynności** w sobotę albo dzień
  ustawowo wolny przesuwa się na najbliższy dzień roboczy. Nie dotyczy dnia,
  w którym umowa przestaje obowiązywać (to skutek, nie czynność), dlatego
  ``shift_free_days`` jest jawnym wyborem wołającego.

Postanowienia umów B2B:

* „ze skutkiem na koniec miesiąca kalendarzowego” — okres liczy się w pełnych
  miesiącach kalendarzowych **po** miesiącu doręczenia. Miesiąc doręczenia
  nigdy nie wchodzi do okresu, także przy doręczeniu 1. dnia, bo dnia
  doręczenia się nie liczy (art. 111 § 2): 1 marca + 1 miesiąc = 30 kwietnia;
* „od kolejnego miesiąca” — pierwszy dzień miesiąca po zdarzeniu.

Wynik ``Deadline`` niesie datę, podstawę (oznaczenia przepisów do
weryfikatora cytatów) i opis kroków po polsku do pokazania przy piśmie.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from app.core.scheduling import is_business_day

UNIT_DAYS = "days"
UNIT_WEEKS = "weeks"
UNIT_MONTHS = "months"
UNIT_YEARS = "years"
UNITS: tuple[str, ...] = (UNIT_DAYS, UNIT_WEEKS, UNIT_MONTHS, UNIT_YEARS)

_MONTHS_PL = (
    "stycznia",
    "lutego",
    "marca",
    "kwietnia",
    "maja",
    "czerwca",
    "lipca",
    "sierpnia",
    "września",
    "października",
    "listopada",
    "grudnia",
)


@dataclass(frozen=True)
class Deadline:
    end: date
    basis: tuple[str, ...]
    steps: tuple[str, ...]


def polish_date(day: date) -> str:
    """„17 marca 2026 r.”."""
    return f"{day.day} {_MONTHS_PL[day.month - 1]} {day.year} r."


def last_day_of_month(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def _shift_months(year: int, month: int, months: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + months
    return index // 12, index % 12 + 1


def add_days(start: date, days: int) -> date:
    """Art. 111: koniec z upływem ostatniego dnia, bez dnia zdarzenia."""
    if days < 0:
        raise ValueError("Termin w dniach nie może być ujemny.")
    return start + timedelta(days=days)


def add_months(start: date, months: int) -> date:
    """Art. 112: dzień odpowiadający datą, a gdy go brak — ostatni dzień miesiąca."""
    if months < 0:
        raise ValueError("Termin w miesiącach nie może być ujemny.")
    year, month = _shift_months(start.year, start.month, months)
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(start.day, last))


def add_years(start: date, years: int) -> date:
    """Art. 112 dla lat: 29 lutego + 1 rok = 28 lutego."""
    return add_months(start, 12 * years)


def add_weeks(start: date, weeks: int) -> date:
    """Art. 112 dla tygodni: ten sam dzień tygodnia."""
    if weeks < 0:
        raise ValueError("Termin w tygodniach nie może być ujemny.")
    return start + timedelta(weeks=weeks)


def non_continuous(start: date, amount: int, unit: str) -> date:
    """Art. 114: bez wymogu ciągłości miesiąc = 30 dni, rok = 365 dni."""
    per_unit = {UNIT_MONTHS: 30, UNIT_YEARS: 365}.get(unit)
    if per_unit is None:
        raise ValueError("Art. 114 dotyczy tylko miesięcy i lat.")
    return add_days(start, amount * per_unit)


def month_point(year: int, month: int, point: str) -> date:
    """Art. 113 § 1: ``start`` = 1., ``middle`` = 15., ``end`` = ostatni dzień."""
    if point == "start":
        return date(year, month, 1)
    if point == "middle":
        return date(year, month, 15)
    if point == "end":
        return last_day_of_month(year, month)
    raise ValueError("Punkt miesiąca: start, middle albo end.")


def is_free_day(day: date) -> bool:
    """Sobota, niedziela albo dzień ustawowo wolny od pracy w Polsce."""
    return not is_business_day(datetime.combine(day, time(12)))


def next_working_day(day: date) -> date:
    """Art. 115: pierwszy dzień, który nie jest wolny od pracy ani sobotą."""
    while is_free_day(day):
        day += timedelta(days=1)
    return day


def first_day_of_next_month(event: date) -> date:
    """„Od kolejnego miesiąca”: 1. dzień miesiąca po zdarzeniu (także gdy zdarzenie jest 1.)."""
    year, month = _shift_months(event.year, event.month, 1)
    return date(year, month, 1)


def term_end(
    start: date,
    amount: int,
    unit: str,
    *,
    continuous: bool = True,
    shift_free_days: bool = False,
) -> Deadline:
    """Koniec terminu ``amount`` × ``unit`` od zdarzenia ``start`` (art. 111–115 KC)."""
    if unit not in UNITS:
        raise ValueError(f"Nieznana jednostka terminu: {unit!r}.")
    steps: list[str] = []
    basis: list[str] = []
    if unit == UNIT_DAYS:
        end = add_days(start, amount)
        basis.append("art. 111 § 2 KC")
        steps.append(
            f"Dnia zdarzenia ({polish_date(start)}) się nie liczy; {amount} dni "
            f"upływa {polish_date(end)}."
        )
    elif not continuous and unit in (UNIT_MONTHS, UNIT_YEARS):
        end = non_continuous(start, amount, unit)
        days = amount * (30 if unit == UNIT_MONTHS else 365)
        basis.append("art. 114 KC")
        steps.append(
            f"Ciągłość terminu nie jest wymagana, więc liczymy {days} dni od "
            f"{polish_date(start)}: koniec {polish_date(end)}."
        )
    else:
        if unit == UNIT_WEEKS:
            end = add_weeks(start, amount)
        elif unit == UNIT_MONTHS:
            end = add_months(start, amount)
        else:
            end = add_years(start, amount)
        basis.append("art. 112 KC")
        clipped = end.day != start.day and unit != UNIT_WEEKS
        steps.append(
            f"Termin kończy się w dniu odpowiadającym datą dniowi początkowemu "
            f"({polish_date(start)}): {polish_date(end)}"
            + (
                " — w tym miesiącu nie ma takiego dnia, więc ostatni dzień miesiąca."
                if clipped
                else "."
            )
        )
    if shift_free_days and is_free_day(end):
        shifted = next_working_day(end)
        basis.append("art. 115 KC")
        steps.append(
            f"{polish_date(end)} to sobota albo dzień wolny od pracy, więc termin "
            f"upływa {polish_date(shifted)}."
        )
        end = shifted
    return Deadline(end=end, basis=tuple(basis), steps=tuple(steps))


def _calendar_months(count: int) -> str:
    if count == 1:
        return "miesiąc kalendarzowy"
    if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        return "miesiące kalendarzowe"
    return "miesięcy kalendarzowych"


def notice_end_of_month(delivered_on: date, months: int) -> Deadline:
    """Wypowiedzenie „ze skutkiem na koniec miesiąca kalendarzowego”.

    Okres = ``months`` pełnych miesięcy kalendarzowych po miesiącu doręczenia;
    umowa kończy się ostatniego dnia ostatniego z nich.
    """
    if months < 1:
        raise ValueError(
            "Okres wypowiedzenia na koniec miesiąca: co najmniej 1 miesiąc."
        )
    year, month = _shift_months(delivered_on.year, delivered_on.month, months)
    end = last_day_of_month(year, month)
    first_year, first_month = _shift_months(delivered_on.year, delivered_on.month, 1)
    return Deadline(
        end=end,
        basis=("art. 111 § 2 KC", "art. 113 § 1 KC"),
        steps=(
            f"Doręczenie {polish_date(delivered_on)}: dnia doręczenia się nie liczy, "
            "więc miesiąc doręczenia nie wchodzi do okresu.",
            f"Okres biegnie od {polish_date(date(first_year, first_month, 1))} przez "
            f"{months} {_calendar_months(months)} i kończy się z końcem miesiąca: "
            f"{polish_date(end)}.",
        ),
    )


def notice_days_end_of_month(delivered_on: date, days: int) -> Deadline:
    """„{days} dni ze skutkiem na koniec miesiąca”: koniec miesiąca, w którym upływa termin."""
    reached = add_days(delivered_on, days)
    end = last_day_of_month(reached.year, reached.month)
    return Deadline(
        end=end,
        basis=("art. 111 § 2 KC", "art. 113 § 1 KC"),
        steps=(
            f"{days} dni od doręczenia {polish_date(delivered_on)} upływa "
            f"{polish_date(reached)}.",
            f"Skutek na koniec tego miesiąca: {polish_date(end)}.",
        ),
    )


def from_next_month(event: date) -> Deadline:
    """„Od kolejnego miesiąca” po zdarzeniu (np. zmiana stawki po podpisie aneksu)."""
    start = first_day_of_next_month(event)
    return Deadline(
        end=start,
        basis=("art. 113 § 1 KC",),
        steps=(
            f"Zdarzenie {polish_date(event)}; „od kolejnego miesiąca” = od "
            f"{polish_date(start)}.",
        ),
    )


def months_word(count: int) -> str:
    """„1 miesiąc”, „3 miesiące”, „5 miesięcy”."""
    if count == 1:
        return "1 miesiąc"
    if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        return f"{count} miesiące"
    return f"{count} miesięcy"


def notice_from_next_month(delivered_on: date, months: int) -> Deadline:
    """Wypowiedzenie z okresem „liczonym od kolejnego miesiąca” (umowy z 2025 r.).

    Okres zaczyna się 1. dnia miesiąca po doręczeniu i trwa ``months``
    miesięcy (art. 112 KC), więc umowa kończy się ostatniego dnia ostatniego
    z nich: doręczenie 12 listopada + 1 miesiąc = 1–31 grudnia. Dzień końca
    wychodzi taki sam jak przy „na koniec miesiąca kalendarzowego” — różni
    się podstawa i opis kroków, które pismo pokazuje Partnerowi.
    """
    if months < 1:
        raise ValueError(
            "Okres wypowiedzenia od kolejnego miesiąca: co najmniej 1 miesiąc."
        )
    start = first_day_of_next_month(delivered_on)
    end = add_months(start, months) - timedelta(days=1)
    return Deadline(
        end=end,
        basis=("art. 112 KC", "art. 113 § 1 KC"),
        steps=(
            f"Doręczenie {polish_date(delivered_on)}: okres liczy się od kolejnego "
            f"miesiąca, czyli od {polish_date(start)}.",
            f"{months_word(months)} od {polish_date(start)} upływa {polish_date(end)}.",
        ),
    )
