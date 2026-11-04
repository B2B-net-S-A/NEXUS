"""Kiedy kandydat ostatnio używał technologii — z dat odczytu CV (27.10.2026).

Zgłoszenie Delivery Leada: tester z Angularem z lat 2019–2020 (testy
w Protractorze) miał „✓ angular” przy rekrutacji na fullstacka. Decyzja Artura:
technologia, której kandydat ostatnio używał ponad 3 lata temu, nie jest
spełnionym „musi mieć” — wiersz jest „?” z rokiem („angular · 2020”), bo
rekruter musi o to zapytać. Punkty „Dop.” się nie zmieniają (wagi zmienia
Head of Recruitment w panelu).

Daty: `last_used` w liście umiejętności (`candidates.skills`,
`cv_extracted_data.skills`) i na osi technologii z doświadczenia
(`cv_extracted_data.skill_timeline`), w kanonie `cv_parser._normalize_skill_dates`:
`present`, `RRRR-MM`, `RRRR`. Liczy się NAJPÓŹNIEJSZA znana data ze wszystkich
źródeł. Brak daty albo data nieczytelna to brak wiedzy, nie dowód, że
technologia jest stara — wtedy nic się nie zmienia (ta sama zasada co
`scoring_service._skill_recency_weights`).
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping, Optional

from app.core.scheduling import business_today

# Dokładnie 3 lata (36 miesięcy) jeszcze się liczy.
MAX_AGE_MONTHS = 36

_DATE = re.compile(r"^(\d{4})(?:-(\d{2}))?")


def _month_index(value: Any, today_index: int) -> Optional[int]:
    text = str(value or "").strip().casefold()
    if text == "present":
        return today_index
    match = _DATE.match(text)
    if not match:
        return None
    year, month = int(match.group(1)), int(match.group(2) or 12)
    if not 1 <= month <= 12:
        return None
    # Sam rok = do końca tego roku: na korzyść kandydata.
    return year * 12 + month - 1


def _dated_entries(candidate: Any) -> Iterable[tuple[str, Any]]:
    for item in getattr(candidate, "skills", None) or []:
        if isinstance(item, Mapping):
            yield str(item.get("name") or ""), item.get("last_used")
    extracted = getattr(candidate, "cv_extracted_data", None)
    if not isinstance(extracted, Mapping) or _curated(candidate, extracted):
        return
    for item in extracted.get("skills") or []:
        if isinstance(item, Mapping):
            yield str(item.get("name") or ""), item.get("last_used")
    for item in extracted.get("skill_timeline") or []:
        if isinstance(item, Mapping):
            yield str(item.get("skill") or ""), item.get("last_used")


def _curated(candidate: Any, extracted: Mapping) -> bool:
    # Lista poprawiona ręcznie jest całą prawdą (jak `candidate_known_skill_names`).
    return bool(
        getattr(candidate, "skills_manually_curated", False)
        or extracted.get("_manual_override_skills")
    )


def last_used_index(candidate: Any) -> dict[str, int]:
    """Klucz `_canon_skill` technologii → najpóźniejszy znany miesiąc użycia."""
    from app.services.scoring_service import _canon_skill, canonical_skill_names

    today = business_today()
    today_index = today.year * 12 + today.month - 1
    out: dict[str, int] = {}
    for name, last_used in _dated_entries(candidate):
        month = _month_index(last_used, today_index)
        if not name.strip() or month is None:
            continue
        for canonical in canonical_skill_names([name]):
            key = _canon_skill(canonical)
            out[key] = max(out.get(key, month), month)
    return out


def _wanted(name: str) -> set[str]:
    """Klucze, które `scoring_service.skill_present` uznaje za `name`."""
    from app.services.requirement_contract import alternatives
    from app.services.scoring_service import ALIAS_MAP, _canon_skill
    from app.services.skill_normalize import implied_forms

    options = alternatives(name)
    if len(options) > 1:
        return {
            key
            for option in options
            for key in _wanted(ALIAS_MAP.get(option.lower(), option))
        }
    return {_canon_skill(name), *(_canon_skill(form) for form in implied_forms(name))}


def stale_year(name: str, index: Mapping[str, int]) -> Optional[int]:
    """Rok ostatniego użycia, gdy technologia `name` jest starsza niż 3 lata.

    `None`, gdy jest świeża albo nie ma daty — wtedy wymaganie liczy się jak
    dotąd.
    """
    if not index:
        return None
    months = [index[key] for key in _wanted(name) if key in index]
    if not months:
        return None
    today = business_today()
    latest = max(months)
    if today.year * 12 + today.month - 1 - latest <= MAX_AGE_MONTHS:
        return None
    return latest // 12
