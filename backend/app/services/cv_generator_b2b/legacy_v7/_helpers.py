"""Frozen copy of the post-processing helpers used by the 2bc6b14f pipeline.

Verbatim from ``standalone_service`` at the baseline, so the legacy pipeline
reproduces the old normalisation (industry "IT" default), the old years-of-
experience headline (rounded interval union, tech/company-bound claims left
alone) and the old warning-only fabrication checks. ``StandaloneGenerationError``
is imported so the API keeps catching the same class.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from app.services.cv_generator_b2b.champion_builder import ChampionProfileForPrompt
from app.services.cv_generator_b2b.docx_renderer import (
    compile_keyword_patterns,
    highlight_spans,
)
from app.services.cv_generator_b2b.standalone_service import (  # noqa: F401
    StandaloneGenerationError,
)
from app.core.scheduling import local_now


# Letters NFKD cannot decompose to ASCII — transliterate manually so the ASCII
# fallback renders "Łukasz" → "Lukasz" instead of dropping it to "ukasz".
_TRANSLIT = str.maketrans({"ł": "l", "Ł": "L", "đ": "d", "Đ": "D", "ø": "o", "Ø": "O"})


# Claude picks up the prompt's typographic en-dashes (date examples like
# "MM.YYYY – MM.YYYY") and sprinkles em/en dashes across the generated CV.
# Recruiters want plain ASCII hyphens, so fold every dash variant down to "-".
_DASH_TRANS = {
    ord("‐"): "-",  # hyphen
    ord("‑"): "-",  # non-breaking hyphen
    ord("‒"): "-",  # figure dash
    ord("–"): "-",  # en dash
    ord("—"): "-",  # em dash
    ord("―"): "-",  # horizontal bar
    ord("−"): "-",  # minus sign
}


def _normalize_dashes(value: Any) -> Any:
    """Recursively replace typographic dashes with plain hyphens in strings."""
    if isinstance(value, str):
        return value.translate(_DASH_TRANS)
    if isinstance(value, list):
        return [_normalize_dashes(v) for v in value]
    if isinstance(value, dict):
        return {k: _normalize_dashes(v) for k, v in value.items()}
    return value


def _str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(x).strip() for x in value if x is not None and str(x).strip()]


def _normalize_candidate_data(data: Any, fallback_name: str | None) -> dict[str, Any]:
    """Coerce the Claude JSON into the exact shape the DOCX renderer needs.

    The renderer indexes hard keys (``edu["dates"]``, ``job["company"]`` …) —
    a missing key in an otherwise fine response used to surface as a raw 500.
    Defaults are injected here so render never KeyErrors.
    """
    if not isinstance(data, dict):
        raise StandaloneGenerationError(
            code="ai_failed",
            message=(
                "Claude zwrócił JSON o niepoprawnej strukturze "
                f"(oczekiwano obiektu, otrzymano {type(data).__name__})."
            ),
        )

    out: dict[str, Any] = {}
    out["name"] = str(data.get("name") or fallback_name or "Kandydat").strip()
    out["first_name"] = str(data.get("first_name") or "").strip()
    out["position"] = str(data.get("position") or "").strip()
    out["why_points"] = _str_list(data.get("why_points"))

    education: list[dict[str, str]] = []
    for edu in data.get("education") or []:
        if not isinstance(edu, dict):
            continue
        education.append(
            {
                "dates": str(edu.get("dates") or "").strip(),
                "institution": str(edu.get("institution") or "").strip(),
                "degree": str(edu.get("degree") or "").strip(),
                "location": str(edu.get("location") or "").strip(),
            }
        )
    out["education"] = [e for e in education if e["institution"] or e["degree"]]

    skills: list[dict[str, str]] = []
    for cat in data.get("skills") or []:
        if isinstance(cat, dict):
            label = str(cat.get("label") or "").strip()
            content = str(cat.get("content") or "").strip()
        else:
            label, content = "", str(cat).strip()
        if content:
            skills.append({"label": label, "content": content})
    out["skills"] = skills

    out["certifications"] = _str_list(data.get("certifications"))
    out["languages"] = _str_list(data.get("languages"))

    experience: list[dict[str, Any]] = []
    for job in data.get("experience") or []:
        if not isinstance(job, dict):
            continue
        experience.append(
            {
                "dates": str(job.get("dates") or "").strip(),
                "company": str(job.get("company") or "").strip(),
                # D1 (13.10.2026): branża tylko ze źródła; bez niej puste pole,
                # a nie zgadnięte „IT" (blind drukuje wtedy samo „Firma").
                "industry": str(job.get("industry") or "").strip(),
                "position": str(job.get("position") or "").strip(),
                "responsibilities": _str_list(job.get("responsibilities")),
                "technologies": _str_list(job.get("technologies")),
            }
        )
    out["experience"] = [
        j for j in experience if j["company"] or j["position"] or j["responsibilities"]
    ]

    out["warnings"] = _str_list(data.get("warnings"))
    return _normalize_dashes(out)


# Readability: the "Technologie:" line for a long role can balloon to 20+
# entries. Keep the most relevant 12 — champion must/nice-to-have first.
_MAX_TECHNOLOGIES_PER_ROLE = 12


def _cap_role_technologies(
    candidate_data: dict[str, Any], highlight_keywords: list[str] | None
) -> None:
    patterns = compile_keyword_patterns(highlight_keywords or [])
    for job in candidate_data.get("experience", []):
        techs = job.get("technologies") or []
        if len(techs) <= _MAX_TECHNOLOGIES_PER_ROLE:
            continue
        prioritized = [t for t in techs if patterns and highlight_spans(t, patterns)]
        rest = [t for t in techs if t not in prioritized]
        kept = set((prioritized + rest)[:_MAX_TECHNOLOGIES_PER_ROLE])
        # Preserve the model's original ordering within the kept subset.
        job["technologies"] = [t for t in techs if t in kept]


_ONGOING_RE = re.compile(r"obecnie|currently|present|now", re.IGNORECASE)


_DATE_TOKEN_RE = re.compile(r"(?:(\d{1,2})\.)?(\d{4})")


# A 1-month "overlap" is usually just a handover month — don't cry wolf.
_MIN_OVERLAP_MONTHS = 2


def _parse_date_range(dates: str) -> tuple[int, int] | None:
    """Parse "MM.YYYY – MM.YYYY" / "YYYY" / "MM.YYYY – obecnie" into a
    (start, end) pair of absolute month indexes. Returns None when the
    string doesn't carry parseable dates."""
    if not dates or not dates.strip():
        return None
    tokens = [
        (int(m.group(2)), int(m.group(1)) if m.group(1) else None)
        for m in _DATE_TOKEN_RE.finditer(dates)
    ]
    if not tokens:
        return None
    start_year, start_month = tokens[0]
    start = start_year * 12 + ((start_month or 1) - 1)
    if _ONGOING_RE.search(dates):
        end = 9999 * 12
    else:
        end_year, end_month = tokens[-1]
        end = end_year * 12 + ((end_month or 12) - 1)
    if end < start:
        return None
    return (start, end)


