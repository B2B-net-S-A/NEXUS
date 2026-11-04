"""Okres stanowiska w CV firmowym ma być taki jak w oryginale (02.11.2026).

Rekruterka zgłosiła, że koniec pracy „05.2026” staje się w CV firmowym
„obecnie”. Pomiar 02.11.2026 (797 CV z 30 dni): 59 ról z 555 porównywalnych
„obecnie” przeczyło oryginałowi, bo prompt każe pisać „obecnie” przy trwającym
stanowisku, a kod dat nie porównywał. Decyzja Artura: oryginał wygrywa także
wtedy, gdy kandydat mówi w rozmowie co innego — taką zmianę rekruter wpisuje
ręcznie w edytorze.

Ta sama reguła działa w generatorze (po odpowiedzi modelu), w uwadze QC „Daty
stanowisk jak w oryginale” i w jej poprawce.

Różnica liczy się tylko przy pewnym dopasowaniu: w oryginale jeden okres z tym
samym początkiem, a obok niego w tekście nazwa firmy albo stanowiska. Bez tego
warunku studia 10.2019 – 06.2021 zamknęłyby trwającą pracę z tym samym
początkiem. Oryginał w formacie, którego nie umiemy przeczytać, nie zmienia
niczego.

Generator sam poprawia wyłącznie fałszywe „obecnie”. Inna data końca bywa
świadomym złączeniem albo podziałem stanowisk (pomiar 02.11.2026: „Wcześniejsze
projekty”, awanse w jednej firmie), więc te różnice pokazuje uwaga QC, a decyduje
rekruter.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from typing import Any, Optional

from app.core.scheduling import business_today

YearMonth = tuple[int, Optional[int]]

_MONTH_NAMES = {
    1: "jan january sty stycz styczen styczeń stycznia",
    2: "feb february lut luty lutego",
    3: "mar march marzec marca",
    4: "apr april kwi kwiecien kwiecień kwietnia",
    5: "may maj maja",
    6: "jun june cze czerwiec czerwca",
    7: "jul july lip lipiec lipca",
    8: "aug august sie sierpien sierpień sierpnia",
    9: "sep sept september wrz wrzesien wrzesień wrzesnia września",
    10: "oct october paz paź pazdziernik październik pazdziernika października",
    11: "nov november lis listopad listopada",
    12: "dec december gru grudzien grudzień grudnia",
}
_MONTHS = {name: n for n, names in _MONTH_NAMES.items() for name in names.split()}
_MONTH_WORD = "|".join(sorted(_MONTHS, key=len, reverse=True))
_YEAR = r"(?:19|20)\d{2}"
_NUM_MONTH = r"(?:0?[1-9]|1[0-2])"
_DAY = r"(?:0?[1-9]|[12]\d|3[01])"
_MONTH_DATE = (
    rf"(?:{_DAY}[./-])?{_NUM_MONTH}[./-]{_YEAR}"
    rf"|{_YEAR}[./-]{_NUM_MONTH}"
    rf"|(?:{_MONTH_WORD})\.?,?\s+{_YEAR}"
)
_DATE = rf"(?:{_MONTH_DATE}|{_YEAR})"
_ONGOING = (
    r"obecnie|nadal|teraz|aktualnie|do\s+dzi[śs]|do\s+teraz|currently|current"
    r"|present|now|today|ongoing|till\s+now|to\s+date"
)
_SEPARATOR = r"\s*(?:-|–|—|−|\bdo\b|\bto\b|\buntil\b|\btill\b)\s*"
_RANGE = re.compile(
    rf"(?<![\w./-])(?P<start>{_DATE}){_SEPARATOR}"
    rf"(?P<end>{_DATE}|{_ONGOING})(?![\w/]|\.\d)"
    # Dwie pełne daty bez myślnika („01/2021 09/2024”): układ kolumn w PDF-ie.
    rf"|(?<![\w./-])(?P<bare_start>{_MONTH_DATE})\s+(?P<bare_end>{_MONTH_DATE})(?![\w/]|\.\d)",
    re.IGNORECASE,
)
# Słowa, które stoją przy wielu firmach, nie wskazują tej jednej.
_GENERIC_WORDS = frozenset(
    "bank group grupa poland polska project projekt services service solutions "
    "company firma zakres zadan zadania obowiazki responsibilities spolka".split()
)
# Tyle znaków od okresu może w oryginale stać nazwa firmy albo stanowiska.
_ROLE_WINDOW = 400


@dataclass(frozen=True)
class DateRange:
    start: YearMonth
    # ``None`` = stanowisko trwa.
    end: Optional[YearMonth]
    at: int
    raw: str


def _parse_date(token: str) -> Optional[YearMonth]:
    text = token.strip().casefold()
    if re.fullmatch(_YEAR, text):
        return int(text), None
    match = re.fullmatch(rf"(?:{_DAY}[./-])?({_NUM_MONTH})[./-]({_YEAR})", text)
    if match:
        return int(match.group(2)), int(match.group(1))
    match = re.fullmatch(rf"({_YEAR})[./-]({_NUM_MONTH})", text)
    if match:
        return int(match.group(1)), int(match.group(2))
    match = re.fullmatch(rf"({_MONTH_WORD})\.?,?\s+({_YEAR})", text)
    if match:
        return int(match.group(2)), _MONTHS[match.group(1)]
    return None


def date_ranges(text: Optional[str]) -> list[DateRange]:
    """Okresy z tekstu CV w kolejności tekstu; ``end=None`` to stanowisko trwające."""
    found: list[DateRange] = []
    for match in _RANGE.finditer(text or ""):
        start = _parse_date(match.group("start") or match.group("bare_start"))
        raw_end = match.group("end") or match.group("bare_end")
        end = _parse_date(raw_end)
        if start is None or (end is None and re.fullmatch(_DATE, raw_end, re.I)):
            continue
        # „09.2018 - 06.2014” to dwa sąsiednie okresy w układzie kolumn, nie okres.
        if end is not None and end[0] < start[0]:
            continue
        if end is not None and end[0] == start[0] and (end[1] or 12) < (start[1] or 1):
            continue
        found.append(DateRange(start, end, match.start(), match.group(0)))
    return found


def _fold(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text.replace("ł", "l").replace("Ł", "L"))
    return plain.encode("ascii", "ignore").decode().casefold()


# Linia stanowiska niesie też okres: jego słowa nie wskazują firmy.
_PERIOD_WORDS = frozenset(_fold(name) for name in _MONTHS) | frozenset(
    "obecnie nadal teraz aktualnie currently current present today ongoing".split()
)


def _role_words(role_text: str) -> list[str]:
    words = re.split(r"[^a-z0-9+#]+", _fold(role_text))
    return [
        w
        for w in words
        if len(w) >= 4
        and re.search(r"[a-z]", w)
        and w not in _GENERIC_WORDS
        and w not in _PERIOD_WORDS
    ]


def _names_role(found: DateRange, source: str, words: list[str]) -> bool:
    around = _fold(
        source[
            max(0, found.at - _ROLE_WINDOW) : found.at + len(found.raw) + _ROLE_WINDOW
        ]
    )
    return any(re.search(rf"(?<![a-z0-9]){re.escape(w)}", around) for w in words)


def _same_end(a: Optional[YearMonth], b: Optional[YearMonth]) -> bool:
    if a is None or b is None:
        return a is b
    # Rok bez miesiąca nie przeczy dacie z tego samego roku.
    return a[0] == b[0] and (a[1] is None or b[1] is None or a[1] == b[1])


def _render(value: YearMonth) -> str:
    year, month = value
    return f"{month:02d}.{year}" if month else str(year)


def _source_range(
    role: DateRange, source: str, ranges: list[DateRange], role_text: str
) -> Optional[DateRange]:
    """Jedyny okres tego stanowiska w oryginale albo ``None``."""
    same = [r for r in ranges if r.start == role.start]
    if not same and role.end is None:
        # Model dopisuje miesiąc do roku z oryginału (i odwrotnie).
        same = [
            r
            for r in ranges
            if r.start[0] == role.start[0]
            and (r.start[1] is None or role.start[1] is None)
        ]
    words = _role_words(role_text)
    if not words:
        return None
    # Złączone awanse: „05.2021 - obecnie” przy dwóch okresach tej samej firmy.
    if role.end is None and any(
        r.end is None and _names_role(r, source, words) for r in ranges
    ):
        return None
    same = [r for r in same if _names_role(r, source, words)]
    if not same or len({(r.start, r.end) for r in same}) != 1:
        return None
    return same[0]


@dataclass(frozen=True)
class DateFix:
    current: str
    expected: str
    # Model napisał „obecnie”, a oryginał podaje datę końca.
    false_ongoing: bool


def date_fix(dates: str, source: str, role_text: str) -> Optional[DateFix]:
    """Okres z oryginału, gdy ``dates`` mu przeczy; ``None`` = zgodne albo niepewne."""
    found = date_ranges(dates)
    if not found:
        return None
    role = found[-1]
    match = _source_range(role, source, date_ranges(source), role_text)
    if match is None or _same_end(role.end, match.end):
        return None
    start = role.start if role.start == match.start else match.start
    end = _render(match.end) if match.end else "obecnie"
    return DateFix(
        role.raw,
        f"{_render(start)} - {end}",
        false_ongoing=role.end is None and match.end is not None,
    )


def restore_experience_dates(
    candidate_data: dict[str, Any], source: str, today: Optional[date] = None
) -> int:
    """Fałszywe „obecnie” z danych generatora. Zwraca liczbę zmian.

    Bieżący miesiąc jako koniec to to samo „obecnie”, tylko zapisane datą: model,
    któremu prompt zabrania „obecnie”, wpisał 11.2026 przy końcu 09.2026 w oryginale.
    """
    now = (today or business_today()).year * 12 + (today or business_today()).month
    changed = 0
    for job in candidate_data.get("experience") or []:
        if not isinstance(job, dict):
            continue
        dates = str(job.get("dates") or "")
        role_text = f"{job.get('company') or ''} {job.get('position') or ''}"
        fix = date_fix(dates, source, role_text)
        if fix is None:
            continue
        end = date_ranges(fix.current)[-1].end
        ends_now = (
            end is not None and end[1] is not None and end[0] * 12 + end[1] >= now
        )
        if fix.false_ongoing or ends_now:
            job["dates"] = dates.replace(fix.current, fix.expected, 1)
            changed += 1
    return changed
