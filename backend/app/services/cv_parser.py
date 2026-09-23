"""CV parser service (Phase D3 + Phase D4 — Claude + Phase v4 auto-fill).

Takes raw CV text and uses an LLM to extract structured facts:
  - first_name / last_name (str|None)              — v4
  - email / phone / city (str|None)                — v4
  - years_it_experience (int)
  - current_position (str|None)
  - skills (list of canonical dicts)
  - education (list)
  - languages (list)
  - companies (list of strings) — Phase D4
  - career_summary (str|None) — Phase D4
  - linkedin_url (str|None)
  - _confidence (dict[str, float])                  — v4, per-field certainty

Hierarchy (highest precedence first):
  1. Claude (Anthropic) — best quality, used for production uploads
  2. Ollama (local) — free, used in dev / when ANTHROPIC_API_KEY is unset
  3. regex heuristic — always-on last resort, never fails

Contact-field safety net: after the LLM returns, a deterministic regex pass
(`_apply_contact_fallbacks`) fills in any email/phone/name it missed by
scanning the first ~15 lines of the CV and any standalone email addresses.
Values from the LLM win — the regex only fills in `None` slots.

Returns a dict — caller decides which fields to persist. On persist, the
`match_score_cache.mark_stale_for_candidate` hook should be invoked so the
cache recomputes with the fresh skills.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

import httpx
from fastapi.concurrency import run_in_threadpool

from app.core.config import settings
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: TC002 — adnotacja parse_cv
from app.services.llm_prompts import CV_ENRICHMENT, PromptTemplate
from app.models.ai_feature import AIFeatureKey
from app.services.ai_models import model_for

logger = logging.getLogger(__name__)


_TECH_PATTERN = re.compile(
    r"\b(Python|Java|JavaScript|TypeScript|React|Angular|Vue|Node|Go|Rust|"
    r"C\+\+|C#|Kotlin|Swift|PHP|Ruby|Scala|SQL|PostgreSQL|MySQL|MongoDB|Redis|"
    r"Docker|Kubernetes|AWS|GCP|Azure|Terraform|Kafka|RabbitMQ|Elasticsearch|"
    r"Django|Flask|FastAPI|Spring|Express|Next\.js|GraphQL|REST|gRPC|CI/CD|Git)\b",
    re.I,
)

_YEARS_PATTERN = re.compile(
    r"(\d{1,2})\s*(?:\+\s*)?(?:lat|years?|lata?)\s*(?:doświadczenia|experience|IT|w IT)?",
    re.I,
)

# Matches standalone LinkedIn profile URLs embedded in CV text.
# Examples caught: "https://linkedin.com/in/jane-doe", "www.linkedin.com/in/jane",
# "pl.linkedin.com/in/jane-doe/", "linkedin.com/in/jane_doe?foo=bar".
_LINKEDIN_URL_RE = re.compile(
    r"(?:https?://)?(?:[a-z]{2,3}\.)?linkedin\.com/in/[\w\-%._]+/?",
    re.IGNORECASE,
)

# Simplified RFC 5322 — sufficient for CV headers; avoids pathological
# edge cases (quoted locals, IP literals) which never appear in CVs.
_EMAIL_RE = re.compile(
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
)

# PL phone numbers: optional +48/48 prefix, then 9 digits with optional
# separators (space, dash, dot, non-breaking space). Captures the raw match —
# callers may normalize to "+48 XXX XXX XXX" if needed.
_PHONE_PL_RE = re.compile(
    r"(?:(?:\+|00)\s*48[\s.\-]*)?"  # optional country code
    r"(?:\d[\s.\-]*){9}",  # exactly 9 digits with separators
)

# Honorific/role tokens that should NOT appear in a detected first/last name.
# Used to filter out heading lines like "CURRICULUM VITAE" or "Senior Developer".
_NAME_REJECT_RE = re.compile(
    r"(?i)\b(cv|curriculum|vitae|resume|senior|lead|junior|mid|"
    r"principal|staff|developer|engineer|manager|architect|profile|summary)\b",
)


def _extract_linkedin_from_text(cv_text: str) -> Optional[str]:
    """Find the first LinkedIn profile URL in the CV text, or None.

    Used as a regex backstop when the LLM response lacks a `linkedin_url`
    field. Returns the raw match; the caller normalizes via
    `app.services.proxycurl.client.normalize_linkedin_url`.
    """

    if not cv_text:
        return None
    match = _LINKEDIN_URL_RE.search(cv_text)
    return match.group(0) if match else None


def _extract_email_from_text(cv_text: str) -> Optional[str]:
    """Return the first plausible email address in the CV (lowercased)."""
    if not cv_text:
        return None
    match = _EMAIL_RE.search(cv_text)
    return match.group(0).lower() if match else None


def _extract_phone_from_text(cv_text: str) -> Optional[str]:
    """Return the first PL phone match from the CV, trimmed.

    We only accept matches whose digit-only form is 9 or 11 digits (with
    country code) to reduce false positives on salary figures / years.
    """
    if not cv_text:
        return None
    # Scan the top of the CV first — contact info usually sits in the header.
    head = "\n".join(cv_text.splitlines()[:20])
    for source in (head, cv_text):
        for match in _PHONE_PL_RE.finditer(source):
            raw = match.group(0).strip(" .-")
            digits = re.sub(r"\D", "", raw)
            if len(digits) in (9, 11):
                return raw
    return None


def _split_name_from_header(cv_text: str) -> tuple[Optional[str], Optional[str]]:
    """Heuristic: first/last name from the first non-empty CV line.

    Matches lines like "Jan Kowalski" or "JAN KOWALSKI" — two or three
    capitalized tokens, no role/honorific keywords. Returns (first, last)
    or (None, None) if no line qualifies.
    """
    if not cv_text:
        return None, None
    for raw_line in cv_text.splitlines()[:10]:
        line = raw_line.strip()
        if not line or len(line) > 60 or _NAME_REJECT_RE.search(line):
            continue
        # Reject lines that contain digits, emails, phone signs — they're
        # contact info, not a name header.
        if any(ch.isdigit() for ch in line) or "@" in line or "+" in line:
            continue
        tokens = [t for t in re.split(r"[\s,]+", line) if t]
        if not 2 <= len(tokens) <= 4:
            continue
        # Each token must start with an uppercase letter; accept PL diacritics.
        if not all(
            re.match(r"^[A-ZŁŚŻŹĆŃÓĄĘ][\wŁłŚśŻżŹźĆćŃńÓóĄąĘę\-']+$", t) for t in tokens
        ):
            continue
        first = tokens[0]
        last = " ".join(tokens[1:])
        return first, last
    return None, None


def _apply_contact_fallbacks(parsed: dict[str, Any], cv_text: str) -> dict[str, Any]:
    """Fill missing contact fields via regex; preserves LLM values.

    Regex only writes into keys that are currently `None` or missing.
    Sets `_confidence` for regex-filled fields: 0.9 for exact email match,
    0.85 for phone with 9+ digits, 0.6 for name split heuristic.
    """
    out = dict(parsed)
    confidence = dict(out.get("_confidence") or {})

    if not out.get("email"):
        email = _extract_email_from_text(cv_text)
        if email:
            out["email"] = email
            confidence.setdefault("email", 0.9)

    if not out.get("phone"):
        phone = _extract_phone_from_text(cv_text)
        if phone:
            out["phone"] = phone
            confidence.setdefault("phone", 0.85)

    if not out.get("first_name") or not out.get("last_name"):
        first, last = _split_name_from_header(cv_text)
        if first and not out.get("first_name"):
            out["first_name"] = first
            confidence.setdefault("first_name", 0.6)
        if last and not out.get("last_name"):
            out["last_name"] = last
            confidence.setdefault("last_name", 0.6)

    if confidence:
        out["_confidence"] = confidence
    return out


def _regex_fallback(cv_text: str) -> dict[str, Any]:
    """Deterministic heuristic — best-effort extraction without LLM."""
    found_tech = {m.group(0) for m in _TECH_PATTERN.finditer(cv_text)}
    skills = [{"name": t, "level": None, "years": None} for t in list(found_tech)[:20]]

    years_match = _YEARS_PATTERN.search(cv_text)
    years = int(years_match.group(1)) if years_match else None
    if years and years > 50:
        years = None

    # Current position — take line starting with "Senior/Lead/Principal" (rough)
    current_position: Optional[str] = None
    for line in cv_text.splitlines()[:40]:
        line = line.strip()
        if re.match(r"^(Senior|Lead|Principal|Staff|Junior|Mid)\s+[A-Z]", line):
            current_position = line[:100]
            break

    base = {
        "first_name": None,
        "last_name": None,
        "email": None,
        "phone": None,
        "city": None,
        "years_it_experience": years,
        "current_position": current_position,
        "current_position_started_at": None,
        "current_position_started_at_precision": "unknown",
        "skills": skills,
        "technologies": [skill["name"] for skill in skills[:8]],
        "sectors": [],
        "education": [],
        "languages": [],
        # Phase D4: schema consistency with Claude/Ollama output. The frontend
        # reads these fields via optional chaining, but an explicit empty list /
        # null lets UI tell "no data yet" from "legacy record, never enriched".
        "companies": [],
        "professional_profile": None,
        "career_summary": None,
        "linkedin_url": _extract_linkedin_from_text(cv_text),
        "_confidence": {},
        "_source": "regex",
    }
    return _apply_contact_fallbacks(base, cv_text)


def _unique_strings(values: Any, *, limit: int) -> list[str]:
    """Normalize an LLM list to short, unique, non-empty strings."""

    if not isinstance(values, list):
        return []
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        if isinstance(value, dict):
            value = value.get("name")
        if not isinstance(value, str):
            continue
        cleaned = " ".join(value.split()).strip()[:80]
        key = cleaned.casefold()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        output.append(cleaned)
        if len(output) >= limit:
            break
    return output


# v7 prosi o WSZYSTKIE stanowiska (max 15). Dłuższa historia była dotąd cięta do
# 10 najnowszych, więc pierwsze lata kariery znikały z osi technologii.
_EXPERIENCE_MAX_ENTRIES = 15
_EXPERIENCE_CURRENT_WORDS = frozenset(
    {"present", "current", "now", "obecnie", "teraz", "do teraz", "nadal", "ongoing"}
)


def _normalize_experience_date(value: Any, *, allow_present: bool) -> Optional[str]:
    """Data wpisu doświadczenia → ``YYYY-MM`` / ``YYYY`` (albo ``present``).

    Model bywa niekonsekwentny co do zapisu („06.2023”, „2023/06”, pełna
    data). Nieczytelny POCZĄTEK jest odrzucany (``None``) — zgadnięta data
    byłaby fabrykacją. Nieczytelny KONIEC (``allow_present``, np. „Dec 2022”)
    zostaje tekstem z CV: ``None`` w ``end`` to kanoniczny znacznik bieżącej
    pracy, więc odrzucenie zamieniłoby zakończoną pracę w obecną.
    """
    if value is None:
        return None
    text = str(value).strip().casefold()
    if not text:
        return None
    if text in _EXPERIENCE_CURRENT_WORDS:
        return "present" if allow_present else None
    match = re.fullmatch(r"(\d{4})[-./](\d{1,2})(?:[-./]\d{1,2})?", text)
    if match:
        year, month = match.group(1), int(match.group(2))
        return f"{year}-{month:02d}" if 1 <= month <= 12 else year
    match = re.fullmatch(r"(?:\d{1,2}[-./])?(\d{1,2})[-./](\d{4})", text)
    if match:
        month, year = int(match.group(1)), match.group(2)
        return f"{year}-{month:02d}" if 1 <= month <= 12 else year
    if re.fullmatch(r"\d{4}", text):
        return text
    if allow_present:
        return " ".join(str(value).split())[:40]
    return None


_EMPLOYMENT_TYPES = frozenset(
    {"b2b", "employment", "contract", "internship", "freelance"}
)
_EDUCATION_LEVELS = frozenset(
    {"secondary", "bachelor", "engineer", "master", "phd", "other"}
)
_MAX_TECH_PER_ENTRY = 12


def _clean_text(value: Any, limit: int) -> Optional[str]:
    """Jednoliniowy tekst z modelu albo None — nigdy pusty string."""
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split()).strip()
    return cleaned[:limit] or None


def _clean_year(value: Any) -> Optional[int]:
    """Rok 1950–2100 albo None. Bool i śmieci odrzucone, nie zgadywane."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        year = int(float(str(value).strip()[:4]))
    except (TypeError, ValueError, OverflowError):
        return None
    return year if 1950 <= year <= 2100 else None


