"""Champion Profile change detection.

Utilities used by the PUT /jobs/{id}/champion-profile handler to decide
whether a write actually changed content (avoid no-op notifications) and
which top-level sections changed (payload for WS event).
"""

from typing import Any, Iterable


# Siedem sekcji szablonu (09.2026). Bloki server-stamped (`verification`,
# `briefing`, `recommended_searches`) świadomie POZA listą: mają własne
# endpointy i własne powiadomienia, a zwykły zapis profilu ich nie dotyka —
# gdyby tu były, każdy zapis raportowałby zmianę czegoś, czego nie zmienił.
_SECTIONS: tuple[str, ...] = (
    "basics",
    "search",
    "stack",
    "project",
    "screening_questions",
    "client",
    "documents",
)


def _normalize(value: Any) -> Any:
    """Canonical form for equality checks.

    - Empty strings, empty dicts, empty lists all collapse to ``None`` so
      that toggling a field between "" and unset doesn't register as a
      change.
    - Dicts are returned with sorted keys.
    """
    if value is None:
        return None
    if isinstance(value, str):
        trimmed = value.strip()
        return trimmed or None
    if isinstance(value, dict):
        cleaned = {k: _normalize(v) for k, v in value.items()}
        cleaned = {k: v for k, v in cleaned.items() if v is not None}
        return cleaned or None
    if isinstance(value, list):
        cleaned = [_normalize(v) for v in value]
        cleaned = [v for v in cleaned if v is not None]
        return cleaned or None
    return value


def diff_champion_profile(old: dict | None, new: dict | None) -> list[str]:
    """Return the top-level sections that differ between two profiles.

    Empty input dicts are treated as "no profile yet" (all of ``_SECTIONS``
    are compared). The result preserves the canonical order from
    ``_SECTIONS`` so downstream UI can rely on a stable list.
    """
    old_norm = _normalize(old or {}) or {}
    new_norm = _normalize(new or {}) or {}
    if not isinstance(old_norm, dict) or not isinstance(new_norm, dict):
        return list(_SECTIONS)
    changed: list[str] = []
    for section in _SECTIONS:
        if old_norm.get(section) != new_norm.get(section):
            changed.append(section)
    return changed


def summarize_sections(sections: Iterable[str]) -> str:
    """Polish human-readable summary for notification message."""
    labels = {
        "basics": "podstawowe informacje",
        "search": "co wpisać w wyszukiwarkę",
        "stack": "stack technologiczny",
        "project": "opis projektu",
        "screening_questions": "pytania screeningowe",
        "client": "informacje o kliencie",
        "documents": "dokumenty",
    }
    named = [labels.get(s, s) for s in sections]
    if not named:
        return ""
    if len(named) == 1:
        return named[0]
    if len(named) == 2:
        return f"{named[0]} i {named[1]}"
    return ", ".join(named[:-1]) + f" i {named[-1]}"
