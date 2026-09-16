"""Sparsowane CV (``services.cv_parser.parse_cv``) → payload kandydata w Traffit.

Port ``merge_and_translate`` + ``build_traffit_payload`` ze scrapera, ale na
kluczach, które zwraca parser NEXUS-a (``first_name``, ``phone``, ``skills``,
``years_it_experience``…), zamiast promptu Haiku ze scrapera. Słowniki ID
(języki, kraje) i etykiety PL są skopiowane 1:1 — Traffit ich wymaga.
"""

from __future__ import annotations

import re
from typing import Any

EXPERIENCE_BUCKETS = ("Poniżej 2", "2-5", "5+")
COUNTRY_IDS = {
    "Poland": 0,
    "Polska": 0,
    "Germany": 55,
    "Niemcy": 55,
    "Ukraine": 72,
    "Ukraina": 72,
    "Great Britain": 75,
    "United Kingdom": 75,
    "France": 35,
    "Netherlands": 39,
    "Spain": 38,
    "Italy": 76,
    "United States": 66,
    "Canada": 47,
    "India": 40,
    "Czech Republic": 27,
    "Slovakia": 64,
    "Romania": 62,
    "Lithuania": 50,
    "Latvia": 53,
}
LANGUAGE_IDS = {
    "polish": 0,
    "polski": 0,
    "english": 1,
    "angielski": 1,
    "german": 2,
    "niemiecki": 2,
    "french": 4,
    "francuski": 4,
    "spanish": 9,
    "hiszpański": 9,
    "italian": 11,
    "włoski": 11,
    "russian": 19,
    "rosyjski": 19,
    "ukrainian": 22,
    "ukraiński": 22,
    "czech": 13,
    "czeski": 13,
    "dutch": 5,
    "portuguese": 10,
    "swedish": 6,
    "norwegian": 7,
}
EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")


def is_valid_email(email: str | None) -> bool:
    return bool(email) and len(email) <= 254 and bool(EMAIL_RE.match(email))


def experience_bucket(years: Any) -> str:
    try:
        y = float(years)
    except (TypeError, ValueError):
        return ""
    if y < 2:
        return "Poniżej 2"
    if y <= 5:
        return "2-5"
    return "5+"


def education_label(education: Any) -> str:
    """Parser zwraca listę wpisów (string/dict) — szukamy najwyższego poziomu."""
    text = " ".join(
        (e.get("degree") or e.get("school") or e.get("name") or "")
        if isinstance(e, dict)
        else str(e)
        for e in (education or [])
    ).lower()
    if not text:
        return ""
    if any(k in text for k in ("informaty", "computer science", "software", "it ")):
        return "Wykształcenie wyższe informatyczne"
    if any(
        k in text
        for k in (
            "magister",
            "inżynier",
            "licencjat",
            "master",
            "bachelor",
            "msc",
            "bsc",
            "uniwersytet",
            "politechnika",
            "university",
            "studia",
        )
    ):
        return "Wykształcenie wyższe"
    if any(
        k in text
        for k in ("liceum", "technikum", "secondary", "high school", "średnie")
    ):
        return "Wykształcenie średnie"
    return ""


def _names(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, dict):
        for key in ("name", "language", "label", "skill", "company"):
            if isinstance(value.get(key), str) and value[key].strip():
                return [value[key].strip()]
        return [n for v in value.values() for n in _names(v)]
    if isinstance(value, (list, tuple, set)):
        return [n for item in value for n in _names(item)]
    return []


def language_ids(languages: Any) -> list[int]:
    ids: list[int] = []
    for name in _names(languages):
        key = name.split("(")[0].strip().lower()
        if key in LANGUAGE_IDS and LANGUAGE_IDS[key] not in ids:
            ids.append(LANGUAGE_IDS[key])
    return ids


def build_traffit_payload(parsed: dict, *, fallback: dict, offer_title: str) -> dict:
    """``parsed`` = wynik ``parse_cv``; ``fallback`` = dane z panelu (imię, nazwisko, email)."""
    first = (parsed.get("first_name") or fallback.get("first_name") or "").strip()
    last = (parsed.get("last_name") or fallback.get("last_name") or "").strip()
    email = (parsed.get("email") or "").strip()
    if not is_valid_email(email):
        email = (fallback.get("email") or "").strip()
    companies = [c for c in _names(parsed.get("companies")) if c]
    country = parsed.get("country") or parsed.get("location_country")
    return {
        "name": first,
        "lastname": last,
        "email": email,
        "mobile": (parsed.get("phone") or "").strip(),
        "linkedin": (parsed.get("linkedin_url") or "").strip(),
        "candidate_about": (parsed.get("career_summary") or "").strip(),
        "_certificates": ", ".join(_names(parsed.get("certifications"))),
        "_technologie": ", ".join(_names(parsed.get("skills"))),
        "_education": [education_label(parsed.get("education"))]
        if education_label(parsed.get("education"))
        else [],
        "_experience": [experience_bucket(parsed.get("years_it_experience"))]
        if experience_bucket(parsed.get("years_it_experience")) in EXPERIENCE_BUCKETS
        else [],
        "source": "E-mail",
        "_Position": (parsed.get("current_position") or offer_title or "").strip(),
        "candidate_languages": language_ids(parsed.get("languages")),
        "_nationality": COUNTRY_IDS.get(str(country)) if country else None,
        "_previous_employers": "\n".join(
            f"{i + 1}. {c}" for i, c in enumerate(companies)
        ),
    }