def _duration_bounds(dates: str) -> tuple[int, int] | None:
    """Przedział roli do SUMY stażu (nagłówek lat).

    Runda 10 (F19): sam rok bez miesiąca liczony był od stycznia do grudnia,
    więc oba lata graniczne wchodziły w całości — źródło „2021–2026, 5 lat”
    dawało w CV „6 lat”. Rok bez miesiąca to niepewność, więc bierzemy środek
    roku: start z samego roku = lipiec, koniec z samego roku = czerwiec
    („2019–2021” = 24 miesiące, nie 36). Rola jednoroczna („2020”) i przedział,
    który by się odwrócił, zostają przy pełnym zakresie z ``_parse_date_range``.
    Daty z miesiącami liczą się bez zmian.
    """
    rng = _parse_date_range(dates)
    if rng is None:
        return None
    tokens = [
        (int(m.group(2)), int(m.group(1)) if m.group(1) else None)
        for m in _DATE_TOKEN_RE.finditer(dates)
    ]
    ongoing = bool(_ONGOING_RE.search(dates))
    if len(tokens) < 2 and not ongoing:
        return rng
    start, end = rng
    start_year, start_month = tokens[0]
    if start_month is None:
        start = start_year * 12 + 6
    if not ongoing:
        end_year, end_month = tokens[-1]
        if end_month is None:
            end = end_year * 12 + 5
    if end < start:
        return rng
    return (start, end)


def _total_experience_years(experience: list[dict[str, Any]]) -> int | None:
    """Sum the candidate's actual time employed across all roles, in whole
    years. Intervals are merged so overlapping/parallel contracts (common in
    B2B) are counted once, and an ongoing role ("obecnie") is capped at the
    current month. Returns ``None`` when no role carries parseable dates.

    Claude is reliable at EXTRACTING dates but not at the arithmetic of summing
    them — it tends to round down ("ponad 4" for a 5-year candidate). Computing
    the figure here makes the why_points headline exact.
    """
    now = local_now()
    now_idx = now.year * 12 + (now.month - 1)
    intervals: list[tuple[int, int]] = []
    for job in experience or []:
        rng = _duration_bounds(job.get("dates") or "")
        if rng is None:
            continue
        start, end = rng
        end = min(end, now_idx)  # cap the "obecnie" sentinel at the current month
        if end >= start:
            intervals.append((start, end))
    if not intervals:
        return None

    intervals.sort()
    total_months = 0
    cur_start, cur_end = intervals[0]
    for start, end in intervals[1:]:
        if start <= cur_end + 1:  # overlapping or back-to-back → one stretch
            cur_end = max(cur_end, end)
        else:
            total_months += cur_end - cur_start + 1
            cur_start, cur_end = start, end
    total_months += cur_end - cur_start + 1

    years = round(total_months / 12)
    return years if years >= 1 else None


# A years-of-experience figure in a why_point ("Ponad 4 lata doświadczenia…").
# The optional approximate prefix is swallowed so it gets replaced by the exact
# figure (recruiter: "5 years must read 5, not 'over 4'"). A decimal figure
# ("4,5 roku") is matched whole: until 13.10.2026 the pattern took "5 roku" out
# of "4.5 roku" and the fix wrote "4.4 lata" (22 CVs in 30 days on production).
_YEARS_PHRASE_RE = re.compile(
    r"(?:ponad|powyżej|przeszło|niemal|prawie|blisko|około|ok\.?|~|"
    r"over|nearly|almost|about|more than)?\s*"
    r"(?<![\d.,])(\d+(?:[.,]\d+)?)(?:\s*[-–/]\s*\d+)?\+?\s*"
    r"(?:lata|lat|roku|rok|years|year|yrs|yr)\b",
    re.IGNORECASE,
)