def _normalize_experience(value: Any) -> list[dict[str, Any]]:
    """Waliduj listę stanowisk z CV: firma, rola, początek, koniec (+ v7).

    Cztery klucze v6 są zawsze obecne. Klucze v7 (`technologies`,
    `description`, `employment_type`, `location`, `client`) pojawiają się
    tylko wtedy, gdy model podał użyteczną wartość — wynik odczytu v6 ma
    więc dokładnie ten sam kształt co przed zmianą.
    """
    if not isinstance(value, list):
        return []
    entries: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        company = item.get("company")
        role = item.get("role") or item.get("title") or item.get("position")
        company = (
            " ".join(company.split()).strip()[:160] if isinstance(company, str) else ""
        )
        role = " ".join(role.split()).strip()[:160] if isinstance(role, str) else ""
        if not company and not role:
            continue
        entry: dict[str, Any] = {
            "company": company or None,
            "role": role or None,
            "start": _normalize_experience_date(item.get("start"), allow_present=False),
            "end": _normalize_experience_date(item.get("end"), allow_present=True),
        }
        technologies = _unique_strings(
            item.get("technologies"), limit=_MAX_TECH_PER_ENTRY
        )
        if technologies:
            entry["technologies"] = technologies
        description = _clean_text(item.get("description") or item.get("desc"), 600)
        if description:
            entry["description"] = description
        employment_type = item.get("employment_type")
        if isinstance(employment_type, str):
            employment_type = employment_type.strip().casefold()
            if employment_type in {"uop", "umowa o pracę", "full-time", "permanent"}:
                employment_type = "employment"
            if employment_type in _EMPLOYMENT_TYPES:
                entry["employment_type"] = employment_type
        location = _clean_text(item.get("location"), 120)
        if location:
            entry["location"] = location
        client = _clean_text(item.get("client"), 160)
        if client:
            entry["client"] = client
        entries.append(entry)
        if len(entries) >= _EXPERIENCE_MAX_ENTRIES:
            break
    return entries


