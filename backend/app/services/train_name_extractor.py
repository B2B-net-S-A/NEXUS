"""Regex-first `train_name` extractor (Phase 15 / Phase D).

Called best-effort on Job create/update to auto-tag roles with their programme
or Agile Release Train identifier, which the historical-jobs retrieval uses
as a same-train boost.

Design
------
- Regex + per-client dictionary first. NO LLM fallback in MVP — false
  positives on an auto-tagged field would hurt retrieval precision more than
  missing tags.
- Return `None` on any ambiguity; callers leave the column as NULL and the
  DL can set it manually via the Job form.
- Pure function: `extract_train_name(text, client_slug=None) -> Optional[str]`.

Tested patterns target Nordea's public naming scheme + a couple of generic
Agile-Release-Train markers. Extend the per-client dict when new clients ask
for auto-tagging.
"""

from __future__ import annotations

import re
from typing import Optional

# ── Generic patterns ────────────────────────────────────────────────────────
# Case-insensitive, anchored to word boundaries. Each regex MUST produce a
# single capturing group with the canonical train identifier.

# Match 1..4 Title-Case / UPPERCASE words (optionally joined by `&`, `-`, `/`).
# This stops at the first lowercase word boundary, which is the heuristic that
# separates the train identifier ("Open Banking") from the surrounding Polish
# prose ("w banku komercyjnym"). Numbers and single-letter tokens (e.g.
# "TRAIN X") are also allowed — the downstream `_clean_captured` rejects
# matches that are too short or contain no alphabetic character.
_TITLE_CASE_SEQUENCE = (
    r"([A-Z0-9][A-Za-z0-9]*"
    r"(?:[\s&/\-]+[A-Z0-9][A-Za-z0-9]*){0,3})"
)

# Trigger words are recognised case-insensitively via `(?i:...)`, but the
# captured sequence itself is case-SENSITIVE so lowercase Polish connectors
# ("w", "na", "dla", "banku") terminate the match cleanly.
_GENERIC_PATTERNS: tuple[re.Pattern[str], ...] = (
    # "ART Payments", "art: Mortgages", "ART - Data & Analytics"
    re.compile(rf"\b(?i:ART)[\s:\-]+{_TITLE_CASE_SEQUENCE}"),
    # "TRAIN X", "Train-5", "TRAIN: Platform"
    re.compile(rf"\b(?i:TRAIN)[\s:\-]+{_TITLE_CASE_SEQUENCE}"),
    # "Release Train Payments" / "Agile Release Train CIB"
    re.compile(rf"\b(?i:(?:Agile\s+)?Release\s+Train)[\s:\-]+{_TITLE_CASE_SEQUENCE}"),
    # "Programme: Open Banking" / "program - Mortgages"
    re.compile(rf"\b(?i:Program(?:me)?)[\s:\-]+{_TITLE_CASE_SEQUENCE}"),
)

# ── Per-client dictionaries ────────────────────────────────────────────────
# Keys are lowercased client slugs/names; values are tuples of canonical train
# names we accept as literal substrings (case-insensitive) inside the text.

_CLIENT_TRAIN_DICT: dict[str, tuple[str, ...]] = {
    "nordea": (
        "CIB Payments",
        "CIB Mortgages",
        "CIB Lending",
        "Payments",
        "Mortgages",
        "Data & Analytics",
        "Digital Channels",
        "Financial Crime Prevention",
        "Open Banking",
    ),
}


# ── Public API ──────────────────────────────────────────────────────────────


def extract_train_name(text: str, client_slug: Optional[str] = None) -> Optional[str]:
    """Return the most likely train name in ``text`` or ``None``.

    Args:
        text: Free-form input. Typically ``f"{job.title}\\n{job.description}"``.
        client_slug: Lowercased client name or slug. When provided, tries the
            client-specific dictionary before falling back to generic regexes.

    Returns:
        The extracted train name (already trimmed) or ``None`` if the input is
        ambiguous, empty, or matches nothing with confidence.
    """
    if not text or not text.strip():
        return None

    if client_slug:
        key = client_slug.strip().lower()
        for canonical in _CLIENT_TRAIN_DICT.get(key, ()):
            pattern = re.compile(r"\b" + re.escape(canonical) + r"\b", re.IGNORECASE)
            if pattern.search(text):
                return canonical

    for pattern in _GENERIC_PATTERNS:
        match = pattern.search(text)
        if match:
            captured = match.group(1)
            cleaned = _clean_captured(captured)
            if cleaned:
                return cleaned

    return None


def _clean_captured(raw: str) -> Optional[str]:
    """Normalise a captured group — strip trailing punctuation / articles.

    Rejects captures that look like junk (single letters, pure numbers, stop
    words) so we don't persist false positives into the ``train_name``
    column.
    """
    cleaned = raw.strip().rstrip(",.;:")
    # Collapse internal whitespace.
    cleaned = re.sub(r"\s+", " ", cleaned)
    if not cleaned:
        return None
    # Reject very short matches — "ART A", "TRAIN X" is borderline useful but
    # "TRAIN 1" alone tells us nothing about the programme, so require at
    # least one alphabetic character AND ≥3 chars total.
    if len(cleaned) < 3:
        return None
    if not any(ch.isalpha() for ch in cleaned):
        return None
    return cleaned
