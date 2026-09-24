"""Akademia — reguły sortowania zgłoszeń (czyste funkcje, bez bazy i modelu).

Decyzje Artura 24.09.2026:

* doświadczenie najwyżej ``max_experience_years`` lat, liczone OD KOŃCA
  STUDIÓW (praca przed ukończeniem studiów się nie liczy); osoba bez
  ukończonych studiów — cała praca;
* odrzucenia są pamiętane na zawsze (to robi ``academy_flow``).

Kryterium języka (polski na poziomie ojczystym albo biegłym) zastępuje
filtr po narodowości i po „polskim” imieniu i nazwisku, którego NIE
budujemy: to byłaby dyskryminacja ze względu na pochodzenie. Z tego samego
powodu nie liczymy wieku. Model nie dostaje narodowości z profilu i ma
zakaz wnioskowania z imienia.

Liczbę lat i werdykt liczy KOD. Luna (``academy_screening``) wyłącznie
wyciąga fakty z tekstu CV, gdy profil ich nie ma — każdy z cytatem, który
musi występować w CV. Werdykt ``skip`` to „Luna odłożyła”: osoba czeka na
zatwierdzenie przez człowieka, nikt nie jest odrzucany automatycznie.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Iterable, Optional

VERDICT_CALL = "call"
VERDICT_REVIEW = "review"
VERDICT_SKIP = "skip"

POLISH_NATIVE = "native"
POLISH_FLUENT = "fluent"
POLISH_BASIC = "basic"
POLISH_UNKNOWN = "unknown"
_POLISH_LEVELS = (POLISH_NATIVE, POLISH_FLUENT, POLISH_BASIC, POLISH_UNKNOWN)

# Absolwent kończy studia zwykle w lipcu — przy samym roku bierzemy 1 lipca.
_GRADUATION_MONTH = 7

_HIGHER_LEVELS = {"bachelor", "master", "engineer", "phd", "higher", "doctorate"}
_NOT_STUDIES = re.compile(
    r"podyplom|postgrad|\bmba\b|kurs|course|bootcamp|certyfik|certific|szkoleni|"
    r"training|liceum|technikum|high school|secondary|gimnazj|szkoła policealna|"
    r"policealn|workshop|warsztat",
    re.IGNORECASE,
)
_STUDIES_DEGREE = re.compile(
    r"licencja|magist|inżynier|inzynier|\bstudia\b|\bstudies\b|bachelor|master|"
    r"engineer|\bb\.?sc\b|\bm\.?sc\b|\bb\.?a\b|\bm\.?a\b|\bphd\b|doktor|doctor",
    re.IGNORECASE,
)
_STUDIES_SCHOOL = re.compile(
    r"uniwersytet|university|politechnika|polytechnic|szkoła wyższa|szkola wyzsza|"
    r"wyższa szkoła|wyzsza szkola|szkoła główna|szkola glowna|akademia|academy of|"
    r"college|uczelnia|institute of technology|school of economics",
    re.IGNORECASE,
)
_ONGOING = re.compile(
    r"w trakcie|obecnie|\bpresent\b|\bcurrent\b|\bongoing\b|\bnow\b|do dziś|do dzis|teraz",
    re.IGNORECASE,
)
_YEAR_MONTH = re.compile(r"^\s*(\d{4})(?:[-./](\d{1,2}))?")


@dataclass(frozen=True)
class StudiesFacts:
    """Wynik odczytu edukacji. ``end_year`` = koniec OSTATNICH ukończonych studiów."""

    end_year: Optional[int]
    still_studying: bool
    found_any: bool  # czy w ogóle była jakakolwiek pozycja edukacji
    quote: Optional[str] = None


@dataclass(frozen=True)
class WorkPeriod:
    start: tuple[int, int]  # (rok, miesiąc)
    end: tuple[int, int]
    quote: Optional[str] = None


@dataclass(frozen=True)
class WorkFacts:
    periods: tuple[WorkPeriod, ...]
    undated: int  # pozycje bez dat — gdy są, liczba lat jest niepewna
    found_any: bool


@dataclass(frozen=True)
class PolishFacts:
    level: str
    quote: Optional[str] = None


@dataclass
class ScreeningResult:
    verdict: str
    experience_years: Optional[float]
    reasons: list[dict[str, Any]] = field(default_factory=list)
    facts: dict[str, Any] = field(default_factory=dict)


# ── odczyt z profilu (ustrukturyzowane pola kandydata) ─────────────────────


def _as_list(value: Any) -> list[dict]:
    if isinstance(value, list):
        return [v for v in value if isinstance(v, dict)]
    if isinstance(value, dict):
        for key in ("items", "entries", "list"):
            if isinstance(value.get(key), list):
                return [v for v in value[key] if isinstance(v, dict)]
    return []


def _int_year(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if 1950 <= value <= 2100 else None
    if isinstance(value, str):
        match = _YEAR_MONTH.match(value)
        if match:
            year = int(match.group(1))
            return year if 1950 <= year <= 2100 else None
    return None


def is_higher_education(entry: dict) -> bool:
    """Czy pozycja edukacji to studia (a nie kurs, liceum, podyplomówka)."""
    level = str(entry.get("level") or "").strip().lower()
    degree = str(entry.get("degree") or "")
    school = str(entry.get("school") or "")
    field_ = str(entry.get("field") or "")
    text = f"{degree} {field_}"
    if _NOT_STUDIES.search(text) or level == "secondary":
        return False
    if level in _HIGHER_LEVELS:
        return True
    if _STUDIES_DEGREE.search(degree):
        return True
    return bool(_STUDIES_SCHOOL.search(school)) and not _NOT_STUDIES.search(school)


def studies_from_profile(education: Any, today: date) -> StudiesFacts:
    entries = _as_list(education)
    completed: list[int] = []
    studying = False
    for entry in entries:
        if not is_higher_education(entry):
            continue
        end_year = _int_year(entry.get("end_year")) or _int_year(entry.get("year"))
        start_year = _int_year(entry.get("start_year"))
        ongoing_text = " ".join(
            str(entry.get(k) or "") for k in ("end", "end_year", "year", "status")
        )
        if end_year is not None and end_year > today.year:
            studying = True
        elif end_year is not None:
            completed.append(end_year)
        elif _ONGOING.search(ongoing_text):
            studying = True
        elif start_year is not None and start_year >= today.year - 5:
            studying = True
    return StudiesFacts(
        end_year=max(completed) if completed else None,
        still_studying=studying,
        found_any=bool(entries),
    )


def parse_year_month(value: Any, today: date) -> Optional[tuple[int, int]]:
    """„2023-05”, „2023”, „05.2023”, „present” → (rok, miesiąc)."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if _ONGOING.search(text):
        return (today.year, today.month)
    match = _YEAR_MONTH.match(text)
    if match:
        year = int(match.group(1))
        month = int(match.group(2)) if match.group(2) else 1
        if 1950 <= year <= today.year and 1 <= month <= 12:
            return (year, month)
        return None
    alt = re.match(r"^\s*(\d{1,2})[-./](\d{4})", text)
    if alt:
        month, year = int(alt.group(1)), int(alt.group(2))
        if 1950 <= year <= today.year and 1 <= month <= 12:
            return (year, month)
    return None


