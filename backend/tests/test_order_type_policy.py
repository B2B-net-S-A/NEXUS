from types import SimpleNamespace
from unittest.mock import AsyncMock
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
    suggested_order_type,
)


def test_ticket_clients_have_pinned_allowed_types(monkeypatch):
    # Polityka nie może zależeć od chwilowego braku zmiennej Coolify — te
    # cztery rekordy są kanonicznym, zamkniętym zakresem korekty.
    monkeypatch.setattr(settings, "MULTI_CONSULTANT_ORDER_CLIENT_IDS", "")
    monkeypatch.setattr(settings, "COST_ORDER_CLIENT_IDS", "")
    monkeypatch.setattr(
        "app.services.order_types._PINNED_ALLOWED_ORDER_TYPES",
        {
            12: (OrderType.md,),
            18: (OrderType.md,),
            15: (OrderType.md, OrderType.cost),
            155: (OrderType.md, OrderType.cost),
        },
    )

    assert allowed_order_types(12) == (OrderType.md,)
    assert allowed_order_types(18) == (OrderType.md,)
    assert allowed_order_types(15) == (OrderType.md, OrderType.cost)
    assert allowed_order_types(155) == (OrderType.md, OrderType.cost)


def test_serialized_client_flags_follow_the_exact_ticket_policy(monkeypatch):
    """The profile wire contract must mirror the same per-client write policy."""

    monkeypatch.setattr(settings, "MULTI_CONSULTANT_ORDER_CLIENT_IDS", "")
    monkeypatch.setattr(settings, "COST_ORDER_CLIENT_IDS", "")
    monkeypatch.setattr(
        "app.services.order_types._PINNED_ALLOWED_ORDER_TYPES",
        {
            12: (OrderType.md,),
            18: (OrderType.md,),
            15: (OrderType.md, OrderType.cost),
            155: (OrderType.md, OrderType.cost),
        },
    )

    now = datetime.now(timezone.utc)

    def flags(client_id: int) -> tuple[bool, bool]:
        wire = ClientSafeResponse(
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
        return wire["periodic_orders_enabled"], wire["cost_orders_enabled"]

    assert flags(12) == (False, False)  # BNP: MD only
    assert flags(18) == (False, False)  # BIK: MD only
    assert flags(15) == (False, True)  # Polkomtel: MD + cost
    assert flags(155) == (False, True)  # Wedel: MD + cost
    assert flags(999_999) == (True, False)  # ordinary client unchanged

    # A stale broad Coolify capability may not override the pinned write
    # policy. BNP/BIK stay MD-only while Polkomtel/Wedel stay MD + cost.
    monkeypatch.setattr(settings, "COST_ORDER_CLIENT_IDS", "12,15,18,155,999999")
    assert flags(12) == (False, False)
    assert flags(18) == (False, False)
    assert flags(15) == (False, True)
    assert flags(155) == (False, True)
    assert flags(999_999) == (True, True)


def test_cyfrowy_polsat_and_ordinary_client_keep_all_existing_choices(monkeypatch):
    monkeypatch.setattr(settings, "MULTI_CONSULTANT_ORDER_CLIENT_IDS", "")
    monkeypatch.setattr(settings, "COST_ORDER_CLIENT_IDS", "")

    assert allowed_order_types(CYFROWY_POLSAT_CLIENT_ID) == (
        OrderType.periodic,
        OrderType.cost,
        OrderType.md,
    )
    assert allowed_order_types(999_999) == (
        OrderType.periodic,
        OrderType.cost,
        OrderType.md,
    )


def test_periodic_write_is_rejected_for_ticket_clients(monkeypatch):
    monkeypatch.setattr(
        "app.services.order_types._PINNED_ALLOWED_ORDER_TYPES",
        {12: (OrderType.md,)},
    )
    with pytest.raises(ValueError, match="periodic"):
        assert_order_type_allowed(12, OrderType.periodic)
    assert_order_type_allowed(12, OrderType.md)


def test_legacy_null_standalone_type_uses_client_policy(monkeypatch):
    monkeypatch.setattr(
        "app.services.order_types._PINNED_ALLOWED_ORDER_TYPES",
        {
            12: (OrderType.md,),
            15: (OrderType.md, OrderType.cost),
        },
    )

    assert effective_standalone_order_type(12, None) == OrderType.md
    assert effective_standalone_order_type(15, None) == OrderType.md
    assert effective_standalone_order_type(999_999, None) == OrderType.periodic
    assert effective_standalone_order_type(12, OrderType.cost) == OrderType.cost


@pytest.mark.asyncio
async def test_suggestion_cannot_resurrect_historical_periodic_for_bnp(monkeypatch):
    monkeypatch.setattr(
        "app.services.order_types._PINNED_ALLOWED_ORDER_TYPES",
        {12: (OrderType.md,)},
    )
    db = SimpleNamespace(
        scalar=AsyncMock(side_effect=[SimpleNamespace(order_type="periodic"), None])
    )

    assert await suggested_order_type(db, 12) == OrderType.md
