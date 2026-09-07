"""Resource-level access policy for calendar events (P1-CALENDAR-01).

Finding: ``backend/app/api/calendar.py`` gated the calendar routes by *role*
only (``RecruitmentReadAccess`` / ``CalendarWriteAccess``). Any operational
user could therefore LIST every event, GET any event by id, and PATCH/DELETE
anyone else's event — leaking attendee emails, descriptions, candidate/client
references and meeting/recording links across the whole org.

This module adds the *resource* decision on top of the existing role gate. The
role guard stays (viewer/client ``user`` is still excluded everywhere); this
narrows an operational user to the events they actually have a relationship
with.

Access rule
-----------
A user may **view** a ``CalendarEvent`` if any of:

* they are the **owner** (``created_by`` / organizer), or
* they are a **participant** (their email appears in ``attendees``), or
* they hold an org-wide override role (**admin** / **head_of_recruitment**).

A user may **mutate** (PATCH/DELETE) a ``CalendarEvent`` only if they are the
**owner** or hold the org-wide override role. A participant who is not the
owner can view (a redacted projection) but never mutate.

Two ``attendees`` storage shapes exist in the wild and both are handled:

* plain email strings — ``["a@example.com", ...]`` (``POST /calendar/events``)
* Graph objects — ``[{"address": "a@example.com"}, ...]`` (M365 invite path)

Role membership is evaluated via ``User.has_any_role`` so a multi-role user
(primary ``role`` + secondary ``roles``) is handled correctly.
"""

from __future__ import annotations

from typing import Any, Iterator, Optional

from sqlalchemy import ColumnElement, and_, func, or_, text, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import Activity
from app.models.calendar_event import CalendarEvent, EventStatus
from app.models.user import User, UserRole
from app.services.workforce_availability import operational_owner_ids

# Roles that can mutate every event regardless of ownership.
CALENDAR_OVERRIDE_ROLES: tuple[UserRole, ...] = (
    UserRole.admin,
    UserRole.head_of_recruitment,
)

# Read-only organization oversight. Finance may inspect the complete calendar,
# but is deliberately absent from ``CALENDAR_OVERRIDE_ROLES`` so PATCH/DELETE
# authority is unchanged.
CALENDAR_READ_OVERRIDE_ROLES: tuple[UserRole, ...] = (
    *CALENDAR_OVERRIDE_ROLES,
    UserRole.finance,
)

# ── Audit actions (Activity.action) ──────────────────────────────────────────
CALENDAR_EVENT_UPDATED = "calendar_event_updated"
CALENDAR_EVENT_DELETED = "calendar_event_deleted"


def _attendee_emails(attendees: Any) -> Iterator[str]:
    """Yield attendee emails from either supported ``attendees`` shape."""
    if not isinstance(attendees, list):
        return
    for entry in attendees:
        if isinstance(entry, str):
            yield entry
        elif isinstance(entry, dict):
            addr = entry.get("address") or entry.get("email")
            if isinstance(addr, str):
                yield addr


def _is_attendee(event: CalendarEvent, user: User) -> bool:
    email = (user.email or "").strip().lower()
    if not email:
        return False
    return any(e.strip().lower() == email for e in _attendee_emails(event.attendees))


def user_is_override(user: User) -> bool:
    """True for admin / head_of_recruitment (org-wide calendar access)."""
    return user.has_any_role(*CALENDAR_OVERRIDE_ROLES)


def user_is_read_override(user: User) -> bool:
    """True for roles with organization-wide read access to calendar data."""
    return user.has_any_role(*CALENDAR_READ_OVERRIDE_ROLES)


def user_owns_event(event: CalendarEvent, user: User) -> bool:
    owner = getattr(event, "operational_owner_id", None) or event.created_by
    if event.status == EventStatus.scheduled:
        return owner in operational_owner_ids(user)
    return owner == user.id or event.created_by == user.id


def operational_event_filter(user: User) -> ColumnElement[bool]:
    owner = func.coalesce(CalendarEvent.operational_owner_id, CalendarEvent.created_by)
    return and_(
        CalendarEvent.status == EventStatus.scheduled,
        owner.in_(operational_owner_ids(user)),
    )


