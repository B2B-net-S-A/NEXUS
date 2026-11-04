"""Wydarzenie „Poza biurem” w kalendarzu osoby (czysty moduł).

Tytuł stały, wydarzenie prywatne i bez treści — kalendarz widzi cały zespół,
a rodzaj nieobecności znają tylko osoba, przełożony i Kadry (D6). Compass
wpisywał rodzaj w tytuł („[Compass] L4 / chorobowe”) i notatkę w treść.

Pół dnia to wydarzenie godzinowe (8–12 albo 12–16), przy tworzeniu
i przy KAŻDEJ zmianie — Compass przy edycji zapisywał zawsze całodniowe
i gubił godziny połówki.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Optional

from app.core.scheduling import DEFAULT_TZ
from app.services.hr.leave_m365 import CALENDAR_SUBJECT

CATEGORY = "NEXUS"
HALF_DAY_HOURS: dict[str, tuple[str, str]] = {
    "morning": ("08:00:00", "12:00:00"),
    "afternoon": ("12:00:00", "16:00:00"),
}


def transaction_id(leave_id: str) -> str:
    return f"nexus-leave-{leave_id}"


def known_transaction_ids(leave_id: str) -> frozenset[str]:
    """Nasz ``transactionId`` i Compassa (``leave-{id}``) — ten sam UUID po imporcie."""

    return frozenset({transaction_id(leave_id), f"leave-{leave_id}"})


def event_body(
    *,
    start: date,
    end: date,
    half_day: Optional[str],
    transaction: Optional[str] = None,
) -> dict[str, Any]:
    """Ciało POST (z ``transactionId``) albo PATCH (bez) wydarzenia."""

    hours = HALF_DAY_HOURS.get(half_day or "") if start == end else None
    if hours:
        timing: dict[str, Any] = {
            "isAllDay": False,
            "start": {
                "dateTime": f"{start.isoformat()}T{hours[0]}",
                "timeZone": DEFAULT_TZ,
            },
            "end": {
                "dateTime": f"{start.isoformat()}T{hours[1]}",
                "timeZone": DEFAULT_TZ,
            },
        }
    else:
        # Całodniowe: północ do północy, koniec wyłączny (dzień po ostatnim).
        timing = {
            "isAllDay": True,
            "start": {
                "dateTime": f"{start.isoformat()}T00:00:00",
                "timeZone": DEFAULT_TZ,
            },
            "end": {
                "dateTime": f"{(end + timedelta(days=1)).isoformat()}T00:00:00",
                "timeZone": DEFAULT_TZ,
            },
        }
    body: dict[str, Any] = {
        "subject": CALENDAR_SUBJECT,
        **timing,
        "showAs": "oof",
        "sensitivity": "private",
        "categories": [CATEGORY],
        "isReminderOn": False,
        "body": {"contentType": "text", "content": ""},
    }
    if transaction:
        body["transactionId"] = transaction
    return body