def work_from_profile(experience: Any, today: date) -> WorkFacts:
    entries = _as_list(experience)
    periods: list[WorkPeriod] = []
    undated = 0
    for position, entry in enumerate(entries):
        start = parse_year_month(entry.get("start"), today)
        raw_end = entry.get("end")
        has_end = raw_end not in (None, "") and str(raw_end).strip() != ""
        end = parse_year_month(raw_end, today) if has_end else None
        if start is None or (has_end and end is None):
            undated += 1
            continue
        if end is None:
            if position > 0:
                # Reguła repo (``services/experience_end.py``): pusty koniec
                # dalej niż na pierwszej pozycji to praca PRZESZŁA o nieznanej
                # dacie końca — nie „do dziś”. Liczenie jej do dziś zawyżało
                # staż (stary staż + scalanie przedziałów = lata od najstarszego
                # startu) i dawało trwałe „nie”. Czas trwania jest nieznany,
                # więc pozycja idzie do „bez dat — sprawdź w rozmowie”.
                undated += 1
                continue
            # Pierwsza pozycja bez daty końca = praca trwająca.
            end = (today.year, today.month)
        if end < start:
            undated += 1
            continue
        periods.append(WorkPeriod(start=start, end=end))
    return WorkFacts(periods=tuple(periods), undated=undated, found_any=bool(entries))


