"""Pure resolvers for the candidate quick-view projection.

The drawer must not guess from presentation-only aliases. These helpers keep
the precedence rules for current role, source attribution and CV-derived AI
highlights in one unit-testable place.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Optional

from app.models.candidate import Candidate

_SOURCE_LABELS = {
    "linkedin": "LinkedIn",
    "linkedin_extension": "LinkedIn",
    "pracuj": "Pracuj.pl",
    "pracuj.pl": "Pracuj.pl",
    "traffit": "TRAFFIT",
    "jjit": "Just Join IT",
    "justjoinit": "Just Join IT",
    "referral": "Polecenie",
    "database": "Baza kandydatów",
    "manual": "Dodany manualnie",
    "cv_upload": "CV upload",
    "apply_submission": "Formularz aplikacyjny",
    "talent_radar": "Talent Radar",
}

_CV_SOURCE_PREFIXES = ("claude:", "ollama:", "regex")
_SECTOR_LABELS = {
    "banking": "Bankowość",
    "bankowość": "Bankowość",
    "finance": "Finanse",
    "finanse": "Finanse",
    "financial services": "Usługi finansowe",
    "government": "Administracja publiczna",
    "public administration": "Administracja publiczna",
    "administracja publiczna": "Administracja publiczna",
    "telecommunications": "Telekomunikacja",
    "telecom": "Telekomunikacja",
    "telekomunikacja": "Telekomunikacja",
    "ecommerce": "E-commerce",
    "e-commerce": "E-commerce",
}


def _clean_text(value: Any, *, limit: int = 255) -> Optional[str]:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split()).strip()
    return cleaned[:limit] or None


def _label_source(value: Any) -> Optional[str]:
    cleaned = _clean_text(value, limit=120)
    if not cleaned:
        return None
    if cleaned.casefold().startswith("invite_link:"):
        return "Formularz aplikacyjny"
    return _SOURCE_LABELS.get(cleaned.casefold(), cleaned)


def resolve_source(candidate: Candidate) -> dict[str, Optional[str]]:
    """Resolve first-touch source separately from the import transport."""

    traffit_source: Optional[str] = None
    tags = candidate.tags if isinstance(candidate.tags, list) else []
    for tag in tags:
        if isinstance(tag, dict) and tag.get("type") == "traffit_source":
            traffit_source = _label_source(tag.get("value"))
            if traffit_source:
                break

    acquisition = traffit_source or _label_source(candidate.source)
    imported_via = _label_source(candidate.external_source)
    if imported_via in {None, "Dodany manualnie"}:
        imported_via = None
    if imported_via == acquisition:
        imported_via = None

    creator = getattr(candidate, "creator", None)
    return {
        "added_by_name": _clean_text(getattr(creator, "name", None))
        or "System / import",
        "acquisition_source": acquisition,
        "imported_via": imported_via,
    }


def _parse_started_at(value: Any) -> tuple[Optional[str], str]:
    if isinstance(value, datetime):
        return value.date().isoformat(), "date"
    if isinstance(value, date):
        return value.isoformat(), "date"
    cleaned = _clean_text(value, limit=32)
    if not cleaned:
        return None, "unknown"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", cleaned):
        return cleaned, "date"
    if re.fullmatch(r"\d{4}-\d{2}", cleaned):
        return cleaned, "month"
    if re.fullmatch(r"\d{4}", cleaned):
        return cleaned, "year"
    match = re.search(r"\b(19|20)\d{2}\b", cleaned)
    return (match.group(0), "year") if match else (None, "unknown")


def _experience_rows(candidate: Candidate) -> list[dict[str, Any]]:
    experience = candidate.experience
    if isinstance(experience, list):
        return [row for row in experience if isinstance(row, dict)]
    return []


def _is_current_experience(row: dict[str, Any]) -> bool:
    end = row.get("end") or row.get("end_date") or row.get("to")
    if end is None:
        return True
    if isinstance(end, str):
        return end.strip().casefold() in {
            "",
            "present",
            "current",
            "obecnie",
            "teraz",
        }
    return False


def resolve_current_position(candidate: Candidate) -> dict[str, Optional[str]]:
    """LinkedIn → active experience → CV/Traffit, with date precision."""

    title = _clean_text(candidate.linkedin_current_title)
    if title:
        started_at, precision = _parse_started_at(candidate.linkedin_current_started_at)
        return {
            "title": title,
            "started_at": started_at,
            "precision": precision,
        }

    current_rows = [
        row for row in _experience_rows(candidate) if _is_current_experience(row)
    ]
    if current_rows:
        current_rows.sort(
            key=lambda row: _parse_started_at(
                row.get("start") or row.get("start_date") or row.get("from")
            )[0]
            or "",
            reverse=True,
        )
        row = current_rows[0]
        title = _clean_text(row.get("role") or row.get("title") or row.get("position"))
        if title:
            started_at, precision = _parse_started_at(
                row.get("start") or row.get("start_date") or row.get("from")
            )
            return {
                "title": title,
                "started_at": started_at,
                "precision": precision,
            }

    extracted = (
        candidate.cv_extracted_data
        if isinstance(candidate.cv_extracted_data, dict)
        else {}
    )
    highlights = (
        extracted.get("cv_highlights")
        if isinstance(extracted.get("cv_highlights"), dict)
        else {}
    )
    title = _clean_text(
        highlights.get("current_role")
        or extracted.get("current_position")
        or extracted.get("traffit_Position")
    )
    started_at, precision = _parse_started_at(
        highlights.get("current_role_started_at")
        or extracted.get("current_position_started_at")
    )
    return {"title": title, "started_at": started_at, "precision": precision}


def _unique_texts(values: Any, *, limit: int) -> list[str]:
    if not isinstance(values, list):
        return []
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        if isinstance(value, dict):
            value = value.get("name")
        cleaned = _clean_text(value, limit=80)
        if not cleaned or cleaned.casefold() in seen:
            continue
        seen.add(cleaned.casefold())
        output.append(cleaned)
        if len(output) >= limit:
            break
    return output


def _normalized_sectors(values: Any) -> list[str]:
    sectors = _unique_texts(values, limit=4)
    return [_SECTOR_LABELS.get(sector.casefold(), sector) for sector in sectors]


def _first_sentence(value: Any) -> Optional[str]:
    cleaned = _clean_text(value, limit=600)
    if not cleaned:
        return None
    sentence = re.split(r"(?<=[.!?])\s+", cleaned, maxsplit=1)[0]
    if len(sentence) > 240:
        sentence = sentence[:237].rstrip() + "…"
    return sentence


def format_cv_highlight_bullets(highlights: dict[str, Any]) -> list[str]:
    """Format at most four Polish bullets from CV facts, without inference."""

    bullets: list[str] = []
    profile = _first_sentence(highlights.get("profile"))
    years = highlights.get("years_experience")
    role = _clean_text(highlights.get("current_role"), limit=160)
    started_at, precision = _parse_started_at(highlights.get("current_role_started_at"))

    valid_years = isinstance(years, int) and 0 < years <= 60
    if profile:
        if valid_years and not re.search(
            rf"\b{years}(?:[- ]let|\s+lat)\b",
            profile,
            flags=re.IGNORECASE,
        ):
            bullets.append(f"{profile.rstrip('.')} · {years} lat doświadczenia.")
        else:
            bullets.append(profile)
    elif role and valid_years:
        bullets.append(f"{role} z {years}-letnim doświadczeniem.")
    elif valid_years:
        bullets.append(f"{years} lat doświadczenia w IT.")

    if role:
        if started_at:
            if precision == "date":
                label = started_at
            elif precision == "month":
                label = started_at.replace("-", ".")
            else:
                label = started_at
            bullets.append(f"Aktualna rola: {role}, od {label}.")
        elif not bullets or role.casefold() not in bullets[0].casefold():
            bullets.append(f"Aktualna rola: {role}.")

    technologies = _unique_texts(highlights.get("technologies"), limit=8)
    if technologies:
        bullets.append(f"Technologie: {', '.join(technologies)}.")

    sectors = _normalized_sectors(highlights.get("sectors"))
    if sectors:
        bullets.append(f"Sektory: {', '.join(sectors)}.")

    return bullets[:4]


def resolve_cv_highlights(candidate: Candidate) -> dict[str, Any]:
    """Return only CV-provenanced facts; never trust generic ``ai_summary``."""

    extracted = (
        candidate.cv_extracted_data
        if isinstance(candidate.cv_extracted_data, dict)
        else {}
    )
    nested = (
        dict(extracted.get("cv_highlights"))
        if isinstance(extracted.get("cv_highlights"), dict)
        else {}
    )
    source = _clean_text(
        nested.get("extractor_version") or extracted.get("_source"), limit=120
    )
    trusted = bool(source and source.startswith(_CV_SOURCE_PREFIXES))

    if not nested and trusted:
        nested = {
            "profile": extracted.get("professional_profile")
            or extracted.get("career_summary"),
            "years_experience": extracted.get("years_it_experience"),
            "current_role": extracted.get("current_position"),
            "current_role_started_at": extracted.get("current_position_started_at"),
            "current_role_started_at_precision": extracted.get(
                "current_position_started_at_precision"
            ),
            "technologies": extracted.get("technologies") or extracted.get("skills"),
            "sectors": extracted.get("sectors") or extracted.get("industries"),
            "extractor_version": source,
        }

    if not nested or not trusted:
        return {
            "profile": None,
            "years_experience": None,
            "current_role": None,
            "current_role_started_at": None,
            "current_role_started_at_precision": "unknown",
            "technologies": [],
            "sectors": [],
            "bullets": [],
            "source_document_id": None,
            "source_hash": None,
            "extractor_version": None,
            "generated_at": None,
        }

    technologies = _unique_texts(nested.get("technologies"), limit=8)
    sectors = _normalized_sectors(nested.get("sectors"))
    started_at, detected_precision = _parse_started_at(
        nested.get("current_role_started_at")
    )
    precision = nested.get("current_role_started_at_precision")
    if precision not in {"date", "month", "year"}:
        precision = detected_precision

    resolved = {
        "profile": _first_sentence(nested.get("profile")),
        "years_experience": nested.get("years_experience"),
        "current_role": _clean_text(nested.get("current_role"), limit=160),
        "current_role_started_at": started_at,
        "current_role_started_at_precision": precision,
        "technologies": technologies,
        "sectors": sectors,
        "source_document_id": nested.get("source_document_id"),
        "source_hash": _clean_text(nested.get("source_hash"), limit=64),
        "extractor_version": _clean_text(
            nested.get("extractor_version") or source, limit=120
        ),
        "generated_at": nested.get("generated_at"),
    }
    resolved["bullets"] = format_cv_highlight_bullets(resolved)
    return resolved