# Staż ma najwyżej dwie cyfry. „Od 2023 roku" to data, nie staż — do 13.10.2026
# poprawka zamieniała ją na „od13 lat".
_MAX_TENURE_FIGURE = 99


def _tenure_figure(match: re.Match[str]) -> float | None:
    """Liczba lat z dopasowania albo ``None`` dla daty i nieczytelnej liczby."""
    try:
        value = float(match.group(1).replace(",", "."))
    except (TypeError, ValueError):
        return None
    return value if value <= _MAX_TENURE_FIGURE else None


def _polish_year_unit(years: int) -> str:
    if years == 1:
        return "rok"
    if 2 <= years % 10 <= 4 and not 12 <= years % 100 <= 14:
        return "lata"
    return "lat"


def _years_text(years: int, language: str) -> str:
    if language == "en":
        return f"{years} {'year' if years == 1 else 'years'}"
    return f"{years} {_polish_year_unit(years)}"


# Markers introducing the "w tym Y lat w [firmie]" sub-figure of a why_point.
# That figure is scoped to one company/chapter of the career, so the recompute
# must never land on it — only the clause BEFORE a marker is searched.
_SUBFIGURE_SPLIT_RE = re.compile(r"\sw tym\s|\sincluding\s|\sincl\.?\s", re.IGNORECASE)

# Ogólny staż kariery (jak v10, ``standalone_service._GENERIC_TENURE_*``):
# przed liczbą najwyżej „łącznie", po niej samo „doświadczenia (w IT)".
# „2 lata w SQL", „2.5 years combined experience across test automation"
# i „od 2023 roku" nie są stażem kariery i zostają, jak napisał model.
_GENERIC_TENURE_PREFIX_RE = re.compile(
    r"(?:łącznie|ogółem|total|a total of)?\s*", re.IGNORECASE
)
_GENERIC_TENURE_TAIL_RE = re.compile(
    r"\s*(?:doświadczenia(?:\s+(?:zawodowego|komercyjnego|łącznie))?"
    r"|(?:of\s+)?(?:(?:professional|work|total)\s+)?experience)"
    r"(?:\s+(?:w|in)\s+(?:IT|branży IT|the IT industry))?\s*[,.;:]?\s*",
    re.IGNORECASE,
)
# „N lat doświadczenia jako X" / „N years of experience as X": staż w roli X.
_ROLE_TENURE_LEAD_RE = re.compile(
    r"\s*(?:doświadczenia(?:\s+(?:zawodowego|komercyjnego))?"
    r"|(?:of\s+)?(?:(?:professional|work)\s+)?experience)(?=\s+(?:jako|as)\s)",
    re.IGNORECASE,
)


def _fix_experience_years(candidate_data: dict[str, Any], language: str) -> None:
    """Popraw liczbę lat w nagłówku kariery (pierwszy punkt z „doświadczenia").

    Model liczy staż z dat słabo („ponad 4" przy 5 latach), więc kod liczy go
    sam — ale nigdy nie dopisuje lat z cudzych ról (13.10.2026: „3 lata jako
    Data Engineer" przy roli kierownika sklepu stawało się „13 lat").

    * Ogólny staż („5 lat doświadczenia", „7 years of experience") — suma
      wszystkich ról.
    * „N lat doświadczenia jako X" — ``min(cała kariera, max(liczba modelu,
      role pasujące do X))``: liczba rośnie tylko wtedy, gdy potwierdzają to
      daty ról X, i nigdy ponad całą karierę. Brak pasującej roli albo ułamek,
      którego nie trzeba zmieniać = bez zmiany.
    * Wszystko inne („2 lata w SQL", „od 2023 roku", „2.5 years combined …")
      zostaje, jak napisał model; sprawdzają to bezpieczniki i kontrola AI.

    Szukamy tylko przed „w tym" / „including" — liczba po nim dotyczy jednej
    firmy.
    """
    experience = [
        job for job in candidate_data.get("experience") or [] if isinstance(job, dict)
    ]
    total = _total_experience_years(experience)
    if not total:
        return

    points = candidate_data.get("why_points") or []
    for i, point in enumerate(points):
        if not isinstance(point, str):
            continue
        low = point.lower()
        if "doświadcz" not in low and "experience" not in low:
            continue
        head = _SUBFIGURE_SPLIT_RE.split(point, maxsplit=1)[0]
        match = _YEARS_PHRASE_RE.search(head)
        if not match:
            continue
        figure = _tenure_figure(match)
        if figure is None or not _GENERIC_TENURE_PREFIX_RE.fullmatch(
            head[: match.start()]
        ):
            continue
        tail = head[match.end() :]
        if _GENERIC_TENURE_TAIL_RE.fullmatch(tail):
            years: float = total
        else:
            lead = _ROLE_TENURE_LEAD_RE.match(tail)
            scoped = (
                _scoped_years(tail[lead.end() :], experience, _company_keys(experience))
                if lead
                else None
            )
            if not scoped:
                continue
            years = min(total, max(figure, scoped))
        if years == figure and figure != int(figure):
            break  # ułamek modelu jest zgodny z datami — zostaje
        lead_space = match.group(0)[
            : len(match.group(0)) - len(match.group(0).lstrip())
        ]
        points[i] = (
            point[: match.start()]
            + lead_space
            + _years_text(int(round(years)), language)
            + point[match.end() :]
        )
        break


