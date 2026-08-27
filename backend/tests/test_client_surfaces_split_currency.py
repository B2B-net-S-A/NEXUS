"""Client-facing finance surfaces must convert each contract rate leg to PLN."""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from sqlalchemy import select

pytestmark = pytest.mark.asyncio


async def test_client_profile_and_dashboards_convert_mixed_currency_legs(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
) -> None:
    from app.core.database import AsyncSessionLocal
    from app.core.scheduling import business_today
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.client_order import ClientOrder, ClientOrderStatus
    from app.models.contract import Contract, ContractStatus, RateUnit
    from app.models.fx_rate import FxRate

    today = business_today()
    # Client profile uses the Warsaw business day, while the legacy dashboard
    # aggregates still resolve FX against the process date (UTC in CI/prod).
    # A rate from the earlier boundary is visible to both surfaces around
    # Polish midnight.
    fx_date = date.today()
    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        # Pick a genuinely free three-character code instead of relying on a
        # short random suffix; FxRate has a unique (date, currency) key shared
        # by every test in the CI shard.
        used_currencies = set(
            (
                await db.scalars(
                    select(FxRate.currency).where(FxRate.effective_date == fx_date)
                )
            ).all()
        )
        client_currency = next(
            f"Q{first}{second}"
            for first in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
            for second in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
            if f"Q{first}{second}" not in used_currencies
        )
        client = Client(name=f"Split currency client {suffix}")
        candidate = Candidate(
            name="Split",
            lastname=f"Currency-{suffix}",
            email=f"split-currency-{suffix}@example.com",
        )
        db.add_all([client, candidate])
        await db.flush()
        contract = Contract(
            client_id=client.id,
            candidate_id=candidate.id,
            status=ContractStatus.active,
            start_date=today - timedelta(days=61),
            rate_client=Decimal("1000.000"),
            rate_candidate=Decimal("2500.000"),
            rate_unit=RateUnit.monthly,
            currency=client_currency,
            rate_client_currency=client_currency,
            rate_candidate_currency="PLN",
        )
        db.add_all(
            [
                contract,
                FxRate(
                    effective_date=fx_date,
                    currency=client_currency,
                    rate_to_pln=Decimal("4.000000"),
                    source="TEST",
                ),
            ]
        )
        await db.flush()
        db.add(
            ClientOrder(
                client_id=client.id,
                contract_id=contract.id,
                title="Foreign active order",
                status=ClientOrderStatus.active,
                start_date=today,
                total_value=Decimal("1000.00"),
                currency=client_currency,
            )
        )
        await db.commit()
        client_id = client.id
        contract_id = contract.id

    profile = await app_client.get(
        f"/api/clients/{client_id}/profile", headers=app_auth_headers
    )
    assert profile.status_code == 200, profile.text
    profile_body = profile.json()
    row = next(
        item
        for item in profile_body["active_consultants"]
        if item["contract_id"] == contract_id
    )
    assert row["currency"] == "PLN"
    assert row["monthly_rate_client"] == 4000
    assert row["monthly_rate_candidate"] == 2500
    assert row["monthly_margin"] == 1500
    assert profile_body["summary"]["active_mrr"] == 1500
    assert profile_body["summary"]["ltv"] == 8000

    dashboard = await app_client.get(
        f"/api/my-clients/{client_id}/dashboard", headers=app_auth_headers
    )
    assert dashboard.status_code == 200, dashboard.text
    assert Decimal(str(dashboard.json()["total_revenue_all_time"])) == Decimal("4000")
    assert Decimal(str(dashboard.json()["active_revenue"])) == Decimal("4000")
    assert dashboard.json()["monthly_margin_total"] == 1500
    # Denominator is the PLN value of the foreign order (1000 × 4), not the
    # nominal 1000. Mixing PLN margin with nominal revenue would yield 150%.
    assert dashboard.json()["monthly_margin_pct"] == 37.5

    my_clients = await app_client.get("/api/my-clients", headers=app_auth_headers)
    assert my_clients.status_code == 200, my_clients.text
    my_client_row = next(
        item for item in my_clients.json() if item["client_id"] == client_id
    )
    assert Decimal(str(my_client_row["total_revenue_all_time"])) == Decimal("4000")
    assert Decimal(str(my_client_row["active_revenue"])) == Decimal("4000")

    overview = await app_client.get(
        "/api/admin/clients-overview", headers=app_auth_headers
    )
    assert overview.status_code == 200, overview.text
    overview_row = next(
        item for item in overview.json() if item["client_id"] == client_id
    )
    assert overview_row["monthly_margin_total"] == 1500
    assert Decimal(str(overview_row["total_revenue_all_time"])) == Decimal("4000")
    assert Decimal(str(overview_row["active_revenue"])) == Decimal("4000")


