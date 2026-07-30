"""Canonical candidate-location normalization and persistence.

``Candidate.city`` and ``Candidate.country`` are the only authored location
facts. ``Candidate.location`` is a compatibility projection rebuilt from them.
Automated sources must respect the manual locks written by the dedicated
location endpoint.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate

_COUNTRY_CODES = {
    "poland": "PL",
    "polska": "PL",
    "germany": "DE",
    "niemcy": "DE",
    "ukraine": "UA",
    "ukraina": "UA",
    "united kingdom": "GB",
    "great britain": "GB",
    "wielka brytania": "GB",
    "czech republic": "CZ",
    "czechia": "CZ",
    "czechy": "CZ",
    "slovakia": "SK",
    "słowacja": "SK",
    "slowacja": "SK",
    "france": "FR",
    "francja": "FR",
    "spain": "ES",
    "hiszpania": "ES",
    "italy": "IT",
    "włochy": "IT",
    "wlochy": "IT",
    "netherlands": "NL",
    "holandia": "NL",
    "sweden": "SE",
    "szwecja": "SE",
    "norway": "NO",
    "norwegia": "NO",
    "denmark": "DK",
    "dania": "DK",
    "finland": "FI",
    "finlandia": "FI",
    "portugal": "PT",
    "portugalia": "PT",
    "romania": "RO",
    "rumunia": "RO",
    "hungary": "HU",
    "węgry": "HU",
    "wegry": "HU",
    "united states": "US",
    "usa": "US",
}


@dataclass(frozen=True)
class CanonicalCandidateLocation:
    city: str | None
    country: str | None

    @property
    def projection(self) -> str | None:
        return project_candidate_location(self.city, self.country)


def _clean_city(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split()).strip(" ,")
    return cleaned[:120] or None


def _country_code(value: Any) -> str | None:
    if isinstance(value, dict):
        value = (
            value.get("code")
            or value.get("country_code")
            or value.get("countryCode")
            or value.get("name")
        )
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split()).strip(" ,")
    if re.fullmatch(r"[A-Za-z]{2}", cleaned):
        return cleaned.upper()
    return _COUNTRY_CODES.get(cleaned.casefold())


def _location_mapping(raw: Any) -> dict[str, Any] | None:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return None
    stripped = raw.strip()
    if not stripped.startswith("{"):
        return None
    try:
        parsed = json.loads(stripped)
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def normalize_candidate_location(
    *,
    city: Any = None,
    country: Any = None,
    raw_location: Any = None,
) -> CanonicalCandidateLocation:
    """Normalize explicit fields or an imported free-form/JSON location."""

    source = city if city not in (None, "") else raw_location
    mapping = _location_mapping(source)
    normalized_country = _country_code(country)
    if mapping is not None:
        normalized_city = _clean_city(
            mapping.get("locality")
            or mapping.get("city")
            or mapping.get("town")
            or mapping.get("place")
        )
        normalized_country = normalized_country or _country_code(
            mapping.get("country_code")
            or mapping.get("countryCode")
            or mapping.get("country")
        )
        return CanonicalCandidateLocation(normalized_city, normalized_country)

    normalized_city = _clean_city(source)
    if normalized_city and normalized_country is None:
        parts = [part.strip() for part in normalized_city.rsplit(",", 1)]
        if len(parts) == 2:
            inferred_country = _country_code(parts[1])
            if inferred_country:
                normalized_city = _clean_city(parts[0])
                normalized_country = inferred_country
    return CanonicalCandidateLocation(normalized_city, normalized_country)


def project_candidate_location(city: Any, country: Any) -> str | None:
    normalized_city = _clean_city(city)
    normalized_country = _country_code(country)
    projection = ", ".join(
        part for part in (normalized_city, normalized_country) if part
    )
    return projection[:255] or None


def _manual_lock(candidate: Candidate, field: str) -> bool:
    value = (candidate.cv_extracted_data or {}).get(f"_manual_override_{field}")
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes"}
    return value is True or value == 1


def apply_candidate_location_from_source(
    candidate: Candidate,
    *,
    city: Any = None,
    country: Any = None,
    raw_location: Any = None,
    overwrite_existing: bool,
) -> bool:
    """Apply an automated location while preserving manually locked fields."""

    incoming = normalize_candidate_location(
        city=city,
        country=country,
        raw_location=raw_location,
    )
    before = (candidate.city, candidate.country, candidate.location)

    if incoming.city and not _manual_lock(candidate, "city"):
        if overwrite_existing or not _clean_city(candidate.city):
            candidate.city = incoming.city
    if incoming.country and not _manual_lock(candidate, "country"):
        if overwrite_existing or not _country_code(candidate.country):
            candidate.country = incoming.country

    # Never author the compatibility field independently.
    candidate.location = project_candidate_location(candidate.city, candidate.country)
    return before != (candidate.city, candidate.country, candidate.location)


async def sync_candidate_location_from_source(
    db: AsyncSession,
    *,
    candidate_id: int,
    city: Any = None,
    country: Any = None,
    raw_location: Any = None,
    overwrite_existing: bool,
) -> bool:
    candidate = await db.scalar(
        select(Candidate)
        .where(Candidate.id == candidate_id)
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if candidate is None:
        raise LookupError(f"candidate {candidate_id} not found")
    changed = apply_candidate_location_from_source(
        candidate,
        city=city,
        country=country,
        raw_location=raw_location,
        overwrite_existing=overwrite_existing,
    )
    if changed:
        await db.flush()
    return changed