# Lata przypięte WPROST do roli albo firmy: „6 lat jako Backend Developer",
# „4 lata w Acme", „5 years as a Data Engineer". Łącznik musi stać zaraz po
# liczbie — „N lat doświadczenia jako…" to nagłówek kariery i należy do
# `_fix_experience_years` (zachowanie bazowe, nietknięte).
_SCOPED_ROLE_CONNECTOR_RE = re.compile(
    r"\s*(?:jako|as)\s+(?:(?:a|an)\s+)?", re.IGNORECASE
)
_SCOPED_COMPANY_CONNECTOR_RE = re.compile(r"\s*(?:w|we|u|at|in)\s+", re.IGNORECASE)
# Koniec frazy roli: przecinek/średnik/kropka albo kolejny łącznik („… w Acme",
# „… z Pythonem", „w tym …").
_SCOPED_PHRASE_END_RE = re.compile(
    r"[,;.()]|\s(?:w tym|including|incl\.?|w|we|u|z|ze|dla|oraz|i|at|in|with|for|and)\s",
    re.IGNORECASE,
)


def _scope_key(text: str) -> str:
    return re.sub(r"[^\w+#]+", " ", str(text or "").casefold()).strip()


def _company_keys(roles: list[dict[str, Any]]) -> list[str]:
    return sorted(
        {key for job in roles if len(key := _scope_key(job.get("company") or "")) >= 4},
        key=len,
        reverse=True,
    )


def _scoped_years(
    tail: str, roles: list[dict[str, Any]], companies: list[str]
) -> int | None:
    """Lata ról pasujących do frazy po liczbie: „jako X" (stanowisko zawiera X)
    albo „w/u/at Firma" (dokładnie ta firma). ``None`` = brak dopasowania albo
    niepełne daty — wtedy liczba zostaje, jak napisał model."""
    role = _SCOPED_ROLE_CONNECTOR_RE.match(tail)
    if role:
        rest = tail[role.end() :]
        end = _SCOPED_PHRASE_END_RE.search(rest)
        phrase = _scope_key(rest[: end.start()] if end else rest)
        if len(phrase) < 4:
            return None
        pattern = re.compile(rf"(?:^|\s){re.escape(phrase)}(?:\s|$)")
        matched = [
            job for job in roles if pattern.search(_scope_key(job.get("position")))
        ]
    else:
        company = _SCOPED_COMPANY_CONNECTOR_RE.match(tail)
        if not company:
            return None
        rest = _scope_key(tail[company.end() :])
        name = next(
            (c for c in companies if rest == c or rest.startswith(c + " ")), None
        )
        if name is None:
            return None
        matched = [job for job in roles if _scope_key(job.get("company")) == name]
    if not matched or any(
        _parse_date_range(str(job.get("dates") or "")) is None for job in matched
    ):
        return None
    return _total_experience_years(matched)


def _fix_scoped_years(candidate_data: dict[str, Any], language: str) -> None:
    """Przelicz z dat liczby lat przypięte do KONKRETNEJ roli albo firmy.

    Model nie zna dzisiejszej daty i liczył „obecnie" jak rok wcześniej
    („6 lat jako Backend Developer" przy roli od 01.2019), a bezpiecznik
    fabrykacji tylko ostrzegał — zła liczba zostawała w DOCX, HTML i kafelkach.
    Tu liczba jest nadpisywana wyłącznie sumą przedziałów PASUJĄCYCH ról:
    stanowisko zawiera frazę po „jako"/„as", albo firma jest dokładnie tą
    nazwą po „w"/„u"/„at". Brak dopasowania, fleksja („jako Developera") czy
    niepełne daty = liczba zostaje, jak napisał model. Dzięki temu poprawka
    nigdy nie dolicza lat z innej roli ani innej firmy. Daty („od 2023 roku")
    nie są liczbą lat i zostają.
    """
    roles = [
        job for job in candidate_data.get("experience") or [] if isinstance(job, dict)
    ]
    if not roles:
        return
    companies = _company_keys(roles)

    points = candidate_data.get("why_points") or []
    for i, point in enumerate(points):
        if not isinstance(point, str):
            continue

        def replace(match: re.Match[str]) -> str:
            if _tenure_figure(match) is None:
                return match.group(0)
            years = _scoped_years(match.string[match.end() :], roles, companies)
            if not years:
                return match.group(0)
            text = match.group(0)
            lead = text[: len(text) - len(text.lstrip())]
            return f"{lead}{_years_text(years, language)}"

        points[i] = _YEARS_PHRASE_RE.sub(replace, point)


def _certain_overlap_bounds(dates: str) -> tuple[int, int] | None:
    """Najwęższy przedział, który rola NA PEWNO obejmuje.

    Sam rok bez miesiąca to niepewność: „2017 – 2020” może kończyć się
    w styczniu 2020, a „2020 – 2026” zaczynać w grudniu 2020. Rok graniczny
    wspólny dla dwóch ról nie jest więc dowodem nakładania się okresów
    (zgłoszenie UAT M05-B07). Dla ostrzeżenia bierzemy start z samego roku
    jako grudzień, a koniec z samego roku jako styczeń; gdy to odwraca
    przedział (rola „2020”), zostaje pełny zakres z ``_parse_date_range``.
    """
    rng = _parse_date_range(dates)
    if rng is None:
        return None
    tokens = [
        (int(m.group(2)), int(m.group(1)) if m.group(1) else None)
        for m in _DATE_TOKEN_RE.finditer(dates)
    ]
    start, end = rng
    start_year, start_month = tokens[0]
    if start_month is None:
        start = start_year * 12 + 11
    if not _ONGOING_RE.search(dates):
        end_year, end_month = tokens[-1]
        if end_month is None:
            end = end_year * 12
    if end < start:
        return rng
    return (start, end)


