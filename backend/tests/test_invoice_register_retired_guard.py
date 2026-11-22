"""Rejestr faktur ``invoices`` wygaszony 20.11.2026 — nie wraca starym merge'em.

Tabelę usunęła migracja 0748 (reguła:
``docs/claude/kontrakty/rejestr-faktur-invoices-wygaszony.md``). ORM nie może
jej znać, bo ``entrypoint.sh`` woła ``create_all`` i założyłby ją z powrotem,
a trasy, scope'y i zdarzenia nie mogą wrócić.
"""

from __future__ import annotations

from app.core.database import Base
from app.main import app
from app.models.service_account import ServiceScope
from app.schemas.dashboard_v2 import FinanceOperationsKpis
from app.services import integration_events
from tests._route_introspection import iter_api_routes

_RETIRED_PREFIXES = ("/api/invoices", "/api/integrations/v1/invoices")


def test_no_route_serves_the_retired_register() -> None:
    paths = [path for path, _ in iter_api_routes(app)]
    assert paths, "introspekcja nie zebrała żadnej trasy"
    assert [path for path in paths if path.startswith(_RETIRED_PREFIXES)] == []


def test_orm_does_not_know_the_table() -> None:
    assert "invoices" not in Base.metadata.tables


def test_scopes_and_events_are_gone() -> None:
    assert {"invoices:read", "invoices:write"}.isdisjoint(
        scope.value for scope in ServiceScope
    )
    assert [
        name for name in integration_events.EVENT_TYPES if name.startswith("invoice.")
    ] == []


def test_finance_dashboard_has_no_register_tiles() -> None:
    assert {"outstanding_pln", "overdue_pln"}.isdisjoint(
        FinanceOperationsKpis.model_fields
    )
