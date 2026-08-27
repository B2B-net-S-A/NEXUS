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


async def _free_test_currency(on: date | None = None) -> str:
    """Return a currently unused X-prefixed code in the shared test DB."""

    effective_date = on or date.today()
    async with AsyncSessionLocal() as db:
        used = set(
            (
                await db.scalars(
                    select(FxRate.currency).where(
                        FxRate.effective_date == effective_date
                    )
                )
            ).all()
        )
    return next(
        f"X{first}{second}"
        for first in "0123456789ABCDEF"
        for second in "0123456789ABCDEF"
        if f"X{first}{second}" not in used
    )


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


async def _seed_split_currency_contract(
    *, currency: str, rate_to_pln: str = "4.1234"
) -> tuple[int, int]:
    """One contract whose revenue and candidate cost use different currencies."""
    await _seed_rate(currency, rate_to_pln, date.today())
    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Split FX Client {unique}")
        db.add(client)
        await db.flush()
        cand = Candidate(name="SplitFx", lastname=f"Contractor-{unique}")
        db.add(cand)
        await db.flush()
        db.add(
            Contract(
                candidate_id=cand.id,
                client_id=client.id,
                status=ContractStatus.active,
                start_date=date(2025, 1, 1),
                end_date=None,
                rate_client=Decimal("5000"),
                rate_candidate=Decimal("3000"),
                rate_client_currency=currency,
                rate_candidate_currency="PLN",
                # Legacy alias follows the client currency, but finance must use
                # both explicit legs rather than this lossy compatibility field.
                currency=currency,
            )
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


async def test_margin_endpoints_convert_revenue_and_cost_independently(
    app_client: AsyncClient, app_auth_headers: dict
):
    fake_currency = await _free_test_currency()
    candidate_id, client_id = await _seed_split_currency_contract(
        currency=fake_currency
    )

    contractor_response = await app_client.get(
        "/api/contract-analytics/margin-by-contractor?limit=100",
        headers=app_auth_headers,
    )
    client_response = await app_client.get(
        "/api/contract-analytics/margin-by-client?limit=100",
        headers=app_auth_headers,
    )

    assert contractor_response.status_code == 200, contractor_response.text
    assert client_response.status_code == 200, client_response.text
    contractor_row = _find(contractor_response.json(), "candidate_id", candidate_id)
    client_row = _find(client_response.json(), "client_id", client_id)
    expected_revenue = 5000 * 4.1234
    expected_margin = expected_revenue - 3000
    for row in (contractor_row, client_row):
        assert row["total_monthly_revenue"] == pytest.approx(expected_revenue, abs=0.05)
        assert row["total_monthly_margin"] == pytest.approx(expected_margin, abs=0.05)
        assert row["fx_missing"] is False


async def test_revenue_forecast_converts_split_currency_margin_per_leg(
    app_client: AsyncClient, app_auth_headers: dict
):
    async def _forecast() -> dict:
        response = await app_client.get(
            "/api/contract-analytics/revenue-forecast?horizon_months=1",
            headers=app_auth_headers,
        )
        assert response.status_code == 200, response.text
        return response.json()["months"][0]

    before = await _forecast()
    fake_currency = await _free_test_currency()
    await _seed_split_currency_contract(currency=fake_currency)
    after = await _forecast()

    expected_revenue = 5000 * 4.1234
    expected_margin = expected_revenue - 3000
    assert after["revenue"] - before["revenue"] == pytest.approx(
        expected_revenue, abs=0.05
    )
    assert after["margin"] - before["margin"] == pytest.approx(
        expected_margin, abs=0.05
    )
    assert after["active_count"] == before["active_count"] + 1


async def test_margin_missing_fx_rate_is_flagged_not_fatal(
    app_client: AsyncClient, app_auth_headers: dict
):
    """A currency without a cached rate is flagged and never treated as PLN."""
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
    # Missing FX excludes both legs. It must not preserve the foreign nominal
    # amount and label it as PLN.
    assert row["total_monthly_revenue"] == 0
    assert row["total_monthly_margin"] == 0


async def test_zero_foreign_revenue_leg_does_not_require_fx(
    app_client: AsyncClient, app_auth_headers: dict
):
    forecast_before_response = await app_client.get(
        "/api/contract-analytics/revenue-forecast?horizon_months=1",
        headers=app_auth_headers,
    )
    assert forecast_before_response.status_code == 200, forecast_before_response.text
    forecast_before = forecast_before_response.json()["months"][0]

    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Zero FX Client {unique}")
        candidate = Candidate(name="ZeroFx", lastname=f"Contractor-{unique}")
        db.add_all([client, candidate])
        await db.flush()
        db.add(
            Contract(
                candidate_id=candidate.id,
                client_id=client.id,
                status=ContractStatus.active,
                start_date=date(2025, 1, 1),
                rate_client=Decimal("0"),
                rate_candidate=Decimal("100"),
                currency="XXZ",
                rate_client_currency="XXZ",
                rate_candidate_currency="PLN",
            )
        )
        await db.commit()
        candidate_id = candidate.id
        client_id = client.id

    contractor_response = await app_client.get(
        "/api/contract-analytics/margin-by-contractor?limit=100",
        headers=app_auth_headers,
    )
    client_response = await app_client.get(
        "/api/contract-analytics/margin-by-client?limit=100",
        headers=app_auth_headers,
    )
    forecast_after_response = await app_client.get(
        "/api/contract-analytics/revenue-forecast?horizon_months=1",
        headers=app_auth_headers,
    )

    assert contractor_response.status_code == 200, contractor_response.text
    assert client_response.status_code == 200, client_response.text
    assert forecast_after_response.status_code == 200, forecast_after_response.text
    for row in (
        _find(contractor_response.json(), "candidate_id", candidate_id),
        _find(client_response.json(), "client_id", client_id),
    ):
        assert row["total_monthly_revenue"] == 0
        assert row["total_monthly_margin"] == -100
        assert row["fx_missing"] is False

    forecast_after_body = forecast_after_response.json()
    forecast_after = forecast_after_body["months"][0]
    assert forecast_after["revenue"] - forecast_before["revenue"] == 0
    assert forecast_after["margin"] - forecast_before["margin"] == -100
    assert forecast_after["active_count"] == forecast_before["active_count"] + 1
    assert not any("XXZ" in warning for warning in forecast_after_body["fx_warnings"])


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
    # NB: directionality is intentionally NOT asserted. A currency with no cached
    # NBP rate is counted 1:1 under convert_currency=false but EXCLUDED under
    # convert_currency=true (P1-FX-01), so the nominal total can exceed the
    # converted one. The magnitude difference is what proves conversion is on.
    assert abs(d_month["revenue"] - n_month["revenue"]) > 1.0


async def test_revenue_forecast_missing_fx_excluded_not_counted_1to1(
    app_client: AsyncClient, app_auth_headers: dict
):
    """A non-PLN contract with no cached rate is EXCLUDED, not folded in 1:1 (P1-FX-01).

    Pollution-proof: run the forecast twice — once with no rate for a per-run
    unique fake currency, once after seeding it @7.0 — and prove the delta equals
    the FULL converted amount (7.0×monthly). That is only possible if the no-rate
    run EXCLUDED the contract entirely. The old 1:1-coercion bug would instead
    leave a delta of only (7.0 − 1.0)×monthly (the foreign amount already counted
    at parity). A per-run currency code guarantees no leftover fx_rates row can
    mask the missing-rate case.
    """
    unique = uuid.uuid4().hex[:8]
    # A per-run fake ISO-ish code (X-space = "no currency"), 3 chars, that no
    # other test seeds a rate for — so the "no cached rate" precondition holds.
    fake_cur = await _free_test_currency()
    monthly = 10000  # default rate_unit → monthly == rate_client
    async with AsyncSessionLocal() as db:
        client = Client(name=f"NoRate Client {unique}")
        db.add(client)
        await db.flush()
        cand = Candidate(name="NoRate", lastname=f"Contractor-{unique}")
        db.add(cand)
        await db.flush()
        db.add(
            Contract(
                candidate_id=cand.id,
                client_id=client.id,
                status=ContractStatus.active,
                start_date=date(2025, 1, 1),
                end_date=None,
                rate_client=Decimal(str(monthly)),
                rate_candidate=Decimal("6000"),
                currency=fake_cur,  # per-run code — no rate ever seeded for it
            )
        )
        await db.commit()

    async def _forecast() -> dict:
        resp = await app_client.get(
            "/api/contract-analytics/revenue-forecast?horizon_months=1",
            headers=app_auth_headers,
        )
        assert resp.status_code == 200, resp.text
        return resp.json()

    no_rate = await _forecast()
    # Flagged, and the missing currency is named in the warnings.
    assert no_rate["fx_missing"] is True
    assert any(
        "Brak kursu NBP" in w and fake_cur in w for w in no_rate["fx_warnings"]
    ), no_rate["fx_warnings"]
    rev_excluded = no_rate["months"][0]["revenue"]

    await _seed_rate(fake_cur, "7.0", date.today())
    with_rate = await _forecast()
    rev_included = with_rate["months"][0]["revenue"]
    # Once the rate exists the currency stops being warned about.
    assert not any(fake_cur in w for w in with_rate["fx_warnings"])

    delta = rev_included - rev_excluded
    # Exclusion → delta is the FULL converted amount.
    assert delta == pytest.approx(monthly * 7.0, abs=0.5), (
        "missing-rate amount must have been excluded, so adding the rate lifts "
        "revenue by the whole converted value"
    )
    # A 1:1 coercion bug would leave a delta of only (7.0 − 1.0)×monthly.
    assert delta != pytest.approx(monthly * 6.0, abs=0.5)