def _date_overlap_warnings(candidate_data: dict[str, Any], language: str) -> list[str]:
    """Informational check: overlapping employment periods are common in B2B
    (parallel contracts), but the recruiter should verify them consciously
    before the client spots them at the interview. Never blocks generation
    and never alters the CV itself."""
    roles: list[tuple[str, str, tuple[int, int]]] = []
    for job in candidate_data.get("experience", []):
        rng = _certain_overlap_bounds(job.get("dates") or "")
        if rng is not None:
            label = job.get("company") or job.get("position") or "?"
            roles.append((label, job.get("dates") or "", rng))

    issues: list[str] = []
    for i in range(len(roles)):
        for j in range(i + 1, len(roles)):
            name_a, dates_a, (start_a, end_a) = roles[i]
            name_b, dates_b, (start_b, end_b) = roles[j]
            overlap = min(end_a, end_b) - max(start_a, start_b) + 1
            if overlap >= _MIN_OVERLAP_MONTHS:
                if language == "en":
                    issues.append(
                        f"VERIFY: overlapping employment periods: "
                        f"'{name_a}' ({dates_a}) and '{name_b}' ({dates_b})"
                    )
                else:
                    issues.append(
                        f"WERYFIKUJ: nakładające się okresy zatrudnienia: "
                        f"'{name_a}' ({dates_a}) i '{name_b}' ({dates_b})"
                    )
    if len(issues) > 3:
        more = len(issues) - 3
        issues = issues[:3]
        issues.append(
            f"… i {more} kolejnych nakładających się par"
            if language != "en"
            else f"… and {more} more overlapping pairs"
        )
    return issues


def _norm_for_guard(text: str) -> str:
    text = text.translate(_TRANSLIT)
    nkfd = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in nkfd if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text.lower())


_GUARD_TOKEN_RE = re.compile(r"[^a-z0-9+#]+")


_GUARD_STOP = {
    "the",
    "and",
    "for",
    "with",
    "certified",
    "certificate",
    "certification",
    "certyfikat",
    "developer",
    "engineer",
    "professional",
    "associate",
    "foundation",
    "podstawy",
}


def _term_in_source(term: str, source_norm: str) -> bool:
    t = _norm_for_guard(term).strip()
    if not t:
        return True
    if t in source_norm:
        return True
    tokens = [
        w for w in _GUARD_TOKEN_RE.split(t) if len(w) >= 3 and w not in _GUARD_STOP
    ]
    if not tokens:
        # Too short/generic to judge reliably — don't cry wolf.
        return True
    return any(w in source_norm for w in tokens)


#: Prefix for findings we are confident about (a figure the source simply does
#: not contain). Kept distinct from "WERYFIKUJ"/"VERIFY" so the UI can show the
#: certain ones first — and so truncation never drops them for softer hints.
_HIGH_PREFIX = {"pl": "BRAK POKRYCIA", "en": "NOT IN SOURCE"}


_MED_PREFIX = {"pl": "WERYFIKUJ", "en": "VERIFY"}


# Pozycje umiejętności, które same sobie przeczą: „Iceberg (podstawowa znajomość
# – brak praktycznego doświadczenia)". Klient czyta to jako brak umiejętności.
_NEGATED_SKILL_RE = re.compile(
    r"brak\s+(?:praktyczn\w*\s+)?doświadcz\w*|bez\s+praktyczn\w*|nie\s+zna\b"
    r"|no\s+(?:practical|hands-on|commercial)\s+experience|no\s+experience",
    re.IGNORECASE,
)
_QUESTION_LINE_RE = re.compile(r"^\s*P:\s?(.*)$")
_TERM_TOKEN_RE = re.compile(r"[a-z0-9+#]+")


def screening_text_without_questions(notes: str) -> str:
    """Notatki bez linii pytań rekrutera („P: …").

    Treść pytania nie jest faktem o kandydacie: pytanie „Czy pracował Pan
    z OpenTelemetry?" przy odpowiedzi o Grafanie nie potwierdza OpenTelemetry.
    Bezpieczniki i kontrola AI porównują CV z tym tekstem, nie z pytaniami.
    """
    return "\n".join(
        line for line in (notes or "").splitlines() if not _QUESTION_LINE_RE.match(line)
    )


def _question_text(notes: str) -> str:
    return "\n".join(
        m.group(1)
        for line in (notes or "").splitlines()
        if (m := _QUESTION_LINE_RE.match(line))
    )


def _term_tokens(term: str) -> list[str]:
    return [t for t in _TERM_TOKEN_RE.findall(_norm_for_guard(term)) if len(t) >= 2]


def _stem(token: str) -> str:
    """Rdzeń słowa na odmianę: „grafana” → „grafa” (łapie „Grafany”)."""
    return token[: max(4, len(token) - 2)] if len(token) > 4 else token


