"""Runda 10 audytu — pieniądze (MONEY): testy na bazie.

* R10-N9-1 — Finanse → Analityka kontraktów liczy kontrakty bez stawki
  przychodowej zamiast pokazywać „0 zł” jak pełną kwotę.
* R10-N9-2 — ranking klientów liczy zamówienia regułą W1 (jak `/by-dl`
  i Analityka klienta), a klient bez zamówień ma 0, nie „—”.
* R10-N9-4 — brak kursu na niewycenionym kontrakcie nie zeruje „Aktywnego
  MRR” na profilu klienta.

Każdy test filtruje po WŁASNYM kliencie — baza CI jest wspólna.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_order_group import ClientOrderGroup
from app.models.contract import RateUnit
from tests.test_client_audit_2026_09_24 import (
    _candidate,
    _cleanup,
    _client,
    _contract,
)

pytestmark = pytest.mark.asyncio


# ── R10-N9-1 ────────────────────────────────────────────────────────────────


async def test_margin_by_client_counts_contracts_without_revenue_leg() -> None:
    from app.api.contract_analytics import _margin_by_client_rows

    client_id = await _client()
    try:
        await _contract(
            client_id,
            await _candidate(),
            rate_client=None,
            rate_candidate=Decimal("120"),
            rate_unit=RateUnit.hourly,
            billing_hours_per_month=168,
        )
        async with AsyncSessionLocal() as db:
            rows = await _margin_by_client_rows(db)
        row = next(r for r in rows if r.client_id == client_id)

        assert row.active_contracts == 1
        assert row.total_monthly_margin == 0
        assert row.contracts_without_revenue_leg == 1
    finally:
        await _cleanup(client_id)


# ── R10-N9-2 ────────────────────────────────────────────────────────────────


async def test_client_ranking_uses_w1_order_value_rule() -> None:
    from app.services.insights_clients import compute_client_ranking

    client_id = await _client()
    empty_client_id = await _client()
    today = business_today()
    try:
        contract_ids = [
            await _contract(client_id, await _candidate()) for _ in range(2)
        ]
        async with AsyncSessionLocal() as db:
            md = ClientOrderGroup(
                client_id=client_id,
                order_number=f"R10-MD-{client_id}",
                start_date=today - timedelta(days=10),
                status="active",
                order_type="md",
                is_cost_based=False,
                is_md_budget_based=False,
            )
            db.add(md)
            await db.flush()
            for contract_id in contract_ids:
                db.add(
                    ClientOrder(
                        client_id=client_id,
                        contract_id=contract_id,
                        order_group_id=md.id,
                        title="linia MD",
                        status=ClientOrderStatus.active,
                        start_date=today - timedelta(days=10),
                        md_total=Decimal("10"),
                        md_remaining=Decimal("10"),
                        md_input_mode="md",
                        md_input_value=Decimal("10"),
                        md_rate_revenue=Decimal("1000"),
                    )
                )
            # Szkic samodzielnego zamówienia nie wnosi wartości.
            db.add(
                ClientOrder(
                    client_id=client_id,
                    contract_id=contract_ids[0],
                    title="szkic",
                    status=ClientOrderStatus.draft,
                    start_date=today,
                    total_value=Decimal("10000"),
                    currency="PLN",
                )
            )
            await db.commit()

        async with AsyncSessionLocal() as db:
            rows = await compute_client_ranking(db, on=today)
        row = next(r for r in rows if r.client_id == client_id)
        empty = next(r for r in rows if r.client_id == empty_client_id)

        # 2 × 10 MD × 1000 zł; bez szkicu — jak `/by-dl` i Analityka.
        assert row.total_revenue_all_time == Decimal("20000")
        assert row.active_revenue == Decimal("20000")
        # Jedno zamówienie MD, nie dwie osoby na liniach.
        assert row.active_orders_count == 1
        # Zero to liczba, nie brak.
        assert empty.total_revenue_all_time == 0
        assert empty.active_revenue == 0
    finally:
        await _cleanup(client_id)
        await _cleanup(empty_client_id)


# ── R10-N9-4 ────────────────────────────────────────────────────────────────


async def test_missing_fx_on_unpriced_contract_does_not_blank_active_mrr(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    client_id = await _client()
    try:
        # A: PLN, marża (15000 − 12000) = 3000 zł / mc.
        await _contract(client_id, await _candidate())
        # B: stawka klienta w walucie bez kursu NBP, bez stawki kosztowej.
        await _contract(
            client_id,
            await _candidate(),
            rate_client=Decimal("5000"),
            rate_candidate=None,
            rate_client_currency="XTS",
        )

        resp = await app_client.get(
            f"/api/clients/{client_id}/profile", headers=app_auth_headers
        )
        assert resp.status_code == 200, resp.text
        summary = resp.json()["summary"]

        assert summary["active_mrr"] == 3000
        assert summary["active_mrr_unpriced_contracts"] == 1
        assert summary["active_mrr_fx_missing_contracts"] == 0
    finally:
        await _cleanup(client_id)


async def test_missing_fx_on_priced_contract_is_reported_as_fx_not_rates(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    client_id = await _client()
    try:
        await _contract(
            client_id,
            await _candidate(),
            rate_client=Decimal("5000"),
            rate_candidate=Decimal("4000"),
            rate_client_currency="XTS",
        )

        resp = await app_client.get(
            f"/api/clients/{client_id}/profile", headers=app_auth_headers
        )
        assert resp.status_code == 200, resp.text
        summary = resp.json()["summary"]

        assert summary["active_mrr"] is None
        assert summary["active_mrr_unpriced_contracts"] == 0
        assert summary["active_mrr_fx_missing_contracts"] == 1
    finally:
        await _cleanup(client_id)


# ── R10-X1-1 ────────────────────────────────────────────────────────────────


async def test_invoice_amount_with_grosze_round_trips(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    client_id = await _client()
    try:
        contract_id = await _contract(client_id, await _candidate())
        payload = {
            "contract_id": contract_id,
            "direction": "to_client",
            "invoice_number": f"R10/{contract_id}",
            "issue_date": business_today().isoformat(),
            "amount": 12345.67,
            "currency": "PLN",
        }
        created = await app_client.post(
            "/api/invoices", json=payload, headers=app_auth_headers
        )
        assert created.status_code == 201, created.text
        assert created.json()["amount"] == 12345.67

        listed = await app_client.get(
            f"/api/invoices?contract_id={contract_id}", headers=app_auth_headers
        )
        assert [row["amount"] for row in listed.json()] == [12345.67]

        zero = await app_client.post(
            "/api/invoices",
            json={**payload, "invoice_number": f"R10/{contract_id}/0", "amount": 0},
            headers=app_auth_headers,
        )
        assert zero.status_code == 422, zero.text
    finally:
        # Faktury znikają kaskadą z kontraktem (FK ON DELETE CASCADE).
        await _cleanup(client_id)
