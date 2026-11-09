"""Ostatni dotyk szansy: jedna definicja dla listy, karty, Podsumowania i automatu.

Dotyk to najpóźniejsza z chwil w przeszłości:

* aktywność szansy albo jej firmy: telefon (odbyty), notatka, mail w obie strony,
  odbyte spotkanie (``occurred_at`` minęło, nie odwołane), zrobione zadanie;
* ``last_activity_at``, poza śladami joba Atlasa (niżej);
* ``created_at`` szansy jako dolna granica, więc dotyk jest zawsze.

Nie są dotykiem: ``updated_at`` (zapisuje go też import), otwarte zadanie,
zaplanowany telefon i przyszłe spotkanie, bo to zamiar, a nie praca.

Ślad joba: Atlas codziennie o 06:20 UTC nadpisywał ``last_activity_at``. Na kopii
produkcji z 08.11.2026 to 431 wierszy z importu z godziną 06:20:00, a pojedyncze
06:20:11 i 06:20:17 to zwykła praca, stąd okno jednej sekundy.

Dwa podzapytania skorelowane zamiast jednego z ``OR``, bo każde idzie po swoim
indeksie (``ix_sales_activities_opportunity``, ``ix_sales_activities_company``).
"""

from __future__ import annotations

from datetime import datetime, time
from typing import Any

from sqlalchemy import (
    DateTime,
    Time,
    and_,
    case,
    cast,
    func,
    null,
    or_,
    select,
)
from sqlalchemy.sql.elements import ColumnElement

from app.models.sales import SalesActivity, SalesOpportunity
from app.services.sales.kpi import CANCELLED_PREFIXES

ATLAS_JOB_SECOND_START = time(6, 20, 0)
ATLAS_JOB_SECOND_END = time(6, 20, 1)


def not_cancelled() -> list[ColumnElement[bool]]:
    """Warunki odsiewające odwołane spotkania (temat z Outlooka)."""

    subject = func.coalesce(SalesActivity.subject, "")
    return [subject.not_ilike(f"{prefix}%") for prefix in CANCELLED_PREFIXES]


def touched_at() -> ColumnElement[Any]:
    """Chwila dotyku aktywności; NULL, gdy aktywność dotykiem nie jest."""

    activity = SalesActivity
    happened_at = func.coalesce(
        activity.occurred_at, activity.done_at, activity.created_at
    )
    return case(
        (activity.kind.in_(("email", "note")), happened_at),
        (
            and_(
                activity.kind == "call",
                # Telefon z terminem bez done_at to pozycja listy zadań, choćby import
                # wpisał mu occurred_at = created_at (_is_open_item w sales_activities).
                or_(
                    activity.done_at.is_not(None),
                    and_(activity.occurred_at.is_not(None), activity.due_at.is_(None)),
                ),
            ),
            happened_at,
        ),
        (and_(activity.kind == "meeting", *not_cancelled()), activity.occurred_at),
        (activity.kind == "task", activity.done_at),
    )


def _latest_touch(scope: ColumnElement[bool], now: datetime) -> Any:
    touched = touched_at()
    return (
        select(func.max(touched))
        .where(scope, touched < now)
        .correlate(SalesOpportunity)
        .scalar_subquery()
    )


def _last_activity_without_job_trace(now: datetime) -> ColumnElement[Any]:
    column = SalesOpportunity.last_activity_at
    clock_utc = cast(func.timezone("UTC", column), Time)
    job_trace = and_(
        SalesOpportunity.external_ref.is_not(None),
        clock_utc >= ATLAS_JOB_SECOND_START,
        clock_utc < ATLAS_JOB_SECOND_END,
    )
    return case((or_(job_trace, column >= now), null()), else_=column)


def last_touch_at(now: datetime) -> ColumnElement[Any]:
    """Kolumna z ostatnim dotykiem; zapytanie musi mieć ``SalesOpportunity`` w FROM."""

    return func.greatest(
        _latest_touch(SalesActivity.opportunity_id == SalesOpportunity.id, now),
        _latest_touch(SalesActivity.company_id == SalesOpportunity.company_id, now),
        _last_activity_without_job_trace(now),
        SalesOpportunity.created_at,
        type_=DateTime(timezone=True),
    )