def _loosely_present(term: str, haystack_tokens: set[str]) -> bool:
    """Każde słowo terminu (jego rdzeń) zaczyna jakieś słowo źródła („REST API" ↔
    „RESTful APIs", „Grafana" ↔ „Grafany"). Alternatywa w nawiasie liczy się
    osobno („Kubernetes (K8s)")."""
    variants = [term]
    paren = re.search(r"\(([^)]*)\)", term)
    if paren:
        variants = [term[: paren.start()], paren.group(1)]
    for variant in variants:
        tokens = _term_tokens(variant)
        if tokens and all(
            any(word.startswith(_stem(tok)) for word in haystack_tokens)
            for tok in tokens
        ):
            return True
    return False


def strip_unsupported_terms(
    candidate_data: dict[str, Any],
    *,
    cv_text: str,
    screening_notes_text: str,
    requirements: list[str],
    language: str,
) -> list[str]:
    """Usuń z technologii ról i umiejętności to, co pochodzi z pytań albo wymagań.

    Termin znika, gdy (a) nie ma go w CV ani w odpowiedziach i notatkach (bez
    linii pytań), a (b) wszystkie jego słowa stoją w pytaniach rekrutera albo
    w wymaganiach klienta — czyli model wziął go z ogłoszenia, nie od kandydata
    (13.10.2026: „OpenTelemetry" tylko z pytania, „Kafka Connect SMT" z
    nice-to-have). Znika też pozycja umiejętności, która sama sobie przeczy
    („… – brak praktycznego doświadczenia"). Zwraca uwagi do listy ostrzeżeń.
    """
    evidence = set(
        _TERM_TOKEN_RE.findall(
            _norm_for_guard(
                f"{cv_text}\n{screening_text_without_questions(screening_notes_text)}"
            )
        )
    )
    asked = set(
        _TERM_TOKEN_RE.findall(
            _norm_for_guard(
                _question_text(screening_notes_text) + "\n" + "\n".join(requirements)
            )
        )
    )
    removed: list[str] = []
    negated: list[str] = []

    def from_ad(term: str) -> bool:
        tokens = _term_tokens(term)
        if not tokens or _loosely_present(term, evidence):
            return False
        if all(tok in asked for tok in tokens):
            removed.append(term.strip())
            return True
        return False

    for job in candidate_data.get("experience") or []:
        techs = job.get("technologies") or []
        job["technologies"] = [t for t in techs if not from_ad(str(t))]

    skills: list[dict[str, str]] = []
    for cat in candidate_data.get("skills") or []:
        items = [
            i.strip() for i in str(cat.get("content") or "").split(",") if i.strip()
        ]
        kept: list[str] = []
        for item in items:
            if _NEGATED_SKILL_RE.search(item):
                negated.append(item)
            elif not from_ad(item):
                kept.append(item)
        if kept:
            skills.append({**cat, "content": ", ".join(kept)})
    candidate_data["skills"] = skills

    notes: list[str] = []
    prefix = _MED_PREFIX["en" if language == "en" else "pl"]
    if removed:
        names = ", ".join(dict.fromkeys(removed))
        notes.append(
            f"{prefix}: removed items found only in recruiter questions or client "
            f"requirements, not in the CV or answers: {names}"
            if language == "en"
            else f"{prefix}: usunięto pozycje, które były tylko w pytaniach rekrutera "
            f"albo wymaganiach klienta, a nie w CV ani odpowiedziach: {names}"
        )
    if negated:
        names = ", ".join(dict.fromkeys(negated))
        notes.append(
            f"{prefix}: removed skills that deny themselves (no practical "
            f"experience): {names}"
            if language == "en"
            else f"{prefix}: usunięto umiejętności z dopiskiem o braku "
            f"doświadczenia: {names}"
        )
    return notes


#: A number is only judged when it is attached to something countable. Bare
#: numbers are ignored on purpose: dates, versions and enumerations are noise,
#: whereas "20 serwerów" or "SLA 99,9%" is exactly the kind of figure clients
#: report as not holding up in interview.
_SCALE_UNITS = (
    r"osob\w*|pracownik\w*|czlonk\w*|specjalist\w*|programist\w*|deweloper\w*"
    r"|serwer\w*|klient\w*|projekt\w*|uzytkownik\w*|instancj\w*|klastr\w*"
    r"|aplikacj\w*|system\w*|wdrozen\w*|integracj\w*|oddzial\w*|lokalizacj\w*"
    r"|people|persons|members|engineers|developers|servers|clients|customers"
    r"|projects|users|instances|clusters|applications|systems|deployments"
    r"|integrations|locations|teams|countries"
)


_SCALE_CLAIM_RE = re.compile(r"(\d[\d\s.,]*?)\s*(%|" + _SCALE_UNITS + r")")


_YEARS_CLAIM_RE = re.compile(r"(\d{1,2})\s*(?:lat\w*|year)")


#: Spaces are allowed INSIDE a run so the Polish thousand separator ("1 000")
#: is indexed the same way ``_SCALE_CLAIM_RE`` captures it. The trailing ``\d``
#: keeps the run from swallowing a trailing space, and the ``|\d`` alternative
#: preserves single-digit matches.
_DIGIT_RUN_RE = re.compile(r"\d[\d\s.,]*\d|\d")


