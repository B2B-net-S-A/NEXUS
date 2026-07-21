"""M7-P0.11 — margin analytics must convert currencies to PLN before summing.

Regression guard for a financial-correctness bug: `margin_by_contractor`,
`margin_by_client` and `revenue_forecast` used to `SUM()` monthly margin/revenue
grouped only by entity, adding EUR + PLN nominally into one number. These tests
seed two contracts for one contractor in DIFFERENT currencies and assert the
reported total equals the PLN-converted sum, NOT the nominal add.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus
from app.models.fx_rate import FxRate

pytestmark = pytest.mark.asyncio


async def _seed_rate(currency: str, rate: str, on: date) -> None:
    async with AsyncSessionLocal() as db:
        exists = await db.scalar(
            select(FxRate).where(
                FxRate.currency == currency, FxRate.effective_date == on
            )
        )
        if exists is None:
            db.add(
                FxRate(
                    effective_date=on,
                    currency=currency,
                    rate_to_pln=Decimal(rate),
                    source="test",
                )
            )
            await db.commit()


async def _seed_contractor_two_currencies() -> tuple[int, int]:
    """One contractor + client with a PLN and a GBP active contract.

    GBP@today = 4.1234. Returns (candidate_id, client_id). ``margin`` is derived
    by the model (rate_client - rate_candidate), so both rates are set.
    Expected PLN-normalised totals:
      margin  = 80000 + 2000 * 4.1234 = 88246.8
      revenue = 200000 + 5000 * 4.1234 = 220617.0
    Nominal (buggy) sums would be 82000 / 205000.
    """
    await _seed_rate("GBP", "4.1234", date.today())
    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"FX Client {unique}")
        db.add(client)
        await db.flush()
        cand = Candidate(name="Fx", lastname=f"Contractor-{unique}")
        db.add(cand)
        await db.flush()
        db.add_all(
            [
                Contract(
                    candidate_id=cand.id,
                    client_id=client.id,
                    status=ContractStatus.active,
                    start_date=date(2025, 1, 1),
                    end_date=None,
                    rate_client=Decimal("200000"),
                    rate_candidate=Decimal("120000"),  # → margin 80000
                    currency="PLN",
                ),
                Contract(
                    candidate_id=cand.id,
                    client_id=client.id,
                    status=ContractStatus.active,
                    start_date=date(2025, 1, 1),
                    end_date=None,
                    rate_client=Decimal("5000"),
                    rate_candidate=Decimal("3000"),  # → margin 2000
                    currency="GBP",
                ),
            ]
        )
        await db.commit()
        return cand.id, client.id


def _find(rows: list[dict], key: str, value: int) -> dict:
    for row in rows:
        if row.get(key) == value:
            return row
    raise AssertionError(f"row with {key}={value} not found in response")


async def test_margin_by_contractor_converts_currencies_to_pln(
    app_client: AsyncClient, app_auth_headers: dict
):
    cand_id, _ = await _seed_contractor_two_currencies()

    resp = await app_client.get(
        "/api/contract-analytics/margin-by-contractor?limit=100",
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    row = _find(resp.json(), "candidate_id", cand_id)

    margin = row["total_monthly_margin"]
    revenue = row["total_monthly_revenue"]

    # Decimal must serialise as a JSON number, not a string (FE does arithmetic).
    assert isinstance(margin, (int, float)), f"margin serialised as {type(margin)}"
    assert isinstance(revenue, (int, float))

    # PLN-converted totals, NOT the nominal add.
    assert margin == pytest.approx(88246.8, abs=0.05)
    assert revenue == pytest.approx(220617.0, abs=0.05)
    assert margin != pytest.approx(82000, abs=0.5), "nominal cross-currency sum"
    assert revenue != pytest.approx(205000, abs=0.5), "nominal cross-currency sum"

    # Fractional result proves the value wasn't truncated back to int.
    assert margin != int(margin)
    assert row["active_contracts"] == 2
    assert row["fx_missing"] is False


async def test_margin_by_client_converts_currencies_to_pln(
    app_client: AsyncClient, app_auth_headers: dict
):
    _, client_id = await _seed_contractor_two_currencies()

    resp = await app_client.get(
        "/api/contract-analytics/margin-by-client?limit=100",
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    row = _find(resp.json(), "client_id", client_id)

    assert row["total_monthly_margin"] == pytest.approx(88246.8, abs=0.05)
    assert row["total_monthly_revenue"] == pytest.approx(220617.0, abs=0.05)
    assert row["total_monthly_margin"] != pytest.approx(82000, abs=0.5)
    assert row["fx_missing"] is False


async def test_margin_missing_fx_rate_is_flagged_not_fatal(
    app_client: AsyncClient, app_auth_headers: dict
):
    """A currency with no cached rate degrades 1:1 but sets fx_missing (observable)."""
    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"NoFx Client {unique}")
        db.add(client)
        await db.flush()
        cand = Candidate(name="NoFx", lastname=f"Contractor-{unique}")
        db.add(cand)
        await db.flush()
        db.add(
            Contract(
                candidate_id=cand.id,
                client_id=client.id,
                status=ContractStatus.active,
                start_date=date(2025, 1, 1),
                end_date=None,
                rate_client=Decimal("150000"),
                rate_candidate=Decimal("80000"),  # → margin 70000
                currency="ZZZ",  # no rate ever seeded for this code
            )
        )
        await db.commit()
        cand_id = cand.id

    resp = await app_client.get(
        "/api/contract-analytics/margin-by-contractor?limit=100",
        headers=app_auth_headers,
    )
    # Non-fatal: missing rate must not 500 the dashboard.
    assert resp.status_code == 200, resp.text
    row = _find(resp.json(), "candidate_id", cand_id)
    assert row["fx_missing"] is True
    # 1:1 fallback → nominal value preserved.
    assert row["total_monthly_margin"] == pytest.approx(70000, abs=0.05)


async def test_revenue_forecast_converts_by_default(
    app_client: AsyncClient, app_auth_headers: dict
):
    """The DEFAULT response must be currency-correct (convert_currency flipped on).

    Pollution-proof: the forecast aggregates every active contract, so we don't
    assert an absolute total. Instead we prove the default equals the explicit
    convert=true response and DIFFERS from the nominal (convert=false) one — the
    seeded CHF contract (rate 5.0) guarantees a non-zero difference.
    """
    await _seed_rate("CHF", "5.0", date.today())
    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"CHF Client {unique}")
        db.add(client)
        await db.flush()
        cand = Candidate(name="Chf", lastname=f"Contractor-{unique}")
        db.add(cand)
        await db.flush()
        db.add(
            Contract(
                candidate_id=cand.id,
                client_id=client.id,
                status=ContractStatus.active,
                start_date=date(2025, 1, 1),
                end_date=None,
                rate_client=Decimal("10000"),
                rate_candidate=Decimal("6000"),  # → margin 4000
                currency="CHF",
            )
        )
        await db.commit()

    async def _forecast(qs: str) -> dict:
        resp = await app_client.get(
            f"/api/contract-analytics/revenue-forecast?horizon_months=1{qs}",
            headers=app_auth_headers,
        )
        assert resp.status_code == 200, resp.text
        return resp.json()

    default_body = await _forecast("")
    explicit_true = await _forecast("&convert_currency=true")
    nominal = await _forecast("&convert_currency=false")

    assert "fx_missing" in default_body
    d_month = default_body["months"][0]
    n_month = nominal["months"][0]
    assert isinstance(d_month["revenue"], (int, float))

    # Default == explicit convert (the flag's default flipped to convert).
    assert d_month["revenue"] == pytest.approx(
        explicit_true["months"][0]["revenue"], abs=0.01
    )
    # Default != nominal: conversion actually happens by default. CHF 10000 → 50000
    # PLN makes the two totals differ regardless of what else is in the DB.
    assert abs(d_month["revenue"] - n_month["revenue"]) > 1.0
    assert d_month["revenue"] > n_month["revenue"]
