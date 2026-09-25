"""Prywatne spotkania z kalendarzy zewnętrznych (Outlook, iCal).

Kalendarz NEXUSA widzą także admin, Head of Recruitment i Finanse, więc
spotkanie oznaczone w Outlooku jako prywatne (``sensitivity`` = ``private``
albo ``confidential``; w iCal ``CLASS:PRIVATE``/``CONFIDENTIAL``) wchodzi
wyłącznie jako zajęty termin: bez tematu, opisu, uczestników, miejsca i linku
do spotkania (decyzja Artura 25.09.2026, audyt R3-7).
"""

from __future__ import annotations

from typing import Any, Optional

PRIVATE_EVENT_TITLE = "Spotkanie prywatne"

_PRIVATE_MARKERS = frozenset({"private", "confidential"})

# Pola nadpisywane w wierszu prywatnego spotkania (uczestników czyści wołający
# — mają różne kształty w Outlooku i iCal).
PRIVATE_EVENT_FIELDS: dict[str, Any] = {
    "title": PRIVATE_EVENT_TITLE,
    "description": None,
    "location": None,
    "teams_link": None,
    "online_meeting_url": None,
}


def is_private_marker(value: Optional[Any]) -> bool:
    """Czy ``sensitivity`` (Graph) albo ``CLASS`` (iCal) oznacza prywatne."""
    return str(value or "").strip().casefold() in _PRIVATE_MARKERS


def is_scrubbed(event: Any) -> bool:
    """Czy zapisany wiersz nie niesie już treści prywatnego spotkania."""
    return (
        getattr(event, "title", None) == PRIVATE_EVENT_TITLE
        and not getattr(event, "description", None)
        and not getattr(event, "location", None)
        and not getattr(event, "teams_link", None)
        and not getattr(event, "online_meeting_url", None)
        and not getattr(event, "attendees", None)
    )


__all__ = [
    "PRIVATE_EVENT_FIELDS",
    "PRIVATE_EVENT_TITLE",
    "is_private_marker",
    "is_scrubbed",
]