async def test_missing_fx_never_becomes_a_nominal_margin(monkeypatch) -> None:
    from app.api import admin_clients_overview, my_clients, reports
    from app.api.clients import _finance_rates_in_pln
    from app.models.client_order import ClientOrderStatus
    from app.services.fx_service import amount_to_pln_with_rate
    from app.services.order_revenue import fold_order_revenue_rows_pln

    contract = SimpleNamespace(
        client_id=17,
        resolved_rate_client_currency="EUR",
        resolved_rate_candidate_currency="PLN",
        monthly_client=Decimal("1000"),
        monthly_candidate=Decimal("2500"),
    )
    fields = {
        "monthly_rate_client": contract.monthly_client,
        "monthly_rate_candidate": contract.monthly_candidate,
    }

    profile_rates = _finance_rates_in_pln(
        contract,
        fields,
        {"EUR": None, "PLN": Decimal("1")},
    )
    assert profile_rates["monthly_rate_client"] is None
    assert profile_rates["monthly_rate_candidate"] == Decimal("2500")
    assert profile_rates["monthly_margin"] is None
    assert profile_rates["client_missing_fx"] is True

    async def missing_fx(_db, _currencies, _on):
        return {"EUR": None, "PLN": Decimal("1")}

    def effective_fields(row, _on):
        return {
            "monthly_rate_client": row.monthly_client,
            "monthly_rate_candidate": row.monthly_candidate,
        }

    monkeypatch.setattr(my_clients, "rates_to_pln", missing_fx)
    monkeypatch.setattr(my_clients, "effective_rate_fields", effective_fields)
    total, has_margin, complete = await my_clients._monthly_margin_total_pln(
        object(), [contract], date.today()
    )
    assert total == 0
    assert has_margin is False
    assert complete is False

    monkeypatch.setattr(admin_clients_overview, "rates_to_pln", missing_fx)
    monkeypatch.setattr(
        admin_clients_overview, "effective_rate_fields", effective_fields
    )
    totals, incomplete = await admin_clients_overview._margin_lookup_pln(
        object(), [contract], date.today()
    )
    assert totals == {}
    assert incomplete == {17}

    active_rows = [
        SimpleNamespace(
            client_id=17,
            status=ClientOrderStatus.active,
            currency="EUR",
            sum_val=Decimal("1000"),
        ),
        SimpleNamespace(
            client_id=17,
            status=ClientOrderStatus.active,
            currency="PLN",
            sum_val=Decimal("500"),
        ),
    ]
    revenue_lookup, revenue_incomplete = fold_order_revenue_rows_pln(
        active_rows,
        {"EUR": None, "PLN": Decimal("1")},
    )
    assert revenue_lookup[17]["active"] == Decimal("500")
    assert revenue_incomplete == {17}

    zero_revenue_contract = SimpleNamespace(
        client_id=18,
        resolved_rate_client_currency="ZZZ",
        resolved_rate_candidate_currency="PLN",
        rate_client_currency="ZZZ",
        rate_candidate_currency="PLN",
        currency="ZZZ",
        rate_client=Decimal("0"),
        rate_candidate=Decimal("100"),
        rate_unit=SimpleNamespace(value="monthly"),
        billing_hours_per_month=160,
        monthly_client=Decimal("0"),
        monthly_candidate=Decimal("100"),
    )
    assert amount_to_pln_with_rate(Decimal("0"), None) == (
        Decimal("0"),
        True,
    )
    zero_profile = _finance_rates_in_pln(
        zero_revenue_contract,
        effective_fields(zero_revenue_contract, date.today()),
        {"ZZZ": None, "PLN": Decimal("1")},
    )
    assert zero_profile["monthly_rate_client"] == Decimal("0")
    assert zero_profile["monthly_margin"] == Decimal("-100")
    assert zero_profile["client_missing_fx"] is False

    (
        zero_total,
        zero_has_margin,
        zero_complete,
    ) = await my_clients._monthly_margin_total_pln(
        object(), [zero_revenue_contract], date.today()
    )
    assert (zero_total, zero_has_margin, zero_complete) == (
        Decimal("-100"),
        True,
        True,
    )
    zero_admin, zero_admin_incomplete = await admin_clients_overview._margin_lookup_pln(
        object(), [zero_revenue_contract], date.today()
    )
    assert zero_admin == {18: Decimal("-100")}
    assert zero_admin_incomplete == set()
    report_revenue, report_margin, report_missing = reports._fold_finance_pln(
        [zero_revenue_contract], {"ZZZ": None, "PLN": Decimal("1")}
    )
    assert report_revenue == Decimal("0")
    assert report_margin == Decimal("-100")
    assert report_missing == set()

    zero_without_fx = SimpleNamespace(
        client_id=19,
        status=ClientOrderStatus.active,
        currency="ZZZ",
        sum_val=Decimal("0"),
    )
    zero_lookup, zero_incomplete = fold_order_revenue_rows_pln(
        [zero_without_fx], {"ZZZ": None}
    )
    assert zero_lookup[19]["active"] == Decimal("0")
    assert zero_incomplete == set()


async def test_historical_fx_snapshots_are_loaded_in_one_query() -> None:
    from app.services.fx_service import rates_to_pln_by_date

    class Result:
        def all(self):
            return [
                SimpleNamespace(
                    currency="EUR",
                    effective_date=date(2026, 1, 1),
                    rate_to_pln=Decimal("4.10"),
                ),
                SimpleNamespace(
                    currency="EUR",
                    effective_date=date(2026, 2, 1),
                    rate_to_pln=Decimal("4.20"),
                ),
                SimpleNamespace(
                    currency="GBP",
                    effective_date=date(2026, 1, 15),
                    rate_to_pln=Decimal("5.00"),
                ),
            ]

    class FakeDb:
        calls = 0

        async def execute(self, _statement):
            self.calls += 1
            return Result()

    db = FakeDb()
    snapshots = await rates_to_pln_by_date(
        db,  # type: ignore[arg-type]
        {
            date(2026, 1, 10): {"PLN", "EUR", "GBP"},
            date(2026, 2, 10): {"EUR", "GBP"},
        },
    )

    assert db.calls == 1
    assert snapshots[date(2026, 1, 10)] == {
        "PLN": Decimal("1"),
        "EUR": Decimal("4.10"),
        "GBP": None,
    }
    assert snapshots[date(2026, 2, 10)] == {
        "EUR": Decimal("4.20"),
        "GBP": Decimal("5.00"),
    }
