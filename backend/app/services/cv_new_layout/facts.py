"""Czyste funkcje faktów z CV: języki, certyfikaty, daty ról, lata, wykształcenie.

Liczby bez zaokrąglania w górę: data bez miesiąca to „ok. N lat” w dół.
„Dziś” przychodzi z zewnątrz jako ułamek roku (`year_fraction(business_today())`),
nigdy z zegara w tej warstwie.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date
from typing import Callable, Optional, Sequence

from app.services.cv_new_layout.labels import counted, labels_for

# ---------- języki ----------
CEFR = ("A1", "A2", "B1", "B2", "C1", "C2")
_NATIVE = ("ojczyst", "native", "dwujęzycz", "bilingual", "mother tongue")

LANGUAGE_CODES = {
    "polski": "PL",
    "angielski": "EN",
    "niemiecki": "DE",
    "francuski": "FR",
    "hiszpański": "ES",
    "rosyjski": "RU",
    "włoski": "IT",
    "ukraiński": "UK",
    "czeski": "CS",
    "słowacki": "SK",
    "niderlandzki": "NL",
    "holenderski": "NL",
    "szwedzki": "SV",
    "norweski": "NO",
    "duński": "DA",
    "fiński": "FI",
    "portugalski": "PT",
    "węgierski": "HU",
    "rumuński": "RO",
    "litewski": "LT",
    "łotewski": "LV",
    "estoński": "ET",
    "białoruski": "BE",
    "bułgarski": "BG",
    "chorwacki": "HR",
    "serbski": "SR",
    "słoweński": "SL",
    "grecki": "EL",
    "turecki": "TR",
    "arabski": "AR",
    "hebrajski": "HE",
    "chiński": "ZH",
    "japoński": "JA",
    "koreański": "KO",
    "hindi": "HI",
    "perski": "FA",
    "azerski": "AZ",
    "wietnamski": "VI",
    "łacina": "LA",
    "esperanto": "EO",
    "kantoński": "YUE",
    "persian": "FA",
    "farsi": "FA",
    "azari": "AZ",
    "azerbaijani": "AZ",
    "vietnamese": "VI",
    "latin": "LA",
    "cantonese": "YUE",
    "polish": "PL",
    "english": "EN",
    "german": "DE",
    "french": "FR",
    "spanish": "ES",
    "russian": "RU",
    "italian": "IT",
    "ukrainian": "UK",
    "czech": "CS",
    "slovak": "SK",
    "dutch": "NL",
    "swedish": "SV",
    "norwegian": "NO",
    "danish": "DA",
    "finnish": "FI",
    "portuguese": "PT",
    "hungarian": "HU",
    "romanian": "RO",
    "lithuanian": "LT",
    "latvian": "LV",
    "estonian": "ET",
    "belarusian": "BE",
    "bulgarian": "BG",
    "croatian": "HR",
    "serbian": "SR",
    "slovenian": "SL",
    "greek": "EL",
    "turkish": "TR",
    "arabic": "AR",
    "hebrew": "HE",
    "chinese": "ZH",
    "japanese": "JA",
    "korean": "KO",
}


# „Polski - ojczysty”, „English -B2” (spacja tylko przed myślnikiem), „Niemiecki: B1”
_LANG_SPLIT = re.compile(r"\s+[-–—]\s*|\s*:\s+")
# „Angielski B2” — poziom CEFR na końcu bez myślnika
_LANG_TRAILING_CEFR = re.compile(
    r"^(.*?\S)\s+([ABC][12](?:\s*/\s*[ABC][12])?)\.?$", re.I
)


def lang_parts(entry: str) -> tuple[str, str]:
    """„Polski - ojczysty” → („Polski”, „ojczysty”); także półpauza, pauza i dwukropek
    („polski – ojczysty” z edytora), bez tego kod języka brał dwie pierwsze litery („PO”)."""
    parts = _LANG_SPLIT.split((entry or "").strip(), maxsplit=1)
    if len(parts) == 1:
        # „Polish-fluent.” bez spacji (#40503) — dzieli tylko po znanej nazwie języka,
        # żeby „Serbo-Croatian” zostało w całości
        left, dash, right = parts[0].partition("-")
        trailing = _LANG_TRAILING_CEFR.match(parts[0])
        if dash and left.strip().lower() in LANGUAGE_CODES:
            parts = [left, right]
        elif trailing:
            parts = [trailing.group(1), trailing.group(2)]
    return parts[0].strip(), (
        parts[1].strip().rstrip(".").strip() if len(parts) > 1 else ""
    )


def lang_level(level: str, language: str = "pl") -> tuple[Optional[int], str]:
    """(stopień 1–6 albo None, etykieta). Ojczysty i dwujęzyczny = ojczysty;
    „C1/C2” zostaje w całości; inny opis zostaje słowami."""
    low = (level or "").lower()
    if any(k in low for k in _NATIVE):
        return 6, labels_for(language)["native"]
    m = re.search(r"\b([abc][12])(?:\s*/\s*([abc][12]))?\b", low)
    if not m:
        return None, level or ""
    label = m.group(1).upper() + (f"/{m.group(2).upper()}" if m.group(2) else "")
    return CEFR.index(m.group(1).upper()) + 1, label


def lang_code(name: str) -> str:
    """Kod języka; dopisek w nawiasie („English (reading/listening)”) nie zmienia kodu."""
    base = re.sub(r"\s*\(.*?\)\s*", " ", name or "").strip()
    return LANGUAGE_CODES.get(base.lower(), base[:2].upper())


# ---------- certyfikaty ----------
@dataclass(frozen=True)
class Cert:
    name: str
    issuer: str
    year: str


def cert_parts(entry: str) -> Cert:
    """„Nazwa - Wystawca (2022)” albo „Nazwa (2022)”; opis kursu z małej litery
    nie jest wystawcą („PMP - kurs przygotowawczy w …”)."""
    text = (entry or "").strip()
    m = re.match(r"(.*?)\s+-\s+([^-]+?)\s*(?:\((\d{4})\))?$", text)
    if m:
        who = m.group(2)
        if who[:1].islower() and len(who.split()) > 3:
            return Cert(f"{m.group(1)} – {who}", "", m.group(3) or "")
        return Cert(m.group(1), who, m.group(3) or "")
    m = re.match(r"(.*?)\s*\((\d{4})\)$", text)
    if m:
        return Cert(m.group(1), "", m.group(2))
    return Cert(text, "", "")


def certs_by_year(entries: Sequence[str]) -> list[Cert]:
    """Najnowsze pierwsze; bez roku na końcu, w kolejności z CV."""
    rows = [cert_parts(c) for c in entries]
    dated = sorted((r for r in rows if r.year), key=lambda r: -int(r.year))
    return dated + [r for r in rows if not r.year]


# ---------- daty ról ----------
# Słowa „do dziś” z CV i generatora; ta sama lista co `PRESENT` w edytorze
# (`frontend/src/lib/cv-new-layout-form.ts`) plus odmiany — nierozpoznany koniec
# zakresu daje 1 miesiąc (zgłoszenie 25.11.2026: „03.2023 – currently”).
CURRENT_WORD = re.compile(
    r"\b(?:obecnie|aktualnie|teraz|nadal|dziś|dzis|dzisiaj|present|current(?:ly)?|now"
    r"|today|ongoing|to date|till date|until now)\b",
    re.I,
)


def year_fraction(day: date) -> float:
    """Data jako ułamek roku: 2026-11-22 → 2026 + (10 + 21/30) / 12."""
    days = calendar.monthrange(day.year, day.month)[1]
    return day.year + (day.month - 1 + (day.day - 1) / days) / 12


@dataclass(frozen=True)
class Span:
    start: Optional[float]
    end: Optional[float]
    months_known: bool


def parse_dates(text: str, now: float) -> Span:
    """Każda strona zakresu osobno: „MM.YYYY”, „YYYY” albo „obecnie” (bywa
    „2013 - 12.2017”). Sam rok: początek = styczeń, koniec = grudzień — tak samo
    jak edytor (`client-form-years.ts`) i staż do Worda (`cv_tenure_checks`);
    wcześniej „09.2018 - 2019” wychodziło 4 mies. (pętla jakości 25.11.2026)."""
    sides = [
        x.strip()
        # zakres: myślnik ze spacjami albo półpauza/pauza; myślnik bez spacji tylko po roku
        # („05.2025-obecnie”, #39655) — „11-2009” to miesiąc i rok (#38606)
        for x in re.split(
            r"\s+-\s+|\s*[–—]\s*|(?<=(?:19|20)\d{2})\s*-\s*",
            (text or "").strip().lower(),
        )
        if x.strip()
    ]

    def side(t: str, is_end: bool) -> tuple[Optional[float], bool]:
        if CURRENT_WORD.search(t):
            return now, True
        m = re.search(r"(\d{1,2})[./-](\d{4})", t)
        if m:
            y, mo = int(m.group(2)), int(m.group(1))
            return (y + mo / 12 if is_end else y + (mo - 1) / 12), True
        m = re.search(r"(?:19|20)\d{2}", t)
        if not m:
            return None, False
        # sam rok: początek = styczeń, koniec = grudzień (jak edytor i staż do Worda)
        return float(m.group(0)) + (1 if is_end else 0), False

    if not sides:
        return Span(None, None, False)
    if len(sides) == 1 and CURRENT_WORD.search(sides[0]):
        return Span(None, now, False)  # „obecnie” bez początku: początek nieznany
    a, ka = side(sides[0], False)
    if a is None:
        return Span(None, None, False)
    if len(sides) == 1:
        return Span(a, a + (1 / 12 if ka else 1), ka)
    b, kb = side(sides[1], True)
    if b is None:
        return Span(a, a + (1 / 12 if ka else 1), ka)
    return Span(a, min(b, now) if b > a else b, ka and kb)


def duration_text(span: Span, language: str = "pl") -> str:
    """„1 rok 5 mies.”; daty bez miesięcy → „ok. 3 lata” (pełne lata w dół)."""
    lab = labels_for(language)
    if span.start is None or span.end is None:
        return ""
    if span.months_known:
        months = max(round((span.end - span.start) * 12), 1)
        years, rest = divmod(months, 12)
        parts = ([counted(language, "year", years)] if years else []) + (
            [f"{rest} {lab['months_short']}"] if rest else []
        )
        return " ".join(parts)
    return f"{lab['about']} {counted(language, 'year', max(int(span.end - span.start), 1))}"


def union_years(spans: Sequence[tuple[float, float]]) -> float:
    """Suma przedziałów bez podwójnego liczenia nakładek."""
    total, cur = 0.0, None
    for a, b in sorted(spans):
        if cur is None or a > cur[1]:
            if cur is not None:
                total += cur[1] - cur[0]
            cur = [a, b]
        else:
            cur[1] = max(cur[1], b)
    if cur is not None:
        total += cur[1] - cur[0]
    return total


def has_term(text: str, term: str) -> bool:
    return (
        re.search(
            r"(?<![\w])" + re.escape(term.lower()) + r"(?![\w])", (text or "").lower()
        )
        is not None
    )


def years_with(
    roles: Sequence[tuple[Span, str]], predicate: Callable[[str], bool]
) -> float:
    """Lata ról (Span, tekst roli), których tekst spełnia warunek — bez nakładek."""
    return union_years(
        [
            (s.start, s.end)
            for s, txt in roles
            if s.start is not None and s.end is not None and predicate(txt)
        ]
    )


# ---------- wykształcenie ----------
_EDU_RANK = (  # (ranga, wzorce w nazwie tytułu/kierunku); remis rozstrzyga kolejność z CV
    (5, ("doktor", "phd", "dr ")),
    (4, ("magister", "mgr", "master", "msc", "mba")),
    (3, ("inżynier", "inż", "engineer", "licencjat", "bachelor", "bsc", "ba ")),
    (2, ("technik", "studium", "policealn")),
    (1, ("liceum", "technikum", "szkoła średnia", "high school")),
)
_UNFINISHED = (
    "przerwan",
    "nieukończon",
    "niezakończon",
    "w trakcie",
    "część zajęciowa",
    "absolutorium",
    "unfinished",
    "incomplete",
    "not completed",
    "ongoing",
)


def edu_rank(degree: str, institution: str) -> int:
    txt = f" {degree or ''} {institution or ''} ".lower()
    if any(k in txt for k in _UNFINISHED):
        return 0
    return next((r for r, keys in _EDU_RANK if any(k in txt for k in keys)), 0)


_LEVEL = re.compile(
    r"^(magister inżynier|mgr inż\.?|magister|mgr|inżynier|inż\.?|licencjat|doktor|dr|master|bachelor|engineer|mba)$",
    re.I,
)


def split_degree(title: str) -> tuple[str, str]:
    """„Informatyka - magister inżynier” → („Informatyka”, „Magister inżynier”);
    bez rozpoznanego stopnia całość to kierunek."""
    parts = [x.strip() for x in re.split(r"\s+-\s+|,\s*", title or "") if x.strip()]
    levels = [x for x in parts if _LEVEL.match(x)]
    if not levels:
        return title, ""
    field_ = ", ".join(x for x in parts if x not in levels)
    d = levels[0]
    return (field_ or title), d[0].upper() + d[1:]


def last_year(dates: str) -> str:
    years = re.findall(r"(?:19|20)\d{2}", dates or "")
    return years[-1] if years else ""
