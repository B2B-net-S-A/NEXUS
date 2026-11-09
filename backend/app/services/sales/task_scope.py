"""Co należy do listy „Zadania”: jedna definicja dla trasy i skryptu sprzątania."""

from __future__ import annotations

from sqlalchemy import and_, or_
from sqlalchemy.sql.elements import ColumnElement

from app.models.sales import SalesActivity, SalesOpportunity
from app.services import sales_schema as schema


def task_items() -> ColumnElement[bool]:
    """Zadanie albo telefon z terminem, a nie wpis historii."""

    return or_(
        SalesActivity.kind == "task",
        and_(
            SalesActivity.kind.in_(schema.TASK_KINDS),
            SalesActivity.due_at.is_not(None),
        ),
    )


def live_opportunity() -> ColumnElement[bool]:
    """Szansa nadal trwa; zapytanie musi mieć ``SalesOpportunity`` w FROM."""

    return and_(
        SalesOpportunity.status == "open", SalesOpportunity.archived_at.is_(None)
    )


def not_orphaned() -> ColumnElement[bool]:
    """Bez sierot: pozycji przy szansie wygranej, przegranej albo w archiwum.

    Na kopii produkcji z 08.11.2026 takich pozycji było 134 ze 174, a zadanie przy
    firmie bez szansy ma nadal sens. Zapytanie wymaga złączenia z ``SalesOpportunity``
    typu OUTER, bo inaczej zniknęłyby właśnie te pozycje bez szansy.
    """

    return or_(SalesActivity.opportunity_id.is_(None), live_opportunity())
