"""Shared location parsing/matching for candidate↔job matching.

Both ``candidate.location`` and ``job.location`` appear in two shapes in
production:

  • plain text — ``"Warszawa"``, ``"Kraków / remote"``
  • the structured JSON blob Traffit/TalentRadar imports store verbatim:
    ``{"locality":"Warszawa","region1":"Mazowieckie","country":"Polska",...}``

8 242 of 8 305 located candidates are the blob shape (the structured
``city``/``region`` columns were never backfilled), so ``location`` is the only
usable source and parsing the blob is mandatory — a raw-string substring
compare against the blob practically never matches.

Extracted from ``app.api.matching`` (PR #424) so the legacy ``/ai-matches``
engine, the hybrid ``/recommendations`` engine and the composite
``scoring_service._score_location`` layer all share one implementation.
"""

from __future__ import annotations

import json
import re

# Place keys read out of the structured blob, in rough specificity order.
# Coordinates / postcode are intentionally excluded — they are not place names.
_BLOB_PLACE_KEYS = ("locality", "city", "region1", "region2", "region3", "country")

# Plain-text location separators ("Kraków / remote", "Gdańsk, Pomorskie").
_TEXT_SEPARATORS = re.compile(r"[,/;|]+")


def location_tokens(raw: object) -> set[str]:
    """Normalized lowercase place tokens from a location value (blob or text).

    Returns the set of meaningful place tokens (locality, regions, country);
    an empty set when nothing usable is present. A blob that fails to parse
    yields an empty set rather than leaking the raw JSON string in as a junk
    plaintext token.
    """
    if not raw:
        return set()
    s = str(raw).strip()
    if not s:
        return set()
    tokens: set[str] = set()
    if s.startswith("{"):
        try:
            data = json.loads(s)
        except (ValueError, TypeError):
            return set()
        if isinstance(data, dict):
            for key in _BLOB_PLACE_KEYS:
                v = data.get(key)
                if isinstance(v, str) and v.strip():
                    tokens.add(v.strip().lower())
        return tokens
    for part in _TEXT_SEPARATORS.split(s.lower()):
        part = part.strip()
        if part:
            tokens.add(part)
    return tokens


def tokens_overlap(a: set[str], b: set[str]) -> bool:
    """Substring-tolerant overlap between two token sets (either direction).

    ``"warszawa"`` matches ``"warszawa, mazowieckie"`` and vice-versa. Empty on
    either side → no overlap.
    """
    if not a or not b:
        return False
    for x in a:
        for y in b:
            if x == y or x in y or y in x:
                return True
    return False


def location_matches(requested_tokens: set[str], candidate_location: object) -> bool:
    """True if a candidate's location is compatible with the requested tokens.

    No request tokens → no filter (everyone passes). A candidate with no
    parseable location is excluded under an active filter (standard search
    semantics, mirroring the manual-search ``location_cities`` behaviour).
    """
    if not requested_tokens:
        return True
    cand_tokens = location_tokens(candidate_location)
    if not cand_tokens:
        return False
    return tokens_overlap(requested_tokens, cand_tokens)
