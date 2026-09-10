"""Polityka typów zamówień po zniesieniu blokady per klient (09.2026).

Ticket „jedno okno Nowe zamówienie": wszystkie trzy typy (okresowe, kosztowe,
MD) są dostępne dla KAŻDEGO klienta; formularz jedynie podpowiada najczęstszy
typ. Historyczna mapa czterech klientów rozliczanych w MD (BNP, BIK,
Polkomtel, Wedel) zostaje wyłącznie jako interpretacja legacy ``NULL``.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, timezone

import pytest

from app.core.config import settings
from app.models.order_type import OrderType
from app.models.client import ClientStatus
from app.schemas.client import ClientSafeResponse
from app.services.cyfrowy_polsat_orders import CYFROWY_POLSAT_CLIENT_ID
from app.services.order_types import (
    allowed_order_types,
    assert_order_type_allowed,
    effective_standalone_order_type,
    legacy_null_order_type,
    most_common_order_type,
    should_process_active_standalone_order,
    suggested_order_type,
)

_ALL = (OrderType.periodic, OrderType.cost, OrderType.md)
_FORMER_PINNED = {
    12: OrderType.md,
    18: OrderType.md,
    15: OrderType.md,
    155: OrderType.md,
}


@pytest.mark.parametrize(
    "client_id", [12, 15, 18, 155, CYFROWY_POLSAT_CLIENT_ID, 999_999]
)
def test_every_client_can_create_every_order_type(monkeypatch, client_id):
    """BIK i BNP nie są już zablokowane na samym MD — każdy typ dla każdego."""

    monkeypatch.setattr(
        "app.services.order_types._LEGACY_NULL_ORDER_TYPES", _FORMER_PINNED
    )
    monkeypatch.setattr(settings, "MULTI_CONSULTANT_ORDER_CLIENT_IDS", "")
    monkeypatch.setattr(settings, "COST_ORDER_CLIENT_IDS", "")

    assert allowed_order_types(client_id) == _ALL
    for order_type in _ALL:
        assert_order_type_allowed(client_id, order_type)
        assert (
            should_process_active_standalone_order(
                client_id, order_type, was_active=False
            )
            is True
        )


def test_serialized_client_flags_offer_every_type(monkeypatch):
    """Profil klienta nie może już podawać frontowi zawężonej listy typów."""

    monkeypatch.setattr(
        "app.services.order_types._LEGACY_NULL_ORDER_TYPES", _FORMER_PINNED
    )
    monkeypatch.setattr(settings, "MULTI_CONSULTANT_ORDER_CLIENT_IDS", "")
    monkeypatch.setattr(settings, "COST_ORDER_CLIENT_IDS", "")
    now = datetime.now(timezone.utc)

    def wire(client_id: int) -> dict:
        return ClientSafeResponse(
            id=client_id,
            name=f"Client {client_id}",
            industry=None,
            website=None,
            address=None,
            status=ClientStatus.active,
            nda_signed=False,
            contract_type=None,
            created_at=now,
            updated_at=now,
        ).model_dump(mode="json")

    for client_id in (12, 15, 18, 155, 999_999):
        assert wire(client_id)["periodic_orders_enabled"] is True
    # Historyczna interpretacja legacy NULL zostaje per klient.
    assert wire(18)["legacy_null_order_type"] == "md"
    assert wire(12)["legacy_null_order_type"] == "md"
    assert wire(999_999)["legacy_null_order_type"] == "periodic"


def test_legacy_null_standalone_type_keeps_the_historical_reading(monkeypatch):
    """Zdjęcie blokady nie przeklasyfikowuje historycznych kart MD na okresowe."""

    monkeypatch.setattr(
        "app.services.order_types._LEGACY_NULL_ORDER_TYPES", _FORMER_PINNED
    )

    assert legacy_null_order_type(12) == OrderType.md
    assert effective_standalone_order_type(12, None) == OrderType.md
    assert effective_standalone_order_type(15, None) == OrderType.md
    assert effective_standalone_order_type(999_999, None) == OrderType.periodic
    assert effective_standalone_order_type(12, OrderType.cost) == OrderType.cost
    assert legacy_null_order_type(None) == OrderType.periodic


@pytest.mark.asyncio
async def test_latest_suggestion_is_no_longer_filtered_by_a_pinned_list(monkeypatch):
    monkeypatch.setattr(
        "app.services.order_types._LEGACY_NULL_ORDER_TYPES", _FORMER_PINNED
    )
    db = SimpleNamespace(
        scalar=AsyncMock(side_effect=[SimpleNamespace(order_type="periodic"), None])
    )

    assert await suggested_order_type(db, 12) == OrderType.periodic


@pytest.mark.asyncio
async def test_latest_suggestion_without_history_uses_the_historical_type(monkeypatch):
    monkeypatch.setattr(
        "app.services.order_types._LEGACY_NULL_ORDER_TYPES", _FORMER_PINNED
    )
    db = SimpleNamespace(scalar=AsyncMock(side_effect=[None, None]))
    assert await suggested_order_type(db, 18) == OrderType.md

    db = SimpleNamespace(scalar=AsyncMock(side_effect=[None, None]))
    assert await suggested_order_type(db, 999_999) == OrderType.periodic


def _rows(values):
    result = MagicMock()
    result.all.return_value = values
    return result


@pytest.mark.asyncio
async def test_most_common_type_counts_groups_and_standalone_orders(monkeypatch):
    """BIK → MD: przewaga zamówień MD wygrywa z ostatnim okresowym."""

    monkeypatch.setattr(
        "app.services.order_types._LEGACY_NULL_ORDER_TYPES", _FORMER_PINNED
    )
    db = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                # grupy: 4 × MD jawne, 1 × legacy kosztowa
                _rows([("md", False, 4), (None, True, 1)]),
                # samodzielne: 2 × okresowe, 1 × legacy NULL (u BIK = MD)
                _rows([("periodic", 2), (None, 1)]),
            ]
        ),
        scalar=AsyncMock(),
    )

    assert await most_common_order_type(db, 18) == OrderType.md
    db.scalar.assert_not_called()  # brak remisu = bez pytania o ostatni typ


@pytest.mark.asyncio
async def test_most_common_type_breaks_ties_with_the_latest_order(monkeypatch):
    db = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                _rows([("cost", True, 2)]),
                _rows([("periodic", 2)]),
            ]
        ),
        # suggested_order_type: najnowszy samodzielny, najnowsza grupa
        scalar=AsyncMock(
            side_effect=[
                SimpleNamespace(
                    order_type="periodic",
                    created_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
                ),
                SimpleNamespace(
                    order_type="cost",
                    is_cost_based=True,
                    created_at=datetime(2026, 9, 5, tzinfo=timezone.utc),
                ),
            ]
        ),
    )

    assert await most_common_order_type(db, 999_999) == OrderType.cost


@pytest.mark.asyncio
async def test_most_common_type_without_history_uses_the_historical_type(monkeypatch):
    monkeypatch.setattr(
        "app.services.order_types._LEGACY_NULL_ORDER_TYPES", _FORMER_PINNED
    )
    db = SimpleNamespace(
        execute=AsyncMock(side_effect=[_rows([]), _rows([])]), scalar=AsyncMock()
    )
    assert await most_common_order_type(db, 12) == OrderType.md

    db = SimpleNamespace(
        execute=AsyncMock(side_effect=[_rows([]), _rows([])]), scalar=AsyncMock()
    )
    assert await most_common_order_type(db, 999_999) == OrderType.periodic
