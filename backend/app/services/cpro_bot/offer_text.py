"""Pola oferty w Cpro liczone tak, jak wpisuje je osoba od Cpro — bez bazy.

Reguły z nagrania Sandry (28.10.2026, przekazane 17.11.2026):

* **Available from**: ASAP → dziś; okres wypowiedzenia w tygodniach albo
  miesiącach → dziś + okres; konkretna data albo miesiąc („od grudnia”) → ta
  data. Karta screeningu wygrywa z datą z profilu (26.11.2026).
* **Wypowiedzenie** 1–4 tygodnie, „30 dni” i „1 miesiąc” → „a N-week notice
  period” (1 miesiąc = 4 tygodnie, także UoP — osoba od Cpro i Artur 26.11.2026).
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


#: Miesiące w karcie („od grudnia”, „od Stycznia”) → numer miesiąca.
_MONTHS: tuple[tuple[str, int], ...] = (
    ("stycz", 1),
    ("lut", 2),
    ("marz", 3),
    ("marc", 3),
    ("kwie", 4),
    ("maj", 5),
    ("czerw", 6),
    ("lip", 7),
    ("sierp", 8),
    ("wrze", 9),
    ("pazdz", 10),
    ("listop", 11),
    ("grud", 12),
)
_MONTH_RE = re.compile(r"\b(?:od|from|w|in)\s+(\w+)")
_DATE_IN_TEXT_RE = re.compile(r"\b(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?\b")
_ISO_DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")


def _next_date(
    day: int, month: int, year: Optional[int], today: date
) -> Optional[date]:
    """Data z karty; bez roku — najbliższa nie wcześniejsza niż dziś."""

    if year is not None and year < 100:
        year += 2000
    try:
        found = date(year or today.year, month, day)
    except ValueError:
        return None
    if year is None and found < today:
        found = date(today.year + 1, month, day)
    return found


def card_start_date(text: Optional[str], today: date) -> Optional[date]:
    """Termin z tekstu karty: „01.12.2026”, „1.12”, „2026-12-01”, „od grudnia”."""

    folded = fold(text)
    if not folded:
        return None
    if match := _ISO_DATE_RE.search(folded):
        return _next_date(int(match[3]), int(match[2]), int(match[1]), today)
    if match := _DATE_IN_TEXT_RE.search(folded):
        year = int(match[3]) if match[3] else None
        return _next_date(int(match[1]), int(match[2]), year, today)
    for match in _MONTH_RE.finditer(folded):
        word = match[1]
        for stem, month in _MONTHS:
            if word.startswith(stem):
                return _next_date(1, month, None, today.replace(day=1))
    return None


def _notice_weeks(value: int, unit: str) -> Optional[int]:
    """Okres w tygodniach, gdy osoba od Cpro wpisuje „N-week notice period”.

    1–4 tygodnie; „30 dni” i „1 miesiąc” (także UoP — decyzja Artura
    26.11.2026) to 4 tygodnie. Dłuższe okresy zostają w miesiącach.
    """

    if unit == "weeks" and 1 <= value <= 4:
        return value
    if unit == "months" and value == 1:
        return 4
    if unit == "days" and value % 7 == 0 and 7 <= value <= 28:
        return value // 7
    if unit == "days" and 28 <= value <= 31:
        return 4
    return None


def availability(
    *,
    today: date,
    available_date: Optional[date],
    card_value: Optional[Mapping[str, Any]],
) -> Availability:
    """Data do pola „Available from” i końcówka „ściągawki”.

    Karta screeningu wygrywa z datą z NEXUSA (profil albo koniec umowy): to
    najświeższe słowo rekrutera (osoba od Cpro 26.11.2026 — data z profilu dawała
    „available from 25.12.2026” przy „2 tyg wypowiedzenia”). Okres
    wypowiedzenia liczy się od dziś. Bez karty data z NEXUSA w przyszłości,
    a bez niej — „od zaraz”, tak samo jak w kolejce Cpro.
    """

    card = card_value or {}
    if card.get("asap"):
        return Availability(today, "available ASAP")
    notice = card.get("notice")
    if isinstance(notice, Mapping):
        try:
            value = int(notice.get("value") or 0)
        except (TypeError, ValueError):
            value = 0
        unit = str(notice.get("unit") or "")
        weeks = _notice_weeks(value, unit) if value > 0 else None
        if weeks is not None:
            return Availability(
                today + timedelta(weeks=weeks), f"a {weeks}-week notice period"
            )
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
    start = card_start_date(card.get("date_text"), today) or card_start_date(
        card.get("raw"), today
    )
    if start is not None:
        if start > today:
            return Availability(start, f"available from {start:%d.%m.%Y}")
        return Availability(today, "available ASAP")
    if available_date is not None and available_date > today:
        return Availability(available_date, f"available from {available_date:%d.%m.%Y}")
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
