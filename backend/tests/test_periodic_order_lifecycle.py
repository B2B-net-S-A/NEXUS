"""Standalone periodic orders must not retain a stale completed status."""

from datetime import date, datetime, timezone

import pytest
import time_machine

from app.models.client_order import ClientOrder, ClientOrderStatus
from app.services.periodic_order_lifecycle import refresh_periodic_order_status

TODAY = date(2026, 9, 21)


def order(**kwargs):
    return ClientOrder(
        client_id=11,
        order_type="periodic",
        start_date=date(2026, 9, 15),
        end_date=date(2026, 12, 31),
        **kwargs,
    )


@pytest.mark.parametrize(
    "end, expected",
    [
        (date(2026, 9, 20), "completed"),
        (TODAY, "active"),
        (date(2026, 12, 31), "active"),
        (None, "active"),
    ],
)
def test_completed_order_reconciles_inclusive_end(end, expected):
    item = order(status=ClientOrderStatus.completed)
    item.end_date = end
    item.filled_at = datetime(2026, 6, 15, tzinfo=timezone.utc)
    original_filled = item.filled_at
    refresh_periodic_order_status(item, today=TODAY)
    assert item.status == expected
    assert item.filled_at == original_filled
    assert not refresh_periodic_order_status(item, today=TODAY)


@pytest.mark.parametrize("start", [TODAY, date(2026, 10, 1)])
def test_today_and_future_start_keep_existing_active_representation(start):
    item = order(status=ClientOrderStatus.completed)
    item.start_date = start
    assert refresh_periodic_order_status(item, today=TODAY)
    assert item.status == ClientOrderStatus.active


def test_missing_start_cannot_revive_completed_order():
    item = order(status=ClientOrderStatus.completed)
    item.start_date = None
    assert not refresh_periodic_order_status(item, today=TODAY)


@pytest.mark.parametrize("status", ["draft", "paused", "cancelled"])
def test_operator_status_is_preserved(status):
    item = order(status=ClientOrderStatus(status))
    assert not refresh_periodic_order_status(item, today=TODAY)
    assert item.status == status


@pytest.mark.parametrize(
    "kind, group_id", [("md", None), ("cost", None), ("periodic", 42)]
)
def test_budget_and_group_lifecycles_are_not_changed(kind, group_id):
    item = order(status=ClientOrderStatus.completed)
    item.order_type, item.order_group_id = kind, group_id
    assert not refresh_periodic_order_status(item, today=TODAY)
    assert item.status == "completed"


def test_active_past_period_becomes_completed():
    item = order(status=ClientOrderStatus.active)
    item.end_date = date(2026, 9, 20)
    assert refresh_periodic_order_status(item, today=TODAY)
    assert item.status == "completed"


def test_warsaw_midnight_uses_business_date_not_utc():
    item = order(status=ClientOrderStatus.active)
    item.end_date = date(2026, 9, 20)
    with time_machine.travel(
        datetime(2026, 9, 20, 22, 30, tzinfo=timezone.utc), tick=False
    ):
        assert refresh_periodic_order_status(item)
    assert item.status == "completed"