def polish_from_profile(languages: Any) -> PolishFacts:
    for entry in _as_list(languages):
        code = str(entry.get("code") or "").strip().upper()
        name = _fold(str(entry.get("lang") or entry.get("name") or ""))
        if code != "PL" and name not in ("polski", "polish", "jezyk polski"):
            continue
        level = _fold(str(entry.get("level") or ""))
        if level in ("native", "ojczysty", "c2", "mother tongue", "rodzimy"):
            return PolishFacts(POLISH_NATIVE)
        if level in ("c1", "fluent", "biegly", "bieglu"):
            return PolishFacts(POLISH_FLUENT)
        if level in (
            "a1",
            "a2",
            "b1",
            "b2",
            "basic",
            "podstawowy",
            "sredniozaawansowany",
        ):
            return PolishFacts(POLISH_BASIC)
        return PolishFacts(POLISH_UNKNOWN)
    return PolishFacts(POLISH_UNKNOWN)


# ── odczyt z odpowiedzi modelu ─────────────────────────────────────────────


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").replace("ł", "l").replace("Ł", "L")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text).strip().casefold()


def quote_in_text(quote: Any, text: str) -> bool:
    """Cytat modelu musi występować w CV (po normalizacji białych znaków)."""
    if not isinstance(quote, str) or len(quote.strip()) < 3:
        return False
    return _fold(quote) in _fold(text)


# Cytat musi DOWODZIĆ faktu, nie tylko występować w CV: „Specjalista” nie
# dowodzi, że praca zaczęła się w 2010, a „język polski” — że polski jest
# podstawowy. Bez tego model mógł dopisać do dowolnego fragmentu datę albo
# poziom, a werdykt „skip” kończy się trwałym wykluczeniem.
_POLISH_WORD = re.compile(r"polsk|polish|\bpl\b")
_POLISH_BASIC_LEVEL = re.compile(
    r"\b[ab][12]\b|podstaw|basic|elementar|beginner|komunikatyw|intermediate|"
    r"sredni|srednio|conversational|limited|ograniczon"
)


def quote_has_year(quote: Any, year: Optional[int]) -> bool:
    """Czy cytat zawiera dany rok (samodzielną liczbą, nie częścią innej)."""
    if year is None or not isinstance(quote, str):
        return False
    return re.search(rf"(?<!\d){year}(?!\d)", quote) is not None


def quote_proves_polish(quote: Any, level: str) -> bool:
    """Cytat o polskim musi mówić o języku polskim; „podstawowy” — także o poziomie."""
    if not isinstance(quote, str):
        return False
    folded = _fold(quote)
    if not _POLISH_WORD.search(folded):
        return False
    if level == POLISH_BASIC:
        return _POLISH_BASIC_LEVEL.search(folded) is not None
    return True