def _normalize_education(value: Any) -> Optional[list[dict[str, Any]]]:
    """Walidacja `education`. Do v7 lista szła do bazy bez żadnego sprawdzenia.

    Zwraca None, gdy wejście nie jest listą — `_apply_cv_enrichment` traktuje
    brak klucza jako „nie zapisuj", a pusta lista jako wynik byłaby zapisem.
    """
    if not isinstance(value, list):
        return None
    entries: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, str):
            school = _clean_text(item, 200)
            if school:
                entries.append(
                    {"degree": None, "field": None, "school": school, "year": None}
                )
            continue
        if not isinstance(item, dict):
            continue
        degree = _clean_text(item.get("degree"), 160)
        field = _clean_text(item.get("field"), 160)
        school = _clean_text(item.get("school") or item.get("institution"), 200)
        if not (degree or field or school):
            continue
        end_year = _clean_year(item.get("end_year"))
        year = _clean_year(item.get("year")) or end_year
        entry: dict[str, Any] = {
            "degree": degree,
            "field": field,
            "school": school,
            "year": year,
        }
        start_year = _clean_year(item.get("start_year"))
        if start_year:
            entry["start_year"] = start_year
        if end_year:
            entry["end_year"] = end_year
        level = item.get("level")
        if isinstance(level, str) and level.strip().casefold() in _EDUCATION_LEVELS:
            entry["level"] = level.strip().casefold()
        entries.append(entry)
        if len(entries) >= 10:
            break
    return entries