#: Scale words that turn one real task into an implied portfolio. This is the
#: exact defect class reported in #627 ("integracja frontendu z WIELOMA usługami
#: backendowymi dla RÓŻNYCH klientów i domen" for a plain React dev). Flagged
#: only when the source carries no such word itself.
_INFLATION_MARKERS = (
    "wielu",
    "wieloma",
    "wiele",
    "roznych",
    "roznorodnych",
    "szereg",
    "liczne",
    "licznych",
    "multiple",
    "various",
    "numerous",
    "wide range",
)


def _norm_number(raw: str) -> str:
    """Normalise a figure for comparison: drop thousand separators, unify the
    decimal mark, and strip a trailing decimal zero so "99,90" == "99.9"."""
    text = raw.strip().replace(" ", "").replace(",", ".")
    text = text.rstrip(".")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _numbers_in_source(source_norm: str) -> set[str]:
    """Every figure the source states, indexed both ways.

    A run is recorded whole ("1 000" → "1000", matching how the claim regex
    captures a thousand separator) AND split on spaces ("2019", "12" out of a
    date pair), because a space between digits is ambiguous: it separates
    thousands in one place and two distinct numbers in another. Indexing both
    readings keeps the guard from inventing a finding out of that ambiguity —
    for a warning system, over-accepting is far cheaper than crying wolf.
    """
    numbers: set[str] = set()
    for match in _DIGIT_RUN_RE.finditer(source_norm):
        raw = match.group(0)
        numbers.add(_norm_number(raw))
        if " " in raw:
            numbers.update(_norm_number(part) for part in raw.split() if part)
    numbers.discard("")
    return numbers


