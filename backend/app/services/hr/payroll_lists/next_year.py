"""Strażnik parametrów płac na nowy rok.

Od 30 dni przed 1 stycznia (kalendarz firmy) do chwili, gdy jest żywa wersja
parametrów od 1 stycznia, ekran parametrów i ekrany miesięcy płac pokazują
„Brak parametrów płac od 01.01.RRRR” ze szkicem nowej wersji: wartości
z bieżącej wersji plus to, co już ogłoszono na nowy rok (``KNOWN``).

Szkic niczego nie zapisuje ani nie zatwierdza — Płace zapisują wersję
istniejącym formularzem (wchodzi jako „Do potwierdzenia”) i potwierdzają ją
jak każdą inną.

Za rok: dopisz wpis do ``KNOWN`` z aktem, adresem i datą ogłoszenia. Wpisuj
tylko wartości z ogłoszonych aktów — pozostałe parametry szkic bierze
z bieżącej wersji, a komunikat ``UNCHANGED_NOTE`` mówi, co sprawdzić.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Optional

from app.services.hr.payroll_lists import params as params_rules

#: Ile dni przed 1 stycznia strażnik zaczyna przypominać.
LEAD_DAYS = 30


@dataclass(frozen=True)
class KnownValue:
    key: str
    value: str
    source: str
    url: str
    #: Data ogłoszenia aktu (RRRR-MM-DD).
    published: str


_MINIMUM_WAGE_2027 = (
    "Dz.U. 2026 poz. 1213 (rozporządzenie RM z 14.09.2026)",
    "https://api.sejm.gov.pl/eli/acts/DU/2026/1213",
    "2026-09-15",
)
_PENSION_LIMIT_2027 = (
    "M.P. 2026 poz. 1098 (obwieszczenie MRPiPS z 3.11.2026)",
    "https://api.sejm.gov.pl/eli/acts/MP/2026/1098",
    "2026-11-04",
)

#: Wartości ogłoszone na dany rok — klucze jak w ``params.SPECS``.
KNOWN: dict[int, tuple[KnownValue, ...]] = {
    2027: (
        KnownValue("minimum_wage", "4950.00", *_MINIMUM_WAGE_2027),
        KnownValue("minimum_hourly_rate", "32.30", *_MINIMUM_WAGE_2027),
        KnownValue("annual_pension_limit", "300990.00", *_PENSION_LIMIT_2027),
    ),
}

UNCHANGED_NOTE = (
    "Pozostałe parametry są przepisane z bieżącej wersji. Progi i kwoty PIT na {year} "
    "nie są jeszcze pewne (zmiana ustawy po Senacie), więc zostają jak dziś. Limit "
    "dobrowolnej chorobowej, stopę wypadkową i resztę sprawdź przed zapisem."
)

assert all(
    item.key in params_rules.SPECS for values in KNOWN.values() for item in values
), "klucze KNOWN"


@dataclass(frozen=True)
class Version:
    """Żywa wersja parametrów — tyle, ile strażnik potrzebuje."""

    effective_from: date
    params: Mapping[str, Any]


def target_year(today: date) -> int:
    """Rok, którego 1 stycznia pilnujemy: następny od 2 grudnia, inaczej bieżący."""

    upcoming = date(today.year + 1, 1, 1)
    return (
        upcoming.year if upcoming - today <= timedelta(days=LEAD_DAYS) else today.year
    )


def _base(versions: Iterable[Version], start: date) -> Optional[Version]:
    earlier = [v for v in versions if v.effective_from < start]
    return max(earlier, key=lambda v: v.effective_from) if earlier else None


def gap(today: date, versions: Iterable[Version]) -> Optional[dict[str, Any]]:
    """Szkic wersji od 1 stycznia albo ``None``, gdy przypominać nie trzeba.

    ``versions`` — tylko żywe wersje (bez zastąpionych i wycofanych).
    """

    live = list(versions)
    year = target_year(today)
    start = date(year, 1, 1)
    if any(v.effective_from == start for v in live):
        return None
    base = _base(live, start)
    if base is None:
        # Bez żadnej wersji ekran i tak mówi „dodaj wersję” — szkicu nie ma z czego zrobić.
        return None
    draft = {key: str(base.params.get(key, "")) for key in params_rules.SPECS}
    for key, value in params_rules.LATER_DEFAULTS.items():
        if not draft[key]:
            draft[key] = value
    known = []
    for item in KNOWN.get(year, ()):
        known.append(
            {
                "key": item.key,
                "label": params_rules.SPECS[item.key].label,
                "unit": params_rules.SPECS[item.key].unit,
                "value": item.value,
                "before": draft[item.key],
                "source": item.source,
                "url": item.url,
                "published": item.published,
            }
        )
        draft[item.key] = item.value
    return {
        "year": year,
        "effective_from": start.isoformat(),
        "base_effective_from": base.effective_from.isoformat(),
        "params": draft,
        "known": known,
        "unchanged_note": UNCHANGED_NOTE.format(year=year),
        "note": _draft_note(year),
    }


def _draft_note(year: int) -> str:
    """Uwaga do zapisywanej wersji: skąd wartości wstępne (mieści się w NOTE_MAX)."""

    by_source: dict[str, list[str]] = {}
    for item in KNOWN.get(year, ()):
        by_source.setdefault(item.source.split(" (")[0], []).append(
            params_rules.SPECS[item.key].label.split(" (")[0].lower()
        )
    if not by_source:
        return f"Parametry od 01.01.{year} — przepisane z poprzedniej wersji."
    parts = [f"{', '.join(labels)}: {source}" for source, labels in by_source.items()]
    return f"Parametry od 01.01.{year}. " + "; ".join(parts) + "."


__all__ = [
    "KNOWN",
    "KnownValue",
    "LEAD_DAYS",
    "UNCHANGED_NOTE",
    "Version",
    "gap",
    "target_year",
]