def facts_from_model(
    parsed: Any, cv_text: str, today: date
) -> tuple[Optional[StudiesFacts], Optional[WorkFacts], Optional[PolishFacts]]:
    """Fakty z JSON-a modelu; pozycja bez cytatu obecnego w CV odpada."""
    if not isinstance(parsed, dict):
        return None, None, None

    polish: Optional[PolishFacts] = None
    raw_polish = parsed.get("polish")
    if isinstance(raw_polish, dict):
        level = str(raw_polish.get("level") or "").strip().lower()
        quote = raw_polish.get("quote")
        if (
            level in _POLISH_LEVELS
            and level != POLISH_UNKNOWN
            and quote_in_text(quote, cv_text)
            and quote_proves_polish(quote, level)
        ):
            polish = PolishFacts(level, quote.strip()[:300])
        else:
            polish = PolishFacts(POLISH_UNKNOWN)

    studies: Optional[StudiesFacts] = None
    raw_education = parsed.get("education")
    if isinstance(raw_education, list):
        completed: list[tuple[int, str]] = []
        studying = False
        for item in raw_education:
            if not isinstance(item, dict) or item.get("kind") != "higher":
                continue
            if not quote_in_text(item.get("quote"), cv_text):
                continue
            if item.get("completed") is False:
                studying = True
                continue
            end_year = _int_year(item.get("end_year"))
            if end_year is None:
                continue
            if not quote_has_year(item.get("quote"), end_year):
                # Rok końca studiów bez tego roku w cytacie — nie dowiedziony.
                continue
            if end_year > today.year:
                studying = True
            else:
                completed.append((end_year, str(item.get("quote")).strip()[:300]))
        best = max(completed) if completed else None
        studies = StudiesFacts(
            end_year=best[0] if best else None,
            still_studying=studying,
            found_any=bool(raw_education),
            quote=best[1] if best else None,
        )

    work: Optional[WorkFacts] = None
    raw_work = parsed.get("work")
    if isinstance(raw_work, list):
        periods: list[WorkPeriod] = []
        undated = 0
        for item in raw_work:
            if not isinstance(item, dict) or not quote_in_text(
                item.get("quote"), cv_text
            ):
                continue
            start = parse_year_month(item.get("start"), today)
            raw_end = item.get("end") or "present"
            end = parse_year_month(raw_end, today)
            if start is None or end is None or end < start:
                undated += 1
                continue
            quote = item.get("quote")
            ongoing = _ONGOING.search(str(raw_end)) is not None
            if not quote_has_year(quote, start[0]) or (
                not ongoing and not quote_has_year(quote, end[0])
            ):
                # Daty pracy muszą stać w cytacie — inaczej model mógłby
                # dopisać je do dowolnego fragmentu CV („Specjalista”).
                undated += 1
                continue
            periods.append(WorkPeriod(start, end, str(item.get("quote")).strip()[:300]))
        work = WorkFacts(
            periods=tuple(periods), undated=undated, found_any=bool(raw_work)
        )

    return studies, work, polish


# ── liczenie i werdykt ─────────────────────────────────────────────────────


def _month_index(year_month: tuple[int, int]) -> int:
    return year_month[0] * 12 + (year_month[1] - 1)


def work_months_after(
    periods: Iterable[WorkPeriod], cutoff: Optional[tuple[int, int]]
) -> int:
    """Suma miesięcy pracy (przedziały scalone), liczona od ``cutoff`` włącznie."""
    floor = _month_index(cutoff) if cutoff else None
    months: set[int] = set()
    for period in periods:
        start = _month_index(period.start)
        end = _month_index(period.end)
        if floor is not None:
            start = max(start, floor)
        for idx in range(start, end + 1):
            months.add(idx)
    return len(months)


def experience_years(
    studies: StudiesFacts, work: WorkFacts
) -> tuple[Optional[float], str]:
    """(lata doświadczenia, podstawa). ``None`` = nie da się policzyć."""
    if work.undated and not work.periods:
        return None, "unknown"
    cutoff = (studies.end_year, _GRADUATION_MONTH) if studies.end_year else None
    months = work_months_after(work.periods, cutoff)
    basis = "after_studies" if cutoff else "all_work"
    return round(months / 12, 1), basis


def _pick(profile: Any, model: Any, has_profile: bool) -> Any:
    return profile if has_profile or model is None else model