def _derivable_years(candidate_data: dict[str, Any]) -> set[str]:
    """Year counts the pipeline itself computes from the extracted dates.

    ``_fix_experience_years`` rewrites the headline ("6 lat jako…") from the
    date ranges, so those figures legitimately need not appear verbatim in the
    CV. Without this allowance the guard would flag its own arithmetic.
    """
    allowed: set[str] = set()
    total = _total_experience_years(candidate_data.get("experience") or [])
    if total is not None:
        # ±1 absorbs the rounding _fix_experience_years applies.
        allowed.update(str(total + delta) for delta in (-1, 0, 1) if total + delta >= 0)
    for job in candidate_data.get("experience") or []:
        span = _parse_date_range(str(job.get("dates") or ""))
        if not span:
            continue
        start, end = span
        now = local_now()
        end = min(end, now.year * 12 + (now.month - 1))
        years = max(0, (end - start) // 12)
        allowed.update(str(years + delta) for delta in (0, 1))
    # `_fix_scoped_years` sumuje role jednej firmy / jednego stanowiska.
    roles = [j for j in candidate_data.get("experience") or [] if isinstance(j, dict)]
    for field in ("company", "position"):
        for key in {_scope_key(j.get(field)) for j in roles} - {""}:
            scoped = _total_experience_years(
                [j for j in roles if _scope_key(j.get(field)) == key]
            )
            if scoped is not None:
                allowed.add(str(scoped))
    return allowed


def _free_text_fields(candidate_data: dict[str, Any]) -> list[tuple[str, str]]:
    """(label, text) pairs of every prose field the model writes freely."""
    out: list[tuple[str, str]] = []
    for point in candidate_data.get("why_points") or []:
        if isinstance(point, str) and point.strip():
            out.append(("why_points", point))
    for job in candidate_data.get("experience") or []:
        role = job.get("position") or job.get("company") or "?"
        for duty in job.get("responsibilities") or []:
            if isinstance(duty, str) and duty.strip():
                out.append((str(role), duty))
    return out


def _free_text_warnings(
    candidate_data: dict[str, Any], source_norm: str, language: str
) -> list[str]:
    """Check CLAIMS in free prose, not words.

    Term matching works for technologies (a closed vocabulary) but would drown
    the recruiter in false alarms on prose, because "Redakcja" and "Pod ofertę"
    are allowed to rephrase. A guard that cries wolf gets clicked away — that is
    how the existing collapsed warnings badge became invisible. So we only
    assert on things a rewrite must never change: figures, and claims of scale.
    """
    high = _HIGH_PREFIX["en" if language == "en" else "pl"]
    med = _MED_PREFIX["en" if language == "en" else "pl"]
    source_numbers = _numbers_in_source(source_norm)
    allowed_years = _derivable_years(candidate_data)
    issues: list[str] = []
    seen: set[str] = set()

    for label, text in _free_text_fields(candidate_data):
        norm = _norm_for_guard(text)
        snippet = text if len(text) <= 90 else text[:87] + "…"

        for match in _SCALE_CLAIM_RE.finditer(norm):
            number = _norm_number(match.group(1))
            if not number or number in source_numbers:
                continue
            key = f"num:{label}:{number}:{match.group(2)}"
            if key in seen:
                continue
            seen.add(key)
            issues.append(
                f"{high}: figure '{match.group(0).strip()}' ({label}) does not appear "
                f"in the CV or notes — „{snippet}”"
                if language == "en"
                else f"{high}: liczba '{match.group(0).strip()}' ({label}) nie występuje "
                f"w CV ani notatkach — „{snippet}”"
            )

        for match in _YEARS_CLAIM_RE.finditer(norm):
            years = match.group(1)
            if years in source_numbers or years in allowed_years:
                continue
            key = f"yrs:{label}:{years}"
            if key in seen:
                continue
            seen.add(key)
            issues.append(
                f"{high}: '{match.group(0).strip()}' ({label}) follows neither from the "
                f"source nor from the dates — „{snippet}”"
                if language == "en"
                else f"{high}: '{match.group(0).strip()}' ({label}) nie wynika ani ze "
                f"źródła, ani z dat — „{snippet}”"
            )

        for marker in _INFLATION_MARKERS:
            if marker in norm and marker not in source_norm:
                key = f"infl:{label}:{marker}"
                if key in seen:
                    continue
                seen.add(key)
                issues.append(
                    f"{med}: scale claim '{marker}' ({label}) has no basis in the source "
                    f"— „{snippet}”"
                    if language == "en"
                    else f"{med}: rozdmuchanie skali '{marker}' ({label}) bez pokrycia "
                    f"w źródle — „{snippet}”"
                )
                break  # one scale flag per sentence is enough

    return issues


def _fabrication_warnings(
    candidate_data: dict[str, Any], source_text: str, language: str
) -> list[str]:
    """Deterministic no-lying check against the CV text and screening notes.

    Covers three surfaces, each with the matching technique:
      * technologies + certifications — closed vocabulary, so term matching,
      * ``skills[].content`` — comma-separated technologies, same treatment,
      * free prose (``why_points``, ``responsibilities``) — claim checking,
        see :func:`_free_text_warnings`.

    Prose was unchecked until now, which is precisely where inflation lives:
    the prompt forbids it, but a prompt rule is a request. Findings are
    surfaced as warnings (the recruiter verifies); generation is not blocked.
    """
    source_norm = _norm_for_guard(source_text)
    issues: list[str] = []

    for job in candidate_data.get("experience", []):
        role = job.get("position") or job.get("company") or "?"
        for tech in job.get("technologies", []):
            if not _term_in_source(tech, source_norm):
                if language == "en":
                    issues.append(
                        f"VERIFY: technology '{tech}' ({role}) not found in the CV or notes"
                    )
                else:
                    issues.append(
                        f"WERYFIKUJ: technologia '{tech}' ({role}) nie występuje w CV ani notatkach"
                    )

    for cert in candidate_data.get("certifications", []):
        if not _term_in_source(cert, source_norm):
            if language == "en":
                issues.append(
                    f"VERIFY: certification '{cert}' not found in the CV or notes"
                )
            else:
                issues.append(
                    f"WERYFIKUJ: certyfikat '{cert}' nie występuje w CV ani notatkach"
                )

    # SKILLS carry technologies too, just as prose ("Python, PostgreSQL, K8s"),
    # so they get the same closed-vocabulary treatment as experience[].technologies.
    for skill in candidate_data.get("skills") or []:
        if not isinstance(skill, dict):
            continue
        label = str(skill.get("label") or "Umiejętności")
        for item in re.split(r"[,;/]", str(skill.get("content") or "")):
            item = item.strip()
            if len(item) < 3 or _term_in_source(item, source_norm):
                continue
            if language == "en":
                issues.append(
                    f"VERIFY: skill '{item}' ({label}) not found in the CV or notes"
                )
            else:
                issues.append(
                    f"WERYFIKUJ: umiejętność '{item}' ({label}) nie występuje w CV ani notatkach"
                )

    issues.extend(_free_text_warnings(candidate_data, source_norm, language))

    # Certain findings first: truncation must never drop a figure the source
    # does not contain in favour of a softer "verify this" hint.
    high = _HIGH_PREFIX["en" if language == "en" else "pl"]
    issues.sort(key=lambda msg: 0 if msg.startswith(high) else 1)

    if len(issues) > 8:
        more = len(issues) - 8
        issues = issues[:8]
        issues.append(
            f"… i {more} kolejnych pozycji do weryfikacji"
            if language != "en"
            else f"… and {more} more items to verify"
        )
    return issues


def _champion_parse_warnings(
    champion_dto: ChampionProfileForPrompt | None,
) -> list[str]:
    """Surface an implausible Champion DOCX parse to the recruiter.

    The parser cannot fail loudly — a heading spelled differently than expected
    is indistinguishable from a section that simply isn't there — so the only
    honest signal is the *shape* of what came out. Both warnings are gated on
    ``from_docx``: the New-mode path builds its profile from structured JSONB
    (:func:`from_nexus_job`) and can never hit a heading-recognition failure.
    """
    if champion_dto is None:
        return []
    diag = champion_dto.diagnostics
    if not diag.from_docx:
        return []
    if diag.nothing_recognised:
        return [
            "Profil Championa: nie rozpoznano żadnej sekcji z treścią — "
            "profil został zignorowany przy generowaniu. Upewnij się, że plik "
            "zawiera nagłówki MUST-HAVE / NICE-TO-HAVE w osobnych wierszach."
        ]
    if diag.wiped_out:
        return [
            "Profil Championa: żadna pozycja z MUST-HAVE / NICE-TO-HAVE nie "
            f"wyglądała na technologię (odrzucono wszystkie {diag.raw_entry_count}) "
            "— CV powstało bez wytłuszczeń i bez listy brakujących wymagań. "
            "Najczęstsza przyczyna: wymagania opisane zdaniami zamiast listą "
            "technologii."
        ]
    if diag.implausible:
        return [
            "Profil Championa: nietypowy układ dokumentu — pominięto "
            f"{diag.dropped_total} pozycji, które wyglądały na opis wymagań, "
            "a nie na technologie. Sprawdź nagłówki sekcji w pliku championa; "
            "wytłuszczenia technologii w CV mogą być niepełne."
        ]
    return []
