"""Zakres podstawowy / opcjonalny MD linii zamówienia (Faza B, ticket CeZ 09.2026).

Semantyka, której bronią te testy:

* ``md_total`` = zakres PODSTAWOWY (kolumna historyczna, bez zmian),
  ``md_optional_total`` = zakres OPCJONALNY (``NULL`` = brak opcji w umowie);
* ``md_remaining = podstawa + opcja − Σ zejść + korekta``;
* zużycie wypełnia NAJPIERW podstawę: ``md_base_used = min(zużycie, podstawa)``,
  ``md_optional_used = max(0, zużycie − podstawa)``;
* zamiana kontraktora przenosi niewykorzystaną opcję tą samą proporcją co
  podstawę, poprzednik zachowuje swoje liczby;
* eksport XLSX ma osobne kolumny zakresu.

Nazwiska, numery i liczby są zmyślone (repo jest publiczne).
"""

from __future__ import annotations

import io
import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.core.scheduling import business_today
from tests.test_multi_consultant_orders import (
    _enable_for,
    _line_payload,
    _seed_client_with_contracts,
)

pytestmark = pytest.mark.asyncio


async def _create_md_group(
    app_client: AsyncClient, headers: dict, client_id: int, lines: list[dict]
) -> dict:
    """Zamówienie MD z budżetem per osoba — jawny typ, bez listy klientów."""
    resp = await app_client.post(
        f"/api/clients/{client_id}/order-groups",
        json={
            "order_number": f"CeZ-{uuid.uuid4().hex[:6]}",
            "start_date": (business_today() - timedelta(days=10)).isoformat(),
            "order_type": "md",
            "md_budget_mode": "per_person",
            "lines": lines,
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _put_consumption(
    app_client: AsyncClient,
    headers: dict,
    client_id: int,
    group_id: int,
    line_id: int,
    month: str,
    md: float,
    **extra,
) -> dict:
    resp = await app_client.put(
        f"/api/clients/{client_id}/order-groups/{group_id}"
        f"/lines/{line_id}/consumptions/{month}",
        json={"md_reported": md, **extra},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _group(
    app_client: AsyncClient, headers: dict, client_id: int, group_id: int
) -> dict:
    resp = await app_client.get(
        f"/api/clients/{client_id}/order-groups", headers=headers
    )
    assert resp.status_code == 200, resp.text
    return next(g for g in resp.json()["groups"] if g["id"] == group_id)


async def test_usage_fills_the_base_scope_before_the_option(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """190 + 170 przy zużyciu 154 → pozostało 206, opcja nietknięta."""
    client_id, contracts, _ = await _seed_client_with_contracts(1)
    _enable_for(monkeypatch, client_id)

    group = await _create_md_group(
        app_client,
        app_auth_headers,
        client_id,
        [_line_payload(contracts[0], input_value=190, optional_md=170)],
    )
    line = group["lines"][0]
    assert line["md_total"] == 190
    assert line["md_optional_total"] == 170
    assert line["md_remaining"] == 360
    assert line["md_used"] == 0
    assert line["md_base_used"] == 0
    assert line["md_optional_used"] == 0
    assert group["md_positions_total"] == 360
    assert group["md_used_total"] == 0
    # 360 MD × 1200 zł — admin widzi wartość umowy.
    assert group["contract_value_pln"] == pytest.approx(360 * 1200)
    assert group["used_value_pln"] == 0

    after = await _put_consumption(
        app_client,
        app_auth_headers,
        client_id,
        group["id"],
        line["id"],
        "2026-07",
        154,
        status="accepted",
    )
    assert after["md_remaining"] == 206
    assert after["md_used"] == 154
    assert after["md_base_used"] == 154
    assert after["md_optional_used"] == 0

    # Kolejny miesiąc przelewa nadwyżkę ponad podstawę do opcji.
    after = await _put_consumption(
        app_client,
        app_auth_headers,
        client_id,
        group["id"],
        line["id"],
        "2026-08",
        46,
        status="protocol",
    )
    assert after["md_used"] == 200
    assert after["md_base_used"] == 190
    assert after["md_optional_used"] == 10
    assert after["md_remaining"] == 160

    body = await _group(app_client, app_auth_headers, client_id, group["id"])
    assert body["md_positions_total"] == 360
    assert body["md_used_total"] == 200
    assert body["used_value_pln"] == pytest.approx(200 * 1200)


async def test_line_without_an_option_keeps_the_old_shape(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    client_id, contracts, _ = await _seed_client_with_contracts(1)
    _enable_for(monkeypatch, client_id)

    group = await _create_md_group(
        app_client, app_auth_headers, client_id, [_line_payload(contracts[0])]
    )
    line = group["lines"][0]
    assert line["md_total"] == 50
    assert line["md_optional_total"] is None
    assert line["md_remaining"] == 50
    assert line["md_base_used"] == 0
    assert line["md_optional_used"] == 0

    after = await _put_consumption(
        app_client, app_auth_headers, client_id, group["id"], line["id"], "2026-07", 60
    )
    # Przekroczenie podstawy bez opcji ląduje w „opcjonalnym" zużyciu —
    # przekroczenie jest faktem, nie znika przez przycięcie do budżetu.
    assert after["md_remaining"] == -10
    assert after["md_base_used"] == 50
    assert after["md_optional_used"] == 10
    assert after["md_optional_total"] is None


async def test_optional_scope_is_refused_on_a_cost_order(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    from app.services import cost_orders as co

    client_id, contracts, _ = await _seed_client_with_contracts(1)
    _enable_for(monkeypatch, client_id)
    monkeypatch.setattr(co, "cost_order_client_ids", lambda: frozenset({client_id}))

    resp = await app_client.post(
        f"/api/clients/{client_id}/order-groups",
        json={
            "order_number": f"K-{uuid.uuid4().hex[:6]}",
            "start_date": (business_today() - timedelta(days=10)).isoformat(),
            "order_type": "cost",
            "is_cost_based": True,
            "budget_amount": 100000,
            "lines": [
                {
                    "contract_id": contracts[0],
                    "rate_cost": 1000,
                    "rate_revenue": 1200,
                    "optional_md": 20,
                    "start_date": (business_today() - timedelta(days=10)).isoformat(),
                }
            ],
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 422, resp.text
    assert "zakresu opcjonalnego" in resp.text


async def test_swap_carries_the_unused_option_at_the_same_ratio(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Po zużyciu 154 z 190+170: podstawa 36 i opcja 170 idą ×1200/950."""
    client_id, contracts, _ = await _seed_client_with_contracts(2)
    _enable_for(monkeypatch, client_id)

    group = await _create_md_group(
        app_client,
        app_auth_headers,
        client_id,
        [_line_payload(contracts[0], input_value=190, optional_md=170)],
    )
    old = group["lines"][0]
    await _put_consumption(
        app_client, app_auth_headers, client_id, group["id"], old["id"], "2026-07", 154
    )

    resp = await app_client.post(
        f"/api/clients/{client_id}/order-groups/{group['id']}/lines/{old['id']}/swap",
        json={
            "contract_id": contracts[1],
            "rate_cost": 800,
            "rate_revenue": 950,
            "swap_date": business_today().isoformat(),
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 201, resp.text
    new = resp.json()
    ratio = 1200 / 950
    assert new["md_total"] == pytest.approx(36 * ratio, rel=1e-6)
    assert new["md_optional_total"] == pytest.approx(170 * ratio, rel=1e-6)
    assert new["md_remaining"] == pytest.approx(206 * ratio, rel=1e-6)
    # Wartość w PLN bez zmian: (podstawa + opcja) × nowa stawka == 206 × 1200.
    assert (new["md_total"] + new["md_optional_total"]) * 950 == pytest.approx(
        206 * 1200, rel=1e-6
    )

    body = await _group(app_client, app_auth_headers, client_id, group["id"])
    predecessor = next(line for line in body["lines"] if line["id"] == old["id"])
    assert predecessor["md_total"] == 190
    assert predecessor["md_optional_total"] == 170
    assert predecessor["replaced_by_order_id"] == new["id"]
    # Zamiana: następca przejął tylko pozostałość, więc pozycja umowy to
    # zużyta część poprzednika + przeliczona pozostałość następcy — w PLN
    # dokładnie wartość sprzed zamiany (154 × 1200 + 206 × 1200).
    assert predecessor["replaced_by_kind"] == "swap"
    assert body["md_positions_total"] == pytest.approx(154 + 206 * ratio, rel=1e-6)
    assert body["md_used_total"] == 154
    assert body["contract_value_pln"] == pytest.approx(360 * 1200, rel=1e-6)
    assert body["used_value_pln"] == pytest.approx(154 * 1200, rel=1e-6)


async def test_patch_optional_scope_recomputes_and_null_clears_it(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    client_id, contracts, _ = await _seed_client_with_contracts(1)
    _enable_for(monkeypatch, client_id)

    group = await _create_md_group(
        app_client, app_auth_headers, client_id, [_line_payload(contracts[0])]
    )
    line = group["lines"][0]
    base = f"/api/clients/{client_id}/order-groups/{group['id']}/lines/{line['id']}"

    resp = await app_client.patch(
        base, json={"optional_md": 100}, headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["md_optional_total"] == 100
    assert resp.json()["md_remaining"] == 150

    # Pominięte pole nie rusza opcji…
    resp = await app_client.patch(
        base, json={"rate_cost": 900}, headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["md_optional_total"] == 100

    # …a jawne null ją czyści.
    resp = await app_client.patch(
        base, json={"optional_md": None}, headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["md_optional_total"] is None
    assert resp.json()["md_remaining"] == 50


async def test_export_has_scope_columns(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    from openpyxl import load_workbook

    client_id, contracts, _ = await _seed_client_with_contracts(1)
    _enable_for(monkeypatch, client_id)
    group = await _create_md_group(
        app_client,
        app_auth_headers,
        client_id,
        [_line_payload(contracts[0], input_value=190, optional_md=170)],
    )
    line = group["lines"][0]
    await _put_consumption(
        app_client, app_auth_headers, client_id, group["id"], line["id"], "2026-07", 154
    )

    response = await app_client.post(
        f"/api/clients/{client_id}/order-groups/export",
        headers=app_auth_headers,
        json={"group_ids": [group["id"]]},
    )
    assert response.status_code == 200, response.text
    sheet = load_workbook(io.BytesIO(response.content)).active
    headers = [cell.value for cell in sheet[1]]
    for header in (
        "Zakres podstawowy (MD)",
        "Zakres opcjonalny (MD)",
        "Wykorzystano (MD)",
    ):
        assert header in headers, headers
    row = [cell.value for cell in sheet[2]]
    values = dict(zip(headers, row))
    assert values["Zakres podstawowy (MD)"] == 190
    assert values["Zakres opcjonalny (MD)"] == 170
    assert values["Wykorzystano (MD)"] == 154


async def test_swap_never_produces_a_negative_base_scope(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Korekta ręczna poniżej opcji: podstawa następcy = 0, opcja = reszta."""
    client_id, contracts, _ = await _seed_client_with_contracts(2)
    _enable_for(monkeypatch, client_id)
    group = await _create_md_group(
        app_client,
        app_auth_headers,
        client_id,
        [_line_payload(contracts[0], input_value=10, optional_md=5)],
    )
    old = group["lines"][0]
    await _put_consumption(
        app_client, app_auth_headers, client_id, group["id"], old["id"], "2026-07", 12
    )
    patched = await app_client.patch(
        f"/api/clients/{client_id}/order-groups/{group['id']}/lines/{old['id']}",
        json={"md_remaining": 1},
        headers=app_auth_headers,
    )
    assert patched.status_code == 200, patched.text
    resp = await app_client.post(
        f"/api/clients/{client_id}/order-groups/{group['id']}/lines/{old['id']}/swap",
        json={
            "contract_id": contracts[1],
            "rate_cost": 800,
            "rate_revenue": 1200,
            "swap_date": business_today().isoformat(),
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 201, resp.text
    new = resp.json()
    assert new["md_total"] >= 0
    assert new["md_optional_total"] >= 0
    assert new["md_total"] + new["md_optional_total"] == pytest.approx(1, rel=1e-6)


async def test_cancelled_line_does_not_count_as_a_position(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    client_id, contracts, _ = await _seed_client_with_contracts(2)
    _enable_for(monkeypatch, client_id)
    group = await _create_md_group(
        app_client,
        app_auth_headers,
        client_id,
        [
            _line_payload(contracts[0], input_value=100),
            _line_payload(contracts[1], input_value=40),
        ],
    )
    second = group["lines"][1]
    resp = await app_client.delete(
        f"/api/clients/{client_id}/orders/{second['id']}", headers=app_auth_headers
    )
    assert resp.status_code in (200, 204), resp.text
    body = await _group(app_client, app_auth_headers, client_id, group["id"])
    assert body["md_positions_total"] == 100


async def test_budget_mode_switch_with_optional_scope_keeps_the_check_happy(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Szkic per osoba z opcją → wspólna pula: opcja schodzi razem z podstawą."""
    client_id, contracts, _ = await _seed_client_with_contracts(1)
    _enable_for(monkeypatch, client_id)
    resp = await app_client.post(
        f"/api/clients/{client_id}/order-groups",
        json={
            "order_number": f"DRAFT-{uuid.uuid4().hex[:4]}",
            "start_date": business_today().isoformat(),
            "status": "draft",
            "order_type": "md",
            "md_budget_mode": "per_person",
            "lines": [_line_payload(contracts[0], input_value=10, optional_md=5)],
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 201, resp.text
    group_id = resp.json()["id"]
    switched = await app_client.patch(
        f"/api/clients/{client_id}/order-groups/{group_id}",
        json={"md_budget_mode": "shared", "md_budget_total": 50},
        headers=app_auth_headers,
    )
    assert switched.status_code == 200, switched.text
    line = switched.json()["lines"][0]
    assert line["md_total"] is None and line["md_optional_total"] is None


def test_offboarding_reducer_drops_the_option_first():
    """Zwolniona pula schodzi najpierw z opcji, potem z podstawy."""
    from app.api.client_order_groups import _reduce_legacy_md_budget
    from app.models.client_order import ClientOrder

    order = ClientOrder(
        md_total=Decimal("100"),
        md_optional_total=Decimal("50"),
        md_remaining=Decimal("130"),
        md_manual_adjustment=Decimal("0"),
        md_rate_revenue=Decimal("600"),
        md_input_mode="md",
        md_input_value=Decimal("100"),
    )
    _reduce_legacy_md_budget(order, Decimal("130"))
    assert order.md_optional_total == Decimal("0")
    assert order.md_total == Decimal("20")
    assert order.md_manual_adjustment == Decimal("0")
