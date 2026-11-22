"""Pola oferty w Cpro liczone tak, jak wpisuje je osoba od Cpro — bez bazy.

Reguły z nagrania Sandry (28.10.2026, przekazane 17.11.2026):

* **Available from**: ASAP → dziś; okres wypowiedzenia w tygodniach albo
  miesiącach → dziś + okres; konkretna data → ta data.
* **Physical location** to jedna z trzech „ściągawek”:
  ``"<miasto>, willing to come to the Nordea office in <biuro> 3x/week, available ASAP"``,
  ``"…, a 4-week notice period"`` albo ``"…, a 1-month notice period"``,
  a przy dacie ``"…, available from 01.12.2026"``. Biuro to miasto kandydata,
  gdy jest wśród miast rekrutacji, a dni z biura — z rekrutacji, domyślnie 3
  („tyle zazwyczaj wymaga Nordea”). Były pracownik albo konsultant Nordei
  dostaje dopisek na końcu.
* **Motivation** i opis profilu to punkty „Why our candidate?” z CV firmowego:
  każdy punkt od myślnika, bez pustych linii.
* **Nazwa pliku CV** bez ``#``: z nim CV nie otwiera się ani u nas, ani u Nordei.
"""

from __future__ import annotations

import calendar
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Mapping, Optional

DEFAULT_OFFICE_DAYS = 3

#: Miasta, które rozpoznajemy w wolnym tekście lokalizacji rekrutacji i osoby,
#: z nazwą, jaką Sandra wpisuje w Cpro (po angielsku tam, gdzie się różni).
CITY_NAMES: dict[str, str] = {
    "warszawa": "Warsaw",
    "warsaw": "Warsaw",
    "gdynia": "Gdynia",
    "gdansk": "Gdansk",
    "sopot": "Sopot",
    "trojmiasto": "Tricity",
    "tricity": "Tricity",
    "krakow": "Krakow",
    "wroclaw": "Wroclaw",
    "poznan": "Poznan",
    "lodz": "Lodz",
    "katowice": "Katowice",
    "szczecin": "Szczecin",
    "lublin": "Lublin",
    "bydgoszcz": "Bydgoszcz",
    "torun": "Torun",
    "rzeszow": "Rzeszow",
    "bialystok": "Bialystok",
    "olsztyn": "Olsztyn",
    "gliwice": "Gliwice",
}
_TRICITY = ("gdynia", "gdansk", "sopot", "trojmiasto", "tricity")

#: Narodowość z karty („polska”, „Polak”, „PL”) → nazwa kraju z listy Cpro.
_POLISH = re.compile(r"^(pl|polsk\w*|polak\w*|polka|poland|polish)$", re.IGNORECASE)


def fold(text: Optional[str]) -> str:
    text = (text or "").replace("ł", "l").replace("Ł", "L")
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c)).strip()


def cities_in(text: Optional[str]) -> list[str]:
    """Znane miasta w kolejności wystąpienia w tekście (klucze ``CITY_NAMES``)."""

    folded = fold(text)
    found: list[tuple[int, str]] = []
    for key in CITY_NAMES:
        match = re.search(rf"\b{re.escape(key)}\b", folded)
        if match:
            found.append((match.start(), key))
    seen: set[str] = set()
    out: list[str] = []
    for _, key in sorted(found):
        name = CITY_NAMES[key]
        if name not in seen:
            seen.add(name)
            out.append(key)
    return out


def city_label(text: Optional[str]) -> Optional[str]:
    """Miasto osoby do Cpro: znane miasto z tekstu, inaczej pierwszy człon."""

    known = cities_in(text)
    if known:
        return CITY_NAMES[known[0]]
    first = re.split(r"[,;(/\n]", (text or "").strip())[0].strip(" .-")
    if not first or not any(ch.isalpha() for ch in first):
        return None
    return first[:60]


def office_city(
    candidate_city: Optional[str], job_location: Optional[str]
) -> Optional[str]:
    """Biuro Nordei, do którego osoba będzie dojeżdżać.

    Miasto osoby, gdy rekrutacja je wymienia; osoba z Trójmiasta przy
    rekrutacji w Gdyni albo Gdańsku — to z nich, które rekrutacja wymienia
    pierwsze; inaczej pierwsze miasto rekrutacji, a bez miast — miasto osoby.
    """

    job = cities_in(job_location)
    own = cities_in(candidate_city)
    if own and own[0] in job:
        return CITY_NAMES[own[0]]
    if own and own[0] in _TRICITY:
        for key in job:
            if key in ("gdynia", "gdansk"):
                return CITY_NAMES[key]
    if job:
        return CITY_NAMES[job[0]]
    return city_label(candidate_city)


