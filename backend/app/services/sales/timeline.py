"""Wspólna oś firmy i szansy: jedno zdarzenie to jeden wiersz.

Te same zdarzenia wpadają do bazy kilkoma drogami: spotkanie z Outlooka i z Fireflies,
podsumowanie Fireflies jako notatka, mail z synchronizacji i jego kopia z importu.

Reguły są ostrożne, bo sklejenie dwóch różnych zdarzeń chowa pracę handlowca:

* spotkania tej samej firmy zaczynające się do 15 minut od siebie (ta sama granica co KPI);
* notatka z podsumowaniem Fireflies do 3 godzin po spotkaniu tej firmy;
* wpisy o tej samej treści tego samego dnia (min. 40 znaków, liczą się litery i cyfry;
  ucięta kopia to też ta sama treść, np. notatka z pierwszymi akapitami maila);
* dwa maile dodatkowo tylko o tym samym temacie (bez Re:, Fw:, Odp:), bo wiele zaczyna się
  tym samym nagłówkiem adresatów, a ta sama treść bywa wysłana pod innym tematem.

Otwartego zadania nigdy nie sklejamy, bo zniknąłby przycisk „Zrobione”.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal, Optional
from zoneinfo import ZoneInfo

from app.core.scheduling import DEFAULT_TZ
from app.models.sales import SalesActivity

Scope = Literal["opportunity", "company", "other_opportunity"]

MEETING_WINDOW = timedelta(minutes=15)
SUMMARY_WINDOW = timedelta(hours=3)
#: Początek treści służy tylko do wyboru kandydatów; o sklejeniu decyduje `_same_event`.
BODY_KEY_CHARS = 80
BODY_KEY_MIN_CHARS = 40
FIREFLIES_SUMMARY_MARK = "podsumowanie spotkania (fireflies"
#: Który wpis zostaje wierszem, gdy treść jest ta sama.
KIND_ORDER = {"email": 0, "meeting": 1, "call": 2, "note": 3, "task": 4}
BODY_SEPARATOR = "\n\n"
_NON_ALNUM = re.compile(r"[\W_]+")
_REPLY_PREFIX = re.compile(r"^(\s*(re|fw|fwd|odp|pd|aw)\s*:\s*)+")


@dataclass
class TimelineRow:
    activity: SalesActivity
    members: list[SalesActivity] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.members:
            self.members = [self.activity]

    @property
    def sources(self) -> list[str]:
        return sorted({m.external_source for m in self.members if m.external_source})

    @property
    def web_link(self) -> Optional[str]:
        return next((m.web_link for m in self.members if m.web_link), None)

    @property
    def body(self) -> Optional[str]:
        """Treści członków bez powtórzeń: nic nie znika, nawet gdy wiersz jest jeden."""

        parts: list[str] = []
        for member in self.members:
            body = (member.body or "").strip()
            if body and not any(body in part for part in parts):
                parts.append(body)
        return BODY_SEPARATOR.join(parts) or None

    def scope(self, opportunity_id: int) -> Scope:
        linked = {member.opportunity_id for member in self.members}
        if opportunity_id in linked:
            return "opportunity"
        return "company" if None in linked else "other_opportunity"


def happened_at(activity: SalesActivity) -> datetime:
    return activity.occurred_at or activity.created_at


def _is_open_item(activity: SalesActivity) -> bool:
    return activity.done_at is None and (
        activity.kind == "task"
        or (activity.kind == "call" and activity.due_at is not None)
    )


def _text(activity: SalesActivity) -> str:
    return _NON_ALNUM.sub("", (activity.body or "").casefold())


def _subject(activity: SalesActivity) -> str:
    bare = _REPLY_PREFIX.sub("", (activity.subject or "").casefold())
    return _NON_ALNUM.sub("", bare)


def _body_key(activity: SalesActivity) -> Optional[tuple[object, object, str]]:
    normalized = _text(activity)
    if len(normalized) < BODY_KEY_MIN_CHARS:
        return None
    day = happened_at(activity).astimezone(ZoneInfo(DEFAULT_TZ)).date()
    return activity.company_id, day, normalized[:BODY_KEY_CHARS]


def _same_event(left: SalesActivity, right: SalesActivity) -> bool:
    if left.kind == right.kind == "email" and _subject(left) != _subject(right):
        return False
    left_text, right_text = _text(left), _text(right)
    return left_text.startswith(right_text) or right_text.startswith(left_text)


def _is_fireflies_summary(activity: SalesActivity) -> bool:
    return (
        activity.kind == "note"
        and FIREFLIES_SUMMARY_MARK in (activity.body or "")[:120].casefold()
    )


def _absorb(row: TimelineRow, member: SalesActivity) -> None:
    """Dokłada wpis do wiersza; wierszem zostaje mail, potem telefon, notatka, zadanie."""

    row.members.append(member)
    row.activity = min(row.members, key=lambda item: KIND_ORDER.get(item.kind, 9))


def merge_duplicates(activities: Sequence[SalesActivity]) -> list[TimelineRow]:
    """Wiersze w kolejności wejścia (od najnowszych)."""

    rows: list[TimelineRow] = []
    meetings: list[TimelineRow] = []
    rest: list[SalesActivity] = []
    for activity in activities:
        if activity.kind != "meeting":
            rest.append(activity)
            continue
        at = happened_at(activity)
        same = next(
            (
                row
                for row in meetings
                if row.activity.company_id == activity.company_id
                and abs(happened_at(row.activity) - at) <= MEETING_WINDOW
            ),
            None,
        )
        if same is None:
            row = TimelineRow(activity)
            meetings.append(row)
            rows.append(row)
        else:
            same.members.append(activity)

    by_body: dict[tuple[object, object, str], list[TimelineRow]] = {}
    for activity in rest:
        if _is_open_item(activity):
            rows.append(TimelineRow(activity))
            continue
        if _is_fireflies_summary(activity):
            at = happened_at(activity)
            meeting = next(
                (
                    row
                    for row in meetings
                    if row.activity.company_id == activity.company_id
                    and timedelta(0) <= at - happened_at(row.activity) <= SUMMARY_WINDOW
                ),
                None,
            )
            if meeting is not None:
                meeting.members.append(activity)
                continue
        key = _body_key(activity)
        if key is None:
            rows.append(TimelineRow(activity))
            continue
        candidates = by_body.setdefault(key, [])
        same_body = next(
            (
                row
                for row in candidates
                if all(_same_event(member, activity) for member in row.members)
            ),
            None,
        )
        if same_body is not None:
            _absorb(same_body, activity)
            continue
        row = TimelineRow(activity)
        candidates.append(row)
        rows.append(row)
    rows.sort(
        key=lambda row: (happened_at(row.activity), row.activity.id), reverse=True
    )
    return rows