def user_can_view_event(event: CalendarEvent, user: User) -> bool:
    """Owner OR participant OR organization-wide read role."""
    return (
        user_is_read_override(user)
        or user_owns_event(event, user)
        or _is_attendee(event, user)
    )


def user_can_mutate_event(event: CalendarEvent, user: User) -> bool:
    """Owner OR admin/HoR only — a bare participant may not mutate."""
    return user_is_override(user) or user_owns_event(event, user)


# ── SQL-level visibility filter (applied BEFORE read, for the LIST route) ──────

# Handles both attendee shapes: a bare JSON string element (``#>> '{}'`` unwraps
# the scalar to text) and a ``{"address": ...}`` object element. The
# ``jsonb_typeof(... ) = 'array'`` guard keeps the set-returning function from
# erroring on a NULL / non-array column value.
_ATTENDEE_MATCH_SQL = (
    "(jsonb_typeof(calendar_events.attendees) = 'array' AND EXISTS ("
    "SELECT 1 FROM jsonb_array_elements(calendar_events.attendees) AS _att_elem "
    "WHERE lower(CASE "
    "WHEN jsonb_typeof(_att_elem) = 'string' THEN _att_elem #>> '{}' "
    "WHEN jsonb_typeof(_att_elem) = 'object' THEN _att_elem ->> 'address' "
    "END) = lower(:cal_scope_email)))"
)


def event_visibility_filter(user: User) -> ColumnElement[bool]:
    """SQLAlchemy boolean condition scoping a ``CalendarEvent`` query to ``user``.

    admin / head_of_recruitment / finance → unrestricted (``TRUE``). Everyone else →
    events they own or are an attendee of.
    """
    if user_is_read_override(user):
        return true()
    return personal_event_visibility_filter(user)


def personal_event_visibility_filter(user: User) -> ColumnElement[bool]:
    """Owner/attendee scope without the organization-wide read override.

    Dashboard sections labelled "Moje" use this even for Admin, HoR and
    Finance.  Their ability to inspect the complete calendar remains unchanged
    on the calendar screen itself.
    """

    attendee_clause = text(_ATTENDEE_MATCH_SQL).bindparams(
        cal_scope_email=(user.email or "")
    )
    return or_(
        CalendarEvent.created_by == user.id,
        attendee_clause,
        operational_event_filter(user),
    )


# ── Participant projection ────────────────────────────────────────────────────


def project_event_fields(event: CalendarEvent, user: User) -> dict[str, Any]:
    """Return the ``attendees`` / ``description`` a viewer is allowed to see.

    Owner / admin / HoR / Finance get the full record. A non-owner participant gets the
    two fields the finding calls out as leaking others' data redacted: other
    attendees' emails (only their own entry is kept) and the free-text
    ``description`` (internal notes). All meeting logistics stay — they are
    attending. Redacting candidate/client references for participants is a
    possible follow-up refinement.
    """
    if user_is_read_override(user) or user_owns_event(event, user):
        return {
            "attendees": event.attendees or [],
            "description": event.description,
        }

    email = (user.email or "").strip().lower()
    own_entries = [
        entry
        for entry in (event.attendees or [])
        if any(e.strip().lower() == email for e in _attendee_emails([entry]))
    ]
    return {"attendees": own_entries, "description": None}


# ── Audit ─────────────────────────────────────────────────────────────────────


def record_calendar_audit(
    db: AsyncSession,
    *,
    action: str,
    user_id: Optional[int],
    event_id: int,
    override: bool,
    details: Optional[dict[str, Any]] = None,
) -> None:
    """Stage an immutable audit event for a calendar mutation (no commit).

    ``override`` records whether the actor reached the event through the
    admin/HoR org-wide override rather than ownership, so cross-user access is
    visible in the trail. ``details`` MUST stay free of PII (no emails, titles,
    descriptions) — ids and reason codes only.
    """
    payload: dict[str, Any] = {"override": bool(override)}
    if details:
        payload.update(details)
    db.add(
        Activity(
            entity_type="calendar_event",
            entity_id=event_id,
            action=action,
            user_id=user_id,
            details=payload,
            external_source="audit",
        )
    )