def evaluate(
    *,
    education: Any,
    experience: Any,
    languages: Any,
    model_parsed: Any,
    cv_text: str,
    max_experience_years: int,
    require_polish: bool,
    today: date,
    model_error: Optional[str] = None,
) -> ScreeningResult:
    """Werdykt sortowania: ``call`` / ``review`` / ``skip`` z powodami po polsku.

    Profil wygrywa z modelem (to zweryfikowane dane z parsera CV); model
    uzupełnia wyłącznie to, czego w profilu nie ma.
    """
    p_studies = studies_from_profile(education, today)
    p_work = work_from_profile(experience, today)
    p_polish = polish_from_profile(languages)
    m_studies, m_work, m_polish = facts_from_model(model_parsed, cv_text or "", today)

    has_profile_studies = p_studies.end_year is not None or p_studies.still_studying
    studies = _pick(p_studies, m_studies, has_profile_studies)
    work = _pick(p_work, m_work, bool(p_work.periods))
    polish = (
        p_polish if p_polish.level != POLISH_UNKNOWN or m_polish is None else m_polish
    )

    sources = {
        "studies": "profile" if studies is p_studies else "luna",
        "work": "profile" if work is p_work else "luna",
        "polish": "profile" if polish is p_polish else "luna",
    }

    years, basis = experience_years(studies, work)
    # CV bez żadnej pracy, ale też bez odczytanej edukacji i bez tekstu —
    # nie wiemy nic, więc „do decyzji”, a nie 0 lat.
    if (
        years == 0
        and not work.found_any
        and not studies.found_any
        and not (cv_text or "").strip()
    ):
        years, basis = None, "unknown"

    reasons: list[dict[str, Any]] = []
    skip = False
    unknown = False

    if years is None:
        unknown = True
        reasons.append(
            {
                "code": "experience_unknown",
                "text": "Nie da się policzyć doświadczenia — brak dat w CV.",
            }
        )
    elif years > max_experience_years:
        skip = True
        reasons.append(
            {
                "code": "experience_over",
                "text": _experience_text(years, basis, studies)
                + f" — limit {max_experience_years} lat.",
            }
        )
    else:
        reasons.append(
            {
                "code": "experience_ok",
                "text": _experience_text(years, basis, studies) + ".",
            }
        )
    if work.undated and years is not None and not skip:
        unknown = True
        reasons.append(
            {
                "code": "experience_partial",
                "text": f"{work.undated} stanowisk(a) bez dat — sprawdź w rozmowie.",
            }
        )

    if require_polish:
        if polish.level in (POLISH_NATIVE, POLISH_FLUENT):
            label = "ojczysty" if polish.level == POLISH_NATIVE else "biegły"
            reasons.append(
                {
                    "code": "polish_ok",
                    "text": f"Polski: {label}.",
                    "quote": polish.quote,
                }
            )
        elif polish.level == POLISH_BASIC:
            skip = True
            reasons.append(
                {
                    "code": "polish_basic",
                    "text": "Polski poniżej poziomu biegłego — praca wymaga rozmów po polsku.",
                    "quote": polish.quote,
                }
            )
        else:
            unknown = True
            reasons.append(
                {
                    "code": "polish_unknown",
                    "text": "CV nie mówi, na jakim poziomie zna polski.",
                }
            )

    if model_error:
        unknown = True
        reasons.append(
            {
                "code": "luna_unavailable",
                "text": "Luna nie odpowiedziała — oceń ręcznie.",
            }
        )

    verdict = VERDICT_SKIP if skip else VERDICT_REVIEW if unknown else VERDICT_CALL
    facts = {
        "studies_end_year": studies.end_year,
        "still_studying": studies.still_studying,
        "studies_quote": studies.quote,
        "experience_years": years,
        "experience_basis": basis,
        "polish": polish.level,
        "sources": sources,
    }
    return ScreeningResult(
        verdict=verdict, experience_years=years, reasons=reasons, facts=facts
    )


def years_label(years: float) -> str:
    """„1 rok”, „3 lata”, „5 lat”, „2,5 roku” — polska odmiana."""
    value = f"{years:.1f}".rstrip("0").rstrip(".").replace(".", ",")
    if "," in value:
        return f"{value} roku"
    whole = int(value)
    if whole == 1:
        return "1 rok"
    if whole % 10 in (2, 3, 4) and whole % 100 not in (12, 13, 14):
        return f"{whole} lata"
    return f"{whole} lat"


def _experience_text(years: float, basis: str, studies: StudiesFacts) -> str:
    if basis == "after_studies":
        return f"{years_label(years)} pracy po studiach (koniec {studies.end_year})"
    if studies.still_studying:
        return f"{years_label(years)} pracy, studiuje"
    return f"{years_label(years)} pracy, bez ukończonych studiów"