def add_months(day: date, months: int) -> date:
    month = day.month - 1 + months
    year = day.year + month // 12
    month = month % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


@dataclass(frozen=True)
class Availability:
    available_from: date
    phrase: str


def availability(
    *,
    today: date,
    available_date: Optional[date],
    card_value: Optional[Mapping[str, Any]],
) -> Availability:
    """Data do pola „Available from” i końcówka „ściągawki”.

    Data z NEXUSA (profil albo koniec umowy) wygrywa, gdy jest w przyszłości.
    Bez niej okres wypowiedzenia z karty liczy się od dziś. Brak danych
    znaczy „od zaraz” — tak samo pokazuje to kolejka Cpro.
    """

    if available_date is not None and available_date > today:
        return Availability(available_date, f"available from {available_date:%d.%m.%Y}")
    notice = (card_value or {}).get("notice") if card_value else None
    if isinstance(notice, Mapping) and not (card_value or {}).get("asap"):
        try:
            value = int(notice.get("value") or 0)
        except (TypeError, ValueError):
            value = 0
        unit = str(notice.get("unit") or "")
        if value > 0 and unit == "months":
            return Availability(
                add_months(today, value), f"a {value}-month notice period"
            )
        if value > 0 and unit == "weeks":
            return Availability(
                today + timedelta(weeks=value), f"a {value}-week notice period"
            )
        if value > 0 and unit == "days":
            return Availability(
                today + timedelta(days=value), f"a {value}-day notice period"
            )
    return Availability(today, "available ASAP")


@dataclass(frozen=True)
class FormerAtClient:
    employee: Optional[bool]
    consultant: Optional[bool]


def former_at_client(card_value: Optional[Mapping[str, Any]]) -> FormerAtClient:
    """„Czy pracował u Klienta” z karty → dwa pola Cpro.

    ``uop`` = był pracownikiem, ``b2b`` = był konsultantem, ``no`` = ani to,
    ani to. Samo „tak” albo brak odpowiedzi: ``None`` — bot rozstrzyga z CV
    (Nordea jako pracodawca = pracownik, jako klient innej firmy = konsultant).
    """

    value = str((card_value or {}).get("value") or "")
    if value == "uop":
        return FormerAtClient(employee=True, consultant=False)
    if value == "b2b":
        return FormerAtClient(employee=False, consultant=True)
    if value == "no":
        return FormerAtClient(employee=False, consultant=False)
    return FormerAtClient(employee=None, consultant=None)


def physical_location(
    *,
    city: str,
    office: Optional[str],
    remote_policy: Optional[str],
    onsite_days_per_week: Optional[int],
    availability_phrase: str,
    former: FormerAtClient,
    client_label: str = "Nordea",
) -> str:
    if remote_policy == "remote":
        parts = [f"{city}, working remotely"]
    else:
        days = onsite_days_per_week or (
            5 if remote_policy == "onsite" else DEFAULT_OFFICE_DAYS
        )
        parts = [
            f"{city}, willing to come to the {client_label} office in {office or city} {days}x/week"
        ]
    parts.append(availability_phrase)
    if former.employee:
        parts.append(f"a former employee at {client_label}")
    elif former.consultant:
        parts.append(f"a former consultant at {client_label}")
    return ", ".join(parts)


_BULLET = re.compile(r"^\s*(?:[-–—•*·]|\d+[.)])\s*")


def motivation(points: list[str]) -> str:
    """Punkty „Why our candidate?” jako tekst do Cpro: myślnik, bez pustych linii."""

    lines: list[str] = []
    for point in points:
        text = " ".join(_BULLET.sub("", str(point)).replace("**", "").split())
        if text:
            lines.append(f"- {text}")
    return "\n".join(lines)


def citizenship(raw: Optional[str]) -> Optional[str]:
    """Narodowość z karty → kraj z listy Cpro (``Poland`` dla polskiej)."""

    text = " ".join((raw or "").split()).strip(" .")
    if not text or not any(ch.isalpha() for ch in text):
        return None
    if _POLISH.match(text):
        return "Poland"
    return text[:60]


def safe_filename(
    name: Optional[str], fallback: str = "CV.pdf", *, extension: str = ".pdf"
) -> str:
    """Nazwa PDF do Cpro; jawne DOCX tylko dla historycznego zlecenia.

    Bez ``#`` i ścieżki; limit nigdy nie ucina rozszerzenia pliku.
    """

    base = (name or "").replace("\\", "/").rsplit("/", 1)[-1]
    base = " ".join(base.replace("#", "").split()).strip(" .")
    if not base:
        base = fallback
    base = re.sub(r"\.(?:docx|pdf)$", "", base, flags=re.IGNORECASE).strip(" .")
    return f"{(base or 'CV')[: 180 - len(extension)]}{extension}"