def _normalize_certifications(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in value:
        if isinstance(item, str):
            item = {"name": item}
        if not isinstance(item, dict):
            continue
        name = _clean_text(item.get("name"), 200)
        if not name or name.casefold() in seen:
            continue
        seen.add(name.casefold())
        entries.append(
            {
                "name": name,
                "issuer": _clean_text(item.get("issuer"), 120),
                "year": _clean_year(item.get("year")),
                "expires": _normalize_experience_date(
                    item.get("expires"), allow_present=False
                ),
            }
        )
        if len(entries) >= 20:
            break
    return entries


def _normalize_projects(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    entries: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        name = _clean_text(item.get("name"), 200)
        if not name:
            continue
        entries.append(
            {
                "name": name,
                "role": _clean_text(item.get("role"), 160),
                "company": _clean_text(item.get("company"), 160),
                "technologies": _unique_strings(
                    item.get("technologies"), limit=_MAX_TECH_PER_ENTRY
                ),
                "start": _normalize_experience_date(
                    item.get("start"), allow_present=False
                ),
                "end": _normalize_experience_date(item.get("end"), allow_present=True),
                "description": _clean_text(item.get("description"), 600),
            }
        )
        if len(entries) >= 8:
            break
    return entries


def _normalize_achievements(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    output: list[str] = []
    for item in value:
        text = _clean_text(item, 300)
        if text:
            output.append(text)
        if len(output) >= 6:
            break
    return output


def _normalize_skill_dates(value: Any) -> Any:
    """Daty użycia skilli (v7) do kanonu `YYYY-MM`/`YYYY`/`present` albo usunięte.

    Reszta kształtu `skills` należy do `normalize_llm_skills` w warstwie zapisu,
    więc tu dotykamy wyłącznie dwóch nowych kluczy i nic nie odrzucamy.
    """
    if not isinstance(value, list):
        return value
    output = []
    for item in value:
        if isinstance(item, dict) and ("first_used" in item or "last_used" in item):
            item = dict(item)
            first_used = _normalize_experience_date(
                item.pop("first_used", None), allow_present=False
            )
            last_used = item.pop("last_used", None)
            last_text = str(last_used).strip().casefold() if last_used else ""
            last_used = (
                "present"
                if last_text in _EXPERIENCE_CURRENT_WORDS
                else _normalize_experience_date(last_used, allow_present=False)
            )
            if first_used:
                item["first_used"] = first_used
            if last_used:
                item["last_used"] = last_used
        output.append(item)
    return output


def normalize_experience_entries(value: Any) -> list[dict[str, Optional[str]]]:
    """Publiczne wejście dla biegów, które dostają SUROWY wynik `parse_cv_with_claude`.

    `_parse_with_claude` nie normalizuje (robi to dopiero `parse_cv` przez
    `_normalize_cv_output`), więc bieg masowy z własnym szablonem musi sam
    przepuścić `experience` przez tę samą walidację dat co ścieżka rekrutera —
    inaczej „06.2023” z modelu trafiłoby do bazy w innym kształcie niż „2023-06”.
    """
    return _normalize_experience(value)


def _normalize_cv_output(parsed: dict[str, Any]) -> dict[str, Any]:
    """Validate/cap the v5 quick-view facts while preserving legacy fields."""

    output = dict(parsed)
    output["experience"] = _normalize_experience(output.get("experience"))
    if "education" in output:
        education = _normalize_education(output.get("education"))
        if education is None:
            output.pop("education")
        else:
            output["education"] = education
    if "skills" in output:
        output["skills"] = _normalize_skill_dates(output.get("skills"))
    for key, normalizer in (
        ("certifications", _normalize_certifications),
        ("projects", _normalize_projects),
        ("achievements", _normalize_achievements),
    ):
        if key in output:
            output[key] = normalizer(output.get(key))
    for key in ("country", "github_url"):
        if key in output:
            output[key] = _clean_text(output.get(key), 200)
    technologies = output.get("technologies")
    if not isinstance(technologies, list):
        technologies = output.get("skills")
    output["technologies"] = _unique_strings(technologies, limit=8)
    output["sectors"] = _unique_strings(
        output.get("sectors") or output.get("industries"), limit=4
    )

    started_at = output.get("current_position_started_at")
    if isinstance(started_at, str):
        started_at = started_at.strip()[:10] or None
    elif started_at is not None:
        started_at = str(started_at)[:10]
    if started_at and not any(
        re.fullmatch(pattern, started_at)
        for pattern in (r"\d{4}-\d{2}-\d{2}", r"\d{4}-\d{2}", r"\d{4}")
    ):
        started_at = None
    output["current_position_started_at"] = started_at

    precision = output.get("current_position_started_at_precision")
    if precision not in {"date", "month", "year"}:
        if isinstance(started_at, str) and re.fullmatch(
            r"\d{4}-\d{2}-\d{2}", started_at
        ):
            precision = "date"
        elif isinstance(started_at, str) and re.fullmatch(r"\d{4}-\d{2}", started_at):
            precision = "month"
        elif isinstance(started_at, str) and re.fullmatch(r"\d{4}", started_at):
            precision = "year"
        else:
            precision = "unknown"
    output["current_position_started_at_precision"] = precision

    current_position = output.get("current_position")
    output["current_position"] = (
        " ".join(current_position.split()).strip()[:160]
        if isinstance(current_position, str) and current_position.strip()
        else None
    )
    years = output.get("years_it_experience")
    try:
        years = int(years) if years is not None else None
    except (TypeError, ValueError):
        years = None
    output["years_it_experience"] = years if years and 0 < years <= 60 else None

    profile = output.get("professional_profile")
    output["professional_profile"] = (
        " ".join(profile.split()).strip()[:300]
        if isinstance(profile, str) and profile.strip()
        else None
    )
    return output


def _window_cv_text(text: str, cap: int) -> str:
    """Tekst CV przycięty do `cap` znaków z zachowaniem KOŃCA dokumentu.

    Do v7 model dostawał `cv_text[:8000]`, więc w długim CV odpadał ogon —
    a tam siedzą wykształcenie, certyfikaty i języki. Przy przekroczeniu
    bierzemy 70% z początku i 30% z końca, ze znacznikiem przerwy.
    """
    if len(text) <= cap:
        return text
    marker = "\n[…]\n"
    head = int((cap - len(marker)) * 0.7)
    tail = cap - len(marker) - head
    return text[:head] + marker + text[-tail:]


def _cv_input_for(template: PromptTemplate, cv_text: str) -> str:
    """Okno wejścia: pełny odczyt rekrutera (v7) szeroki, bieg masowy bez zmian."""
    if template.name == CV_ENRICHMENT.name:
        return _window_cv_text(cv_text, settings.CV_PARSER_INPUT_CHAR_CAP)
    return cv_text[:8000]


def _max_tokens_for(template: PromptTemplate) -> int:
    """Sufit odpowiedzi; dla v7 podniesiony z 6000 do 8000 (18.09.2026).

    Ucięta odpowiedź jest ZAPŁACONA i bezużyteczna — spada do regexu, więc
    kandydat dostaje uboższy profil, a rachunek pełny. Zmierzone na produkcji
    16–18.09: 52 wywołania `outcome='truncated'` ($3,64) przy średnim wyjściu
    5885 tokenów, czyli tuż pod dawnym sufitem 6000 — to nie były pojedyncze
    monstrualne CV, tylko normalne CV bijące w za ciasny limit.
    """
    return 8000 if template.name == CV_ENRICHMENT.name else 3000


def _timeouts_for(template: PromptTemplate) -> dict:
    """Pełny odczyt v7 ma twardy sufit poniżej 120 s okna przeglądarki.

    „Nowy kandydat z CV” czeka na odpowiedź synchronicznie. Domyślne 90 s na
    próbę z dwoma ponowieniami dawało do ~270 s — długo po tym, jak przeglądarka
    zgłosiła „Network Error”. Bieg masowy zostaje przy domyślnych.
    """
    if template.name != CV_ENRICHMENT.name:
        return {}
    return {"timeout": 100.0, "max_retries": 1, "total_timeout": 110.0}


def _strip_json_fences(raw: str) -> str:
    """Strip ```json ... ``` markdown fences that LLMs occasionally emit.

    Mirrors the behaviour in app/api/ai_writer.py:259-263 so both Claude call-
    sites share the same unwrap logic.
    """
    raw = raw.strip()
    if raw.startswith("```"):
        # Drop the opening fence (with or without language tag).
        raw = raw.split("```", 2)
        # parts: ["", "json\n{...}", ""] or ["", "{...}", ""] — take middle.
        raw = raw[1] if len(raw) > 1 else ""
        if raw.lstrip().startswith("json"):
            raw = raw.lstrip()[4:]
    # Also strip trailing backticks if the split above left any behind.
    return raw.strip().rstrip("`").strip()


async def _parse_with_claude(
    cv_text: str,
    *,
    model: str | None = None,
    template: PromptTemplate = CV_ENRICHMENT,
) -> Optional[dict[str, Any]]:
    """Call Claude with a versioned enrichment prompt, through the shared client.

    Returns None on any failure so the caller can fall back to Ollama / regex.
    Never raises upward.

    PRZEZ `call_claude`, NIE surowego `anthropic.Anthropic` — to nie jest
    kosmetyka. Surowy klient omijał CZTERY rzeczy naraz: jawny timeout (default
    SDK to 600 s na request), retry z backoffem na 429/529, telemetrię zdrowia
    dostawcy w /api/health oraz `_assert_declared` bramki kwot. Przy biegu
    masowym na ~39 tys. CV każda z tych czterech dziur kosztuje realnie; przy
    ścieżce interaktywnej — kosztowała po cichu od początku.

    `model`/`template` są parametrami, bo bieg MASOWY (Fala 3) używa tańszego
    modelu i przyciętego promptu bez pól generatywnych, a ścieżka interaktywna
    zostaje przy dotychczasowych domyślnych. Rozdzielenie per wywołanie, nie
    per proces — obie ścieżki żyją w tym samym backendzie.
    """
    from app.services.claude_client import call_claude
    from app.services.llm_providers import api_key_configured

    chosen_model = model or model_for(AIFeatureKey.cv_parser)
    # Klucz DOSTAWCY wybranego modelu, nie Anthropic na sztywno: bieg masowy
    # i ścieżka interaktywna mogą stać na różnych dostawcach (rejestr
    # `ai_models`), a pytanie o cudzy klucz cicho wyłączyłoby wzbogacanie.
    if not api_key_configured(chosen_model) or not settings.CV_ENRICHMENT_ENABLED:
        return None
    try:
        user_prompt = template.render(cv_text=_cv_input_for(template, cv_text))
        # `call_claude` jest synchroniczne (sam robi timeout+retry) — offload,
        # żeby wielosekundowy round-trip nie blokował jednowątkowego event loopu.
        message = await run_in_threadpool(
            call_claude,
            model=chosen_model,
            # Bieg masowy na tańszym modelu (F10 = GPT-6 Luna od 22.09.2026) przy
            # przeciążeniu dostawcy schodzi na model parsera CV, a nie od razu
            # do Ollamy/regexu.
            fallback_models=[
                m for m in (model_for(AIFeatureKey.cv_parser),) if m != chosen_model
            ],
            # v6 dokłada listę stanowisk z datami — 2000 tokenów obcinało JSON
            # dłuższych CV, a obcięta odpowiedź spada do regexu. v7 (technologie
            # per stanowisko, projekty, certyfikaty) potrzebuje ~2× więcej.
            max_tokens=_max_tokens_for(template),
            **_timeouts_for(template),
            # Claude 5 does adaptive thinking by default; thinking tokens count
            # toward max_tokens and would truncate this JSON output. On models
            # where thinking is off by default (Haiku 4.5) `disabled` is a no-op
            # — the pin only matters when a Claude 5 model is configured.
            thinking={"type": "disabled"},
            system=template.system_prompt or "",
            messages=[{"role": "user", "content": user_prompt}],
            api_key=settings.ANTHROPIC_API_KEY or None,
        )
        # Claude 5 models can lead with a non-text block (e.g. a thinking
        # block), so content[0].text may be absent/empty — collect every text
        # block instead of blindly reading content[0].
        raw = "".join(
            getattr(b, "text", "") or "" for b in message.content if hasattr(b, "text")
        )
        unwrapped = _strip_json_fences(raw)
        data = json.loads(unwrapped)
        if not isinstance(data, dict):
            return None
        data["_source"] = f"claude:{template.name}:v{template.version}"
        # `message.usage` szło dotąd do kosza — a bez niego każdy kosztorys
        # biegu masowego jest zgadywanką. Zapis do payloadu (ląduje w
        # cv_extracted_data) + log, żeby bieg kalibracyjny mierzył realny
        # koszt jednostkowy zamiast szacunku.
        usage = getattr(message, "usage", None)
        if usage is not None:
            data["_usage"] = {
                "model": chosen_model,
                "input_tokens": getattr(usage, "input_tokens", None),
                "output_tokens": getattr(usage, "output_tokens", None),
            }
            logger.info(
                "[cv_parser] model=%s in=%s out=%s template=%s v%d",
                chosen_model,
                getattr(usage, "input_tokens", "?"),
                getattr(usage, "output_tokens", "?"),
                template.name,
                template.version,
            )
        return data
    except Exception as e:
        logger.warning(
            "[cv_parser] Claude call failed (template=%s v%d): %s",
            template.name,
            template.version,
            e,
        )
        return None


async def _parse_with_ollama(cv_text: str) -> Optional[dict[str, Any]]:
    """Call local Ollama; returns None on any failure so caller can fallback."""
    ollama_host = getattr(settings, "OLLAMA_HOST", None) or getattr(
        settings, "OLLAMA_BASE_URL", None
    )
    if not ollama_host:
        return None
    model = getattr(settings, "OLLAMA_MODEL", "llama3.2")

    prompt = CV_ENRICHMENT.render(cv_text=cv_text[:8000])
    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(
                f"{ollama_host.rstrip('/')}/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                },
            )
            resp.raise_for_status()
            payload = (resp.json().get("response") or "").strip()
            data = json.loads(payload)
            if not isinstance(data, dict):
                return None
            data["_source"] = f"ollama:{CV_ENRICHMENT.name}:v{CV_ENRICHMENT.version}"
            return data
    except Exception as e:
        logger.warning(
            "[cv_parser] Ollama call failed (template=%s v%d): %s",
            CV_ENRICHMENT.name,
            CV_ENRICHMENT.version,
            e,
        )
        return None


async def parse_cv_with_claude(
    cv_text: str,
    *,
    model: str | None = None,
    template: PromptTemplate = CV_ENRICHMENT,
) -> Optional[dict[str, Any]]:
    """Publiczne wejście dla sparametryzowanego kroku Claude (bieg masowy).

    Cienki alias na `_parse_with_claude`: bieg masowy potrzebuje `model`/
    `template`, których `parse_cv()` nie wystawia, a import prywatnej nazwy
    między modułami wiąże konsumenta z wnętrzem tego pliku. Fallbacków
    (Ollama/regex) celowo tu NIE ma — patrz docstring runnera.
    """

    return await _parse_with_claude(cv_text, model=model, template=template)


async def parse_cv(
    cv_text: str,
    *,
    prefer_llm: bool = True,
    db: "AsyncSession | None" = None,
    model: str | None = None,
) -> dict[str, Any]:
    """
    Extract structured facts from CV text.

    With `prefer_llm=True` (default) the parser walks the hierarchy
    Claude → Ollama → regex; the first path that returns a non-None result
    wins. With `prefer_llm=False` only the regex heuristic runs (useful for
    deterministic tests and offline environments).

    `model` nadpisuje model KROKU CLAUDE'A dla wołającego, który ma własny wpis
    w rejestrze modeli i własną bramkę kwoty (uzupełnianie nazwisk z CV —
    `cv_name_backfill`). Taki wołający nie podaje `db`, bo bramka `cv_parser`
    naliczyłaby cudzy kubełek. Bez `model` krok idzie na model parsera CV.

    `db` włącza bramkę kwoty NA PŁATNYM KROKU: krok Claude'a idzie wtedy w
    `ai_feature(db, cv_parser)`, a wyczerpana kwota gasi wyłącznie Claude'a —
    Ollama i regex są darmowe i dalej działają. Bramka celowo NIE obejmuje
    całego parsera: kwota na LLM nie jest powodem, żeby onboarding z CV stracił
    także heurystyki, które nic nie kosztują. Wołający będący już wewnątrz
    własnego `ai_feature` (np. cv_match_preview) nie podaje `db` — podwójne
    naliczenie byłoby błędem, a `_assert_declared` widzi aktywny kontekst.

    Returns dict with keys: first_name, last_name, email, phone, city,
    years_it_experience, current_position, skills, education, languages,
    companies, career_summary, linkedin_url, _confidence, _source.

    Regex contact fallback fills any missing email/phone/first_name/last_name
    the LLM left empty — LLM values always win.
    """
    if not cv_text or not cv_text.strip():
        return _normalize_cv_output(_regex_fallback(""))

    if prefer_llm:
        claude = None
        if db is not None:
            from app.models.ai_feature import AIFeatureKey
            from app.services.ai_quota import AIQuotaExceeded, ai_feature

            try:
                async with ai_feature(db, AIFeatureKey.cv_parser):
                    claude = await _parse_with_claude(cv_text, model=model)
            except AIQuotaExceeded as quota_exc:
                logger.info(
                    "[cv_parser] krok Claude pominięty przez kwotę AI "
                    "(fallbacki działają dalej): %s",
                    quota_exc,
                )
        else:
            claude = await _parse_with_claude(cv_text, model=model)
        if claude is not None:
            return _normalize_cv_output(
                _apply_contact_fallbacks(
                    _with_linkedin_fallback(claude, cv_text), cv_text
                )
            )
        ollama = await _parse_with_ollama(cv_text)
        if ollama is not None:
            return _normalize_cv_output(
                _apply_contact_fallbacks(
                    _with_linkedin_fallback(ollama, cv_text), cv_text
                )
            )
    return _normalize_cv_output(_regex_fallback(cv_text))


def _with_linkedin_fallback(parsed: dict[str, Any], cv_text: str) -> dict[str, Any]:
    """Backstop: if the LLM missed `linkedin_url`, try the regex on raw text.

    Mutates a shallow copy so callers that re-use the dict don't see the
    fallback sneak in. Keeps the LLM's `_source` unchanged — the regex
    backfill is transparent to downstream bookkeeping.
    """

    if parsed.get("linkedin_url"):
        return parsed
    found = _extract_linkedin_from_text(cv_text)
    if not found:
        return parsed
    out = dict(parsed)
    out["linkedin_url"] = found
    return out
