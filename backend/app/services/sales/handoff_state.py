"""Stan przekazania spotkania w ``custom_fields["handoff"]`` szansy i jego fazy.

Wspólne dla zapisu (``handoff.py``), list (``handoff_views.py``) i wyboru
prowadzącego (``handoff_hosts.py``). Blok jest zwykłym słownikiem JSON:

``booked_by``, ``booked_at``, ``service``, ``problem``, ``decision_maker``, ``timing``,
``meeting_at``, ``duration_minutes``, ``meeting_activity_id``, ``confirmed_at``,
``confirmed_by`` i ``verdict`` (``kind``, ``at``, ``by``, ``reason``, ``return_on``).
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Literal, Optional
from zoneinfo import ZoneInfo

from app.core.scheduling import DEFAULT_TZ, business_date, is_business_day
from app.models.sales import SalesOpportunity

HANDOFF_KEY = "handoff"
DEFAULT_DURATION = 30
#: Werdykty, po których spotkanie się odbyło.
HELD_VERDICTS: tuple[str, ...] = ("qualified", "not_now", "not_a_fit")
_MORNING = time(9, 0)

Phase = Literal["no_term", "upcoming", "confirm", "verdict", "done"]
VerdictKind = Literal["qualified", "not_now", "not_a_fit", "no_show"]


def clean(value: Optional[str]) -> Optional[str]:
    return (value or "").strip() or None


def block(opportunity: SalesOpportunity) -> Optional[dict[str, Any]]:
    """Kopia bloku przekazania; ``None``, gdy szansa go nie ma."""

    raw = (opportunity.custom_fields or {}).get(HANDOFF_KEY)
    return dict(raw) if isinstance(raw, dict) else None


def store(opportunity: SalesOpportunity, data: dict[str, Any]) -> None:
    # Nowy słownik: SQLAlchemy widzi przypisanie, nie mutację JSON-a.
    opportunity.custom_fields = {**(opportunity.custom_fields or {}), HANDOFF_KEY: data}


def moment(value: Any) -> Optional[datetime]:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def day_of(value: Any) -> Optional[date]:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def user_id_of(value: Any) -> Optional[int]:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def to_utc(moment: datetime) -> datetime:
    """Chwila bez strefy to czas firmy: tak wpisuje ją formularz bez przeglądarki."""

    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=ZoneInfo(DEFAULT_TZ))
    return moment.astimezone(timezone.utc)


def booked_by():
    return SalesOpportunity.custom_fields[HANDOFF_KEY]["booked_by"].astext


def has_handoff():
    return SalesOpportunity.custom_fields.has_key(HANDOFF_KEY)


def _business(day: date) -> bool:
    return is_business_day(datetime.combine(day, time(12), tzinfo=ZoneInfo(DEFAULT_TZ)))


def previous_business_day(day: date) -> date:
    current = day - timedelta(days=1)
    while not _business(current):
        current -= timedelta(days=1)
    return current


def next_business_day(day: date) -> date:
    current = day + timedelta(days=1)
    while not _business(current):
        current += timedelta(days=1)
    return current


def morning(day: date) -> datetime:
    return datetime.combine(day, _MORNING, tzinfo=ZoneInfo(DEFAULT_TZ)).astimezone(
        timezone.utc
    )


def phase_of(
    meeting_at: Optional[datetime], confirmed_at: Optional[datetime], now: datetime
) -> Phase:
    """Co jest do zrobienia: termin, potwierdzenie dzień wcześniej albo werdykt."""

    if meeting_at is None:
        return "no_term"
    if meeting_at <= now:
        return "verdict"
    confirm_from = previous_business_day(business_date(meeting_at))
    if confirmed_at is None and business_date(now) >= confirm_from:
        return "confirm"
    return "upcoming"
