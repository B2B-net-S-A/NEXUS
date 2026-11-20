"""FX normalisation + Decimal precision for finance reporting.

Covers two financial-correctness findings (finding 2, ``/api/invoices/dso``,
left with the retired invoice register on 20.11.2026):

1. ``/api/reports/sales`` — MRR / margin / top-clients summed non-PLN contracts
   at face value (no FX). Now every per-currency amount is converted to PLN;
   a currency with no cached rate is excluded and flagged, never counted 1:1.
3. ``reports._monthly`` truncated the fractional per-unit rate with ``int()``
   before multiplying by hours (135.50/h → 135 → ×160 = 21600 instead of
   21680). Now keeps full ``Decimal`` precision.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

from httpx import AsyncClient
from app.core.scheduling import business_today

# asyncio_mode = auto (pytest.ini) runs the async tests without an explicit mark;
# the pure-Decimal unit tests below stay synchronous.


# ── In-memory duck-type for the pure helpers ─────────────────────────────────


class _FakeContract:
    def __init__(
        self,
        *,
        rate_unit,
        billing_hours_per_month: int = 160,
        currency: str = "PLN",
        rate_client=None,
        rate_candidate=None,
        margin=None,
        rate_client_currency: str | None = None,
        rate_candidate_currency: str | None = None,
    ):
        self.rate_unit = rate_unit
        self.billing_hours_per_month = billing_hours_per_month
        self.currency = currency
        self.rate_client = rate_client
        self.rate_candidate = (
            rate_candidate
            if rate_candidate is not None
            else (
                rate_client - margin
                if rate_client is not None and margin is not None
                else None
            )
        )
        self.margin = margin
        self.rate_client_currency = rate_client_currency
        self.rate_candidate_currency = rate_candidate_currency


# ── Finding 3: _monthly keeps Decimal precision (no int truncation) ──────────


def test_monthly_hourly_keeps_decimal_precision():
    from app.api.reports import _monthly, _monthly_rate_client
    from app.models.contract import RateUnit

    contract = _FakeContract(rate_unit=RateUnit.hourly, billing_hours_per_month=160)
    result = _monthly(contract, Decimal("135.50"))

    # 135.50 × 160 = 21680 — the pre-fix int() truncation gave 135 × 160 = 21600.
    assert result == Decimal("21680")
    assert isinstance(result, Decimal)
    assert result != Decimal("21600")

    via_client = _FakeContract(
        rate_unit=RateUnit.hourly,
        billing_hours_per_month=160,
        rate_client=Decimal("135.50"),
    )
    assert _monthly_rate_client(via_client) == Decimal("21680")


def test_monthly_daily_and_monthly_units_are_decimal():
    from app.api.reports import _monthly
    from app.models.contract import RateUnit

    daily = _FakeContract(rate_unit=RateUnit.daily)
    assert _monthly(daily, Decimal("100.25")) == Decimal("2105.25")  # ×21 MD

    monthly = _FakeContract(rate_unit=RateUnit.monthly)
    assert _monthly(monthly, Decimal("999.99")) == Decimal("999.99")


# ── Finding 1 (core): _fold_finance_pln converts, never raw-sums ─────────────


def test_fold_finance_pln_converts_each_currency():
    from app.api.reports import _fold_finance_pln
    from app.models.contract import RateUnit

    pln = _FakeContract(
        rate_unit=RateUnit.monthly,
        currency="PLN",
        rate_client=Decimal("1000"),
        margin=Decimal("200"),
    )
    eur = _FakeContract(
        rate_unit=RateUnit.monthly,
        currency="EUR",
        rate_client=Decimal("1000"),
        margin=Decimal("200"),
    )
    rates = {"PLN": Decimal("1"), "EUR": Decimal("4")}
    revenue, margin, missing = _fold_finance_pln([pln, eur], rates)

    # 1000·1 + 1000·4 = 5000, NOT the raw face-value sum 2000.
    assert revenue == Decimal("5000")
    assert margin == Decimal("1000")
    assert missing == set()


def test_fold_finance_pln_excludes_missing_rate():
    from app.api.reports import _fold_finance_pln
    from app.models.contract import RateUnit

    pln = _FakeContract(
        rate_unit=RateUnit.monthly, currency="PLN", rate_client=Decimal("1000")
    )
    eur = _FakeContract(
        rate_unit=RateUnit.monthly, currency="EUR", rate_client=Decimal("1000")
    )
    rates = {"PLN": Decimal("1"), "EUR": None}  # no cached EUR rate
    revenue, _margin, missing = _fold_finance_pln([pln, eur], rates)

    assert revenue == Decimal("1000")  # EUR excluded, not added at 1:1
    assert missing == {"EUR"}


def test_fold_finance_pln_converts_revenue_and_cost_independently():
    from app.api.reports import _fold_finance_pln
    from app.models.contract import RateUnit

    contract = _FakeContract(
        rate_unit=RateUnit.monthly,
        rate_client=Decimal("1000"),
        rate_candidate=Decimal("2500"),
        rate_client_currency="EUR",
        rate_candidate_currency="PLN",
    )
    rates = {"PLN": Decimal("1"), "EUR": Decimal("4")}

    revenue, margin, missing = _fold_finance_pln([contract], rates)

    assert revenue == Decimal("4000")
    assert margin == Decimal("1500")
    assert missing == set()


# ── Seeding helpers (real Postgres) ──────────────────────────────────────────


async def _seed_client_and_candidate(
    suffix: str, *, display_name: str | None = None
) -> tuple[int, int]:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client

    async with AsyncSessionLocal() as db:
        c = Client(name=f"FXClient-{suffix}", display_name=display_name)
        db.add(c)
        cand = Candidate(
            email=f"fx-{suffix}@example.com",
            name=f"FX Test {suffix}",
            lastname="Candidate",
        )
        db.add(cand)
        await db.commit()
        await db.refresh(c)
        await db.refresh(cand)
        return c.id, cand.id


async def _seed_contract(
    client_id: int,
    candidate_id: int,
    *,
    currency: str,
    rate_client: int,
    rate_candidate: int = 0,
    rate_unit: str = "monthly",
) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.contract import Contract, ContractStatus

    today = business_today()
    async with AsyncSessionLocal() as db:
        c = Contract(
            client_id=client_id,
            candidate_id=candidate_id,
            status=ContractStatus.active,
            start_date=today - timedelta(days=30),
            end_date=None,
            rate_client=rate_client,
            rate_candidate=rate_candidate,
            rate_unit=rate_unit,
            billing_hours_per_month=160,
            currency=currency,
        )
        db.add(c)
        await db.commit()
        await db.refresh(c)
        return c.id


async def _seed_rate(currency: str, rate: str, on: date | None = None) -> Decimal:
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.fx_rate import FxRate

    on = on or business_today()
    async with AsyncSessionLocal() as db:
        existing = await db.scalar(
            select(FxRate).where(
                FxRate.currency == currency, FxRate.effective_date == on
            )
        )
        if existing is None:
            db.add(
                FxRate(
                    effective_date=on,
                    currency=currency,
                    rate_to_pln=Decimal(rate),
                    source="test",
                )
            )
            await db.commit()
    # Return the rate that rates_to_pln will actually resolve (tolerant of any
    # pre-existing row for this currency/date from another test).
    async with AsyncSessionLocal() as db:
        from app.services.fx_service import rates_to_pln

        resolved = (await rates_to_pln(db, {currency}, on)).get(currency)
    assert resolved is not None
    return resolved


async def _clear_reports_cache() -> None:
    from app.core.cache import cache_invalidate

    await cache_invalidate("reports:")


# ── Finding 1 (integration): /reports/sales converts a foreign contract ──────


async def test_sales_total_revenue_is_fx_converted(
    app_client: AsyncClient, app_auth_headers: dict
):
    suffix = uuid.uuid4().hex[:6]
    client_id, cand_id = await _seed_client_and_candidate(suffix)

    # Seed the rate FIRST, then take the baseline — so any pre-existing AUD
    # contracts are already counted and the only delta is the contract we add.
    rate = await _seed_rate("AUD", "4")

    await _clear_reports_cache()
    baseline = (
        await app_client.get("/api/reports/sales", headers=app_auth_headers)
    ).json()["total_revenue"]

    await _seed_contract(client_id, cand_id, currency="AUD", rate_client=1000)

    await _clear_reports_cache()
    after_resp = await app_client.get("/api/reports/sales", headers=app_auth_headers)
    assert after_resp.status_code == 200
    after = after_resp.json()["total_revenue"]

    delta = float(after) - float(baseline)
    expected = 1000 * float(rate)  # monthly unit → contribution = rate_client × FX
    assert abs(delta - expected) < 1.0, (
        f"expected FX-converted delta ≈ {expected}, got {delta}"
    )
    # The pre-fix bug added the AUD contract at face value (1000), not converted.
    assert abs(delta - 1000) > 1.0


async def test_sales_flags_missing_fx_rate(
    app_client: AsyncClient, app_auth_headers: dict
):
    suffix = uuid.uuid4().hex[:6]
    client_id, cand_id = await _seed_client_and_candidate(suffix)
    # ZZZ has no NBP rate anywhere — must be flagged, not 500 and not counted 1:1.
    await _seed_contract(client_id, cand_id, currency="ZZZ", rate_client=1000)

    await _clear_reports_cache()
    resp = await app_client.get("/api/reports/sales", headers=app_auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["finance_quality"] == "unavailable"
    assert any("ZZZ" in w for w in body["finance_warnings"])
