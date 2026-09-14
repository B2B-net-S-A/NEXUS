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
from datetime import datetime
from typing import Any

from app.services.cv_generator_b2b.champion_builder import ChampionProfileForPrompt
from app.services.cv_generator_b2b.docx_renderer import (
    compile_keyword_patterns,
    highlight_spans,
)
from app.services.cv_generator_b2b.standalone_service import (  # noqa: F401
    StandaloneGenerationError,
)


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
                "industry": str(job.get("industry") or "IT").strip(),
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


def _total_experience_years(experience: list[dict[str, Any]]) -> int | None:
    """Sum the candidate's actual time employed across all roles, in whole
    years. Intervals are merged so overlapping/parallel contracts (common in
    B2B) are counted once, and an ongoing role ("obecnie") is capped at the
    current month. Returns ``None`` when no role carries parseable dates.

    Claude is reliable at EXTRACTING dates but not at the arithmetic of summing
    them — it tends to round down ("ponad 4" for a 5-year candidate). Computing
    the figure here makes the why_points headline exact.
    """
    now = datetime.now()
    now_idx = now.year * 12 + (now.month - 1)
    intervals: list[tuple[int, int]] = []
    for job in experience or []:
        rng = _parse_date_range(job.get("dates") or "")
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
# figure (recruiter: "5 years must read 5, not 'over 4'").
_YEARS_PHRASE_RE = re.compile(
    r"(?:ponad|powyżej|przeszło|niemal|prawie|blisko|około|ok\.?|~|"
    r"over|nearly|almost|about|more than)?\s*"
    r"\d+(?:\s*[-–/]\s*\d+)?\s*"
    r"(?:lata|lat|roku|rok|years|year|yrs|yr)\b",
    re.IGNORECASE,
)


def _polish_year_unit(years: int) -> str:
    if years == 1:
        return "rok"
    if 2 <= years % 10 <= 4 and not 12 <= years % 100 <= 14:
        return "lata"
    return "lat"


# Connectors that bind a duration to a specific technology, tool or company
# ("5 lat z Kubernetes", "3 years with Docker", "8 years at Gigaset", "5 lat
# w Gigaset"). Role connectors ("jako" / "as") are deliberately excluded — a
# duration tied to a ROLE is the total-career headline we DO want to correct.
_BOUND_CONNECTOR_RE = re.compile(r"\b(?:z|ze|w|we|u|with|in|at)\b", re.IGNORECASE)


# Markers introducing the "w tym Y lat w [firmie]" sub-figure of a why_point.
# That figure is scoped to one company/chapter of the career, so the recompute
# must never land on it — only the clause BEFORE a marker is searched.
_SUBFIGURE_SPLIT_RE = re.compile(r"\sw tym\s|\sincluding\s|\sincl\.?\s", re.IGNORECASE)


def _experience_bound_terms(candidate_data: dict[str, Any]) -> set[str]:
    """Collect the vocabulary a duration must never be inflated against: the
    champion highlight list, every role's ``technologies`` and every role's
    company name — lowercased. Used to tell a scoped duration ("2 lata z
    Intune", "5 years at Gigaset") apart from the total-career headline so the
    recompute never inflates the former. Sub-4-char tokens are dropped to
    avoid spurious substring hits (e.g. "AI", "Go", "MDM")."""
    raw: list[str] = list(candidate_data.get("highlight_keywords") or [])
    for job in candidate_data.get("experience") or []:
        raw.extend(job.get("technologies") or [])
        company = str(job.get("company") or "")
        raw.append(company)
        raw.extend(company.split())
    return {s for t in raw if len(s := str(t).strip().lower()) >= 4}


def _years_bound_to_tech_or_company(
    point: str, years_end: int, bound_terms: set[str]
) -> bool:
    """True when the years figure is tied to a specific technology or company
    rather than a role — e.g. "6 lat doświadczenia z Microsoft Intune" or
    "5 years at Gigaset". Only the clause the figure introduces is inspected
    (up to the next comma / "w tym" / "including") so a trailing tech mention
    or the "w tym Y lat w [firma]" sub-figure can't trigger a false positive."""
    if not bound_terms:
        return False
    tail = point[years_end:]
    clause = re.split(r"[,;]| w tym | including | incl\.? ", tail, maxsplit=1)[0]
    conn = _BOUND_CONNECTOR_RE.search(clause)
    if not conn:
        return False
    after = clause[conn.end() :].lower()
    return any(term in after for term in bound_terms)


def _fix_experience_years(candidate_data: dict[str, Any], language: str) -> None:
    """Overwrite the (often under-counted) total-years figure in the experience
    why_point with the exact value computed from the candidate's dates. Only
    the headline total is touched — the "w tym Y lat w …" sub-figure and any
    other point are left as Claude wrote them.

    A technology- or company-specific duration ("2 lata z Microsoft Intune",
    "5 years at Gigaset") is left alone: overwriting it with the total career
    figure would falsely inflate experience with that one technology or tenure
    at that one company, so such points are skipped in favour of a generic
    role/seniority headline.

    Only the clause before "w tym" / "including" is searched. When the headline
    figure itself is unparseable (e.g. "5+ years"), the search must not drift
    into the sub-figure — that once turned "including 5 years at Gigaset" into
    "including 8 years at Gigaset" by stamping the career total there.
    """
    years = _total_experience_years(candidate_data.get("experience") or [])
    if not years:
        return
    if language == "en":
        replacement = f"{years} {'year' if years == 1 else 'years'}"
    else:
        replacement = f"{years} {_polish_year_unit(years)}"

    bound_terms = _experience_bound_terms(candidate_data)

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
        if _years_bound_to_tech_or_company(point, match.end(), bound_terms):
            continue
        points[i] = point[: match.start()] + replacement + point[match.end() :]
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


def _fix_scoped_years(candidate_data: dict[str, Any], language: str) -> None:
    """Przelicz z dat liczby lat przypięte do KONKRETNEJ roli albo firmy.

    Model nie zna dzisiejszej daty i liczył „obecnie" jak rok wcześniej
    („6 lat jako Backend Developer" przy roli od 01.2019), a bezpiecznik
    fabrykacji tylko ostrzegał — zła liczba zostawała w DOCX, HTML i kafelkach.
    Tu liczba jest nadpisywana wyłącznie sumą przedziałów PASUJĄCYCH ról:
    stanowisko zawiera frazę po „jako"/„as", albo firma jest dokładnie tą
    nazwą po „w"/„u"/„at". Brak dopasowania, fleksja („jako Developera") czy
    niepełne daty = liczba zostaje, jak napisał model. Dzięki temu poprawka
    nigdy nie dolicza lat z innej roli ani innej firmy.
    """
    roles = [
        job for job in candidate_data.get("experience") or [] if isinstance(job, dict)
    ]
    if not roles:
        return

    def unit(years: int) -> str:
        if language == "en":
            return "year" if years == 1 else "years"
        return _polish_year_unit(years)

    companies = sorted(
        {key for job in roles if len(key := _scope_key(job.get("company") or "")) >= 4},
        key=len,
        reverse=True,
    )

    def scoped_years(tail: str) -> int | None:
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

    points = candidate_data.get("why_points") or []
    for i, point in enumerate(points):
        if not isinstance(point, str):
            continue

        def replace(match: re.Match[str]) -> str:
            years = scoped_years(match.string[match.end() :])
            if not years:
                return match.group(0)
            text = match.group(0)
            lead = text[: len(text) - len(text.lstrip())]
            return f"{lead}{years} {unit(years)}"

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
        now = datetime.now()
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
