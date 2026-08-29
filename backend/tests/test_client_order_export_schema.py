"""Validation of the backwards-compatible unified export request."""

import pytest
from pydantic import ValidationError

from app.schemas.client_order import ClientOrderExportRequest


def test_export_request_accepts_legacy_ids_or_ordered_mixed_items():
    assert ClientOrderExportRequest(order_ids=[3, 2]).order_ids == [3, 2]
    payload = ClientOrderExportRequest(
        items=[
            {"kind": "group", "id": 1},
            {"kind": "order", "id": 2},
        ]
    )
    assert payload.items is not None
    assert [(item.kind, item.id) for item in payload.items] == [
        ("group", 1),
        ("order", 2),
    ]


def test_export_request_rejects_two_sources_and_duplicate_items():
    with pytest.raises(ValidationError):
        ClientOrderExportRequest(order_ids=[1], items=[{"kind": "order", "id": 1}])
    with pytest.raises(ValidationError):
        ClientOrderExportRequest(
            items=[
                {"kind": "group", "id": 2},
                {"kind": "group", "id": 2},
            ]
        )


def test_export_request_accepts_an_empty_visible_order_set():
    payload = ClientOrderExportRequest(items=[])

    assert payload.items == []
    assert payload.order_ids == []
