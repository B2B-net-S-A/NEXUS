"""Zejścia wspólnej puli MD: edycja per konsultant, usunięcie, przeliczenie puli.

Ticket 10.2026: miesiąc wspólnej puli dało się tylko dopisać. Nie dało się go
poprawić ani usunąć, a usunięcie zamówienia blokowały właśnie te rozliczenia.
Do tego stawki linii MD tracą od 0419 trzecie miejsce po przecinku dopiero
wtedy, gdy wpisano czwarte.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.core.scheduling import business_today
from tests.test_explicit_order_types import _seed_client_with_contracts, _shared_line


async def _active_shared_group(
    app_client, headers, *, total: int = 100
) -> tuple[str, dict]:
    client_id, contracts = await _seed_client_with_contracts()
    url = f"/api/clients/{client_id}/order-groups"
    created = await app_client.post(
        url,
        headers=headers,
        json={
            "order_number": "MD-SHARED-EDIT",
            "start_date": (business_today() - timedelta(days=40)).isoformat(),
            "order_type": "md",
            "md_budget_mode": "shared",
            "md_budget_total": total,
            "status": "active",
            "lines": [_shared_line(contracts[0]), _shared_line(contracts[1])],
        },
    )
    assert created.status_code == 201, created.text
    group = created.json()
    return f"{url}/{group['id']}", group


@pytest.mark.asyncio
async def test_month_is_saved_per_consultant_edited_and_deleted(
    app_client, app_auth_headers
):
    url, group = await _active_shared_group(app_client, app_auth_headers)
    first, second = (line["id"] for line in group["lines"])
    month = business_today().strftime("%Y-%m")

    saved = await app_client.put(
        f"{url}/md-consumptions/{month}",
        headers=app_auth_headers,
        json={
            "lines": [{"order_id": first, "md": 10}, {"order_id": second, "md": 5.5}]
        },
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["md_used"] == 15.5
    assert body["md_remaining"] == 84.5
    [row] = body["months"]
    assert row["md_reported"] == 15.5 and row["source"] == "manual"
    assert row["breakdown_source"] == "manual"
    assert {p["order_id"]: p["md"] for p in row["breakdown"]} == {
        first: 10,
        second: 5.5,
    }
    assert {c["order_id"] for c in body["consultants"]} == {first, second}

    edited = await app_client.put(
        f"{url}/md-consumptions/{month}",
        headers=app_auth_headers,
        json={"lines": [{"order_id": first, "md": 4}, {"order_id": second, "md": 0}]},
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["md_remaining"] == 96

    group_read = await app_client.get(url.rsplit("/", 1)[0], headers=app_auth_headers)
    assert group_read.status_code == 200
    same = next(g for g in group_read.json()["groups"] if g["id"] == group["id"])
    assert same["md_budget_remaining"] == 96

    deleted = await app_client.delete(
        f"{url}/md-consumptions/{month}", headers=app_auth_headers
    )
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["months"] == []
    assert deleted.json()["md_remaining"] == 100

    missing = await app_client.delete(
        f"{url}/md-consumptions/{month}", headers=app_auth_headers
    )
    assert missing.status_code == 404

    history = await app_client.get(f"{url}/events", headers=app_auth_headers)
    descriptions = " | ".join(e["description"] for e in history.json()["events"])
    assert "Zejście wspólnej puli MD" in descriptions
    assert "Usunięto zejście wspólnej puli MD" in descriptions


@pytest.mark.asyncio
async def test_deleting_the_months_unblocks_deleting_the_order(
    app_client, app_auth_headers
):
    url, group = await _active_shared_group(app_client, app_auth_headers)
    month = business_today().strftime("%Y-%m")
    line_id = group["lines"][0]["id"]
    put = await app_client.put(
        f"{url}/md-consumptions/{month}",
        headers=app_auth_headers,
        json={"lines": [{"order_id": line_id, "md": 3}]},
    )
    assert put.status_code == 200, put.text

    blocked = await app_client.delete(url, headers=app_auth_headers)
    assert blocked.status_code == 409
    assert "Zejścia MD" in blocked.json()["detail"]

    await app_client.delete(f"{url}/md-consumptions/{month}", headers=app_auth_headers)
    removed = await app_client.delete(url, headers=app_auth_headers)
    assert removed.status_code == 204, removed.text


@pytest.mark.asyncio
async def test_exhausted_pool_reopens_after_the_month_is_lowered(
    app_client, app_auth_headers
):
    url, group = await _active_shared_group(app_client, app_auth_headers, total=10)
    month = business_today().strftime("%Y-%m")
    line_id = group["lines"][0]["id"]
    over = await app_client.put(
        f"{url}/md-consumptions/{month}",
        headers=app_auth_headers,
        json={"lines": [{"order_id": line_id, "md": 12}]},
    )
    assert over.status_code == 200, over.text
    assert over.json()["md_remaining"] == 0
    lowered = await app_client.put(
        f"{url}/md-consumptions/{month}",
        headers=app_auth_headers,
        json={"lines": [{"order_id": line_id, "md": 6}]},
    )
    assert lowered.status_code == 200
    assert lowered.json()["md_remaining"] == 4


@pytest.mark.asyncio
async def test_foreign_or_duplicate_consultant_is_rejected(
    app_client, app_auth_headers
):
    url, group = await _active_shared_group(app_client, app_auth_headers)
    month = business_today().strftime("%Y-%m")
    line_id = group["lines"][0]["id"]
    duplicate = await app_client.put(
        f"{url}/md-consumptions/{month}",
        headers=app_auth_headers,
        json={
            "lines": [{"order_id": line_id, "md": 1}, {"order_id": line_id, "md": 2}]
        },
    )
    assert duplicate.status_code == 422
    foreign = await app_client.put(
        f"{url}/md-consumptions/{month}",
        headers=app_auth_headers,
        json={"lines": [{"order_id": 999_999_999, "md": 1}]},
    )
    assert foreign.status_code == 422


@pytest.mark.asyncio
async def test_per_person_order_has_no_shared_months(app_client, app_auth_headers):
    from tests.test_explicit_order_types import _md_line

    client_id, contracts = await _seed_client_with_contracts()
    url = f"/api/clients/{client_id}/order-groups"
    created = await app_client.post(
        url,
        headers=app_auth_headers,
        json={
            "order_number": "MD-PER-PERSON",
            "start_date": (business_today() - timedelta(days=5)).isoformat(),
            "order_type": "md",
            "md_budget_mode": "per_person",
            "status": "active",
            "lines": [_md_line(contracts[0], 40)],
        },
    )
    assert created.status_code == 201, created.text
    response = await app_client.get(
        f"{url}/{created.json()['id']}/md-consumptions", headers=app_auth_headers
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_line_rates_keep_three_decimals(app_client, app_auth_headers):
    client_id, contracts = await _seed_client_with_contracts(1)
    line = {
        **_shared_line(contracts[0]),
        "rate_cost": 291.375,
        "rate_revenue": 1100.125,
    }
    created = await app_client.post(
        f"/api/clients/{client_id}/order-groups",
        headers=app_auth_headers,
        json={
            "order_number": "MD-RATE-3",
            "start_date": (business_today() - timedelta(days=5)).isoformat(),
            "order_type": "md",
            "md_budget_mode": "shared",
            "md_budget_total": 50,
            "status": "active",
            "lines": [line],
        },
    )
    assert created.status_code == 201, created.text
    [saved] = created.json()["lines"]
    assert saved["rate_cost"] == 291.375
    assert saved["rate_revenue"] == 1100.125
