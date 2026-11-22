"""Lata w punkcie 1 i daty stanowisk — trzy uwagi QC w panelu „Do poprawy” (R2–R3, 17.11.2026).

Pomiar 17.11.2026 na 126 CV zatwierdzonych 09–16.11 (kopia produkcji): w 24 CV
rekruter podniósł liczbę lat w punkcie 1 „Dlaczego nasz kandydat”, bo generator
liczy tylko role o tej samej nazwie, a rekruter cały staż w zawodzie; 25 CV
miało role z samym rokiem, a w 17 z nich oryginał podaje miesiące; jedna rola
„08.2021 – 09.2019” zaniżyła staż z 7 do 5 lat. Decyzja Artura (R2, R3):

* „Lata w punkcie 1” pokazuje, z czego wyszła liczba — sumę dat ról pasujących
  do stanowiska z punktu 1 i cały staż z dat wszystkich ról — a przy różnicy
  od roku proponuje „Ponad N lat w IT, w tym ponad M lat jako X”. Decyduje
  rekruter, bo role spoza obszaru (gastronomia, sklep) nie powinny wchodzić.
* „Data końca przed datą startu” z „Odwróć daty”.
* „Rola z samym rokiem”, gdy oryginał ma miesiąc przy tym roku — „Pokaż oryginał”.

Wszystko liczy kod z treści CV (i tekstu oryginału), bez AI. Nic tu nie
zmienia CV samo — poprawki nakłada `cv_qc.transform_html` na prośbę rekrutera.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from typing import Optional

from app.services import cv_source_dates
from app.services.cv_source_dates import DateRange

# Od tylu miesięcy różnicy między całym stażem a rolami z punktu 1 jest propozycja.
GAP_MONTHS = 12
# Tyle stanowisk wypisujemy przy uwadze; CV z edytora może ich nieść setki.
ROLES_LISTED = 30

_CLAUSE_END = re.compile(r"[:;,()]|\.(?:\s|$)|\s[–—-]\s")
# „jako Analityk”, „as an IT Project Manager”: stanowisko wprost po łączniku.
_AS_ROLE = re.compile(r"\b(?:jako|as)\s+(?:(?:a|an)\s+)?", re.IGNORECASE)
# Punkt już w nowej formie („…, w tym 5 lat jako X”) — nie proponujemy drugi raz.
_ALREADY_SPLIT = re.compile(r"\bw\s+tym\b|\bincluding\b|\bof\s+which\b", re.IGNORECASE)
_ENGLISH = re.compile(r"\b(?:years?|experience|over|as)\b", re.IGNORECASE)


@dataclass(frozen=True)
class RoleLine:
    """Stanowisko z CV: numer, nazwa bez okresu i okres z linii stanowiska."""

    index: int
    title: str
    period: Optional[DateRange]


@dataclass(frozen=True)
class RoleMonths:
    title: str
    dates: Optional[str]
    months: Optional[int]
    matched: bool


@dataclass(frozen=True)
class Tenure:
    """Z czego wyszła liczba lat w punkcie 1."""

    quote: str
    figure: str
    matched_months: Optional[int]
    total_months: int
    roles: tuple[RoleMonths, ...]
    # Fragment punktu 1 do podmiany i propozycja; ``None`` = bez propozycji.
    segment: Optional[str]
    proposal: Optional[str]


def _fold(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text.replace("ł", "l").replace("Ł", "L"))
    words = re.findall(
        r"[a-z0-9+#]+", plain.encode("ascii", "ignore").decode().casefold()
    )
    return " ".join(words)


def _month_index(value: tuple[int, Optional[int]], *, end: bool) -> int:
    year, month = value
    return year * 12 + (month or (12 if end else 1)) - 1


def role_bounds(period: Optional[DateRange], today: date) -> Optional[tuple[int, int]]:
    """(start, koniec) jako numery miesięcy; ``None`` bez dat albo przy odwróconych.

    „Obecnie” i koniec w przyszłości liczą się do bieżącego miesiąca. Rok bez
    miesiąca to styczeń na starcie i grudzień na końcu — jak `cv_qc._ym`.
    """
    if period is None or cv_source_dates.is_reversed(period):
        return None
    now = today.year * 12 + today.month - 1
    start = _month_index(period.start, end=False)
    finish = now if period.end is None else _month_index(period.end, end=True)
    finish = min(finish, now)
    if finish < start:
        return None
    return start, finish


def union_months(bounds: list[tuple[int, int]]) -> int:
    """Miesiące w sumie przedziałów; nakładające się okresy liczą się raz."""
    if not bounds:
        return 0
    ordered = sorted(bounds)
    total = 0
    cur_start, cur_end = ordered[0]
    for start, finish in ordered[1:]:
        if start <= cur_end + 1:
            cur_end = max(cur_end, finish)
        else:
            total += cur_end - cur_start + 1
            cur_start, cur_end = start, finish
    return total + cur_end - cur_start + 1


def months_text(months: int) -> str:
    """„7 lat 3 mies.”, „1 rok”, „5 mies.” — do listy ról przy uwadze."""
    from app.services.cv_generator_b2b.legacy_v7._helpers import _years_text

    years, rest = divmod(max(months, 0), 12)
    parts = [_years_text(years, "pl")] if years else []
    if rest or not parts:
        parts.append(f"{rest} mies.")
    return " ".join(parts)


def _scope(point: str, figure_end: int) -> tuple[str, int]:
    """Fraza po liczbie lat do końca zdania składowego i jej koniec w punkcie."""
    rest = point[figure_end:]
    end = _CLAUSE_END.search(rest)
    stop = figure_end + (end.start() if end else len(rest))
    return point[figure_end:stop], stop


def _as_phrase(scope: str) -> Optional[str]:
    """Stanowisko po „jako” / „as” z frazy po liczbie lat."""
    found = _AS_ROLE.search(scope)
    if not found:
        return None
    phrase = scope[found.end() :].strip()
    cut = re.search(r"\s(?:w|we|u|z|ze|dla|at|in|with|for)\s", phrase, re.IGNORECASE)
    phrase = (phrase[: cut.start()] if cut else phrase).strip()
    return phrase if len(_fold(phrase)) >= 3 else None


def _matches(title: str, scope_key: str, as_key: Optional[str]) -> bool:
    key = _fold(title)
    if len(key) < 3:
        return False
    if f" {key} " in f" {scope_key} ":
        return True
    return bool(as_key) and f" {as_key} " in f" {key} "


def _join(titles: list[str], language: str) -> str:
    if len(titles) == 1:
        return titles[0]
    word = " and " if language == "en" else " i "
    return ", ".join(titles[:-1]) + word + titles[-1]


def tenure(point: str, roles: list[RoleLine], today: date) -> Optional[Tenure]:
    """Lata z punktu 1 rozłożone na role; ``None`` bez liczby lat albo bez dat.

    Rola pasuje, gdy jej nazwa stoi we frazie po liczbie lat („w rolach Cloud
    Operations Engineer i DevOps Engineer”) albo zawiera stanowisko po „jako”
    / „as”. Od 20.11.2026 przy „jako X” pasują też role tego samego zawodu,
    jak w generatorze (`legacy_v7.role_family`), poza „jako X w <Firma>”
    i punktem wyliczającym kilka ról. Rola bez dat nie wchodzi do żadnej sumy
    (stoi na liście „bez dat”), a odwrócone daty pokazuje osobna uwaga.
    """
    from app.services.cv_generator_b2b.legacy_v7._helpers import (
        _YEARS_PHRASE_RE,
        _role_claims,
        _tenure_figure,
        _tenure_text,
    )
    from app.services.cv_generator_b2b.legacy_v7.role_family import (
        names_company,
        same_profession,
    )

    found = next(
        (m for m in _YEARS_PHRASE_RE.finditer(point) if _tenure_figure(m) is not None),
        None,
    )
    if found is None or not roles:
        return None
    scope, stop = _scope(point, found.end())
    scope_key = _fold(scope)
    as_phrase = _as_phrase(scope)
    as_key = _fold(as_phrase) if as_phrase else None
    family = (
        as_phrase is not None
        and _role_claims(point) < 2
        and not names_company(scope[scope.find(as_phrase) + len(as_phrase) :])
    )

    listed: list[RoleMonths] = []
    all_bounds: list[tuple[int, int]] = []
    matched_bounds: list[tuple[int, int]] = []
    matched_titles: list[str] = []
    for role in roles:
        bounds = role_bounds(role.period, today)
        hit = _matches(role.title, scope_key, as_key) or (
            family and same_profession(str(as_phrase), role.title)
        )
        if bounds is not None:
            all_bounds.append(bounds)
            if hit:
                matched_bounds.append(bounds)
                if role.title not in matched_titles:
                    matched_titles.append(role.title)
        listed.append(
            RoleMonths(
                title=role.title,
                dates=role.period.raw if role.period else None,
                months=bounds[1] - bounds[0] + 1 if bounds else None,
                matched=hit,
            )
        )
    if not all_bounds:
        return None
    total = union_months(all_bounds)
    matched = union_months(matched_bounds) if matched_bounds else None

    segment = proposal = None
    if (
        matched is not None
        and total - matched >= GAP_MONTHS
        and not _ALREADY_SPLIT.search(point)
    ):
        language = "en" if _ENGLISH.search(point[found.start() : stop]) else "pl"
        at_start = not point[: found.start()].strip()
        label = as_phrase or _join(matched_titles[:2], language)
        whole = _tenure_text(total, language, at_start=at_start)
        part = _tenure_text(matched, language, at_start=False)
        if language == "en":
            proposal = f"{whole} in IT, including {part} as {label}"
        else:
            proposal = f"{whole} w IT, w tym {part} jako {label}"
        # Podmieniamy tylko frazę z liczbą; reszta punktu („: projektował…”) zostaje.
        segment = point[found.start() : stop].strip()
    return Tenure(
        quote=point[found.start() : stop].strip(),
        figure=found.group(0).strip(),
        matched_months=matched,
        total_months=total,
        roles=tuple(listed[:ROLES_LISTED]),
        segment=segment,
        proposal=proposal,
    )


@dataclass(frozen=True)
class YearOnly:
    """Okres z samym rokiem w CV i daty z miesiącem z oryginału."""

    current: str
    original: tuple[str, ...]


def year_only(
    period: Optional[DateRange], source: str, role_text: str
) -> Optional[YearOnly]:
    """Rola z samym rokiem na starcie albo końcu, gdy oryginał ma miesiąc przy tym roku.

    Najpierw okres tej roli w oryginale (nazwa firmy albo stanowiska obok),
    potem każda data z miesiącem w tym roku — to szacunek z góry, dlatego
    uwaga tylko odsyła do oryginału i niczego nie wpisuje sama.
    """
    if period is None or not source.strip():
        return None
    years: list[int] = []
    if period.start[1] is None:
        years.append(period.start[0])
    if period.end is not None and period.end[1] is None:
        years.append(period.end[0])
    if not years:
        return None
    words = cv_source_dates._role_words(role_text)
    own: list[str] = []
    for found in cv_source_dates.date_ranges(source):
        if not words or not cv_source_dates._names_role(found, source, words):
            continue
        values = [found.start, *([found.end] if found.end else [])]
        if any(v[0] in years and v[1] is not None for v in values):
            text = " ".join(found.raw.split())
            if text not in own:
                own.append(text)
    if own:
        return YearOnly(period.raw, tuple(own[:3]))
    loose: list[str] = []
    for year in years:
        loose.extend(cv_source_dates.month_dates_in_year(source, year))
    return YearOnly(period.raw, tuple(loose[:3])) if loose else None


def swapped(period: DateRange) -> str:
    """„08.2021 – 09.2019” → „09.2019 – 08.2021” z tym samym łącznikiem."""
    raw = period.raw
    dates = list(
        re.finditer(rf"(?<![\w./-]){cv_source_dates._DATE}(?![\w/]|\.\d)", raw, re.I)
    )
    if len(dates) != 2:
        return raw
    a, b = dates
    return (
        raw[: a.start()]
        + b.group(0)
        + raw[a.end() : b.start()]
        + a.group(0)
        + raw[b.end() :]
    )
