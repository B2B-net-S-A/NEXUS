from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.api.contracts import _inherit_rates_into_unpriced_order_drafts
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.contract import Contract, RateUnit
from app.services.order_rate_snapshots import (
    convert_order_rate,
    inherited_order_rate_fields,
)


def test_hourly_daily_conversion_uses_fixed_eight_hour_day() -> None:
    assert convert_order_rate(
        Decimal("125"), RateUnit.hourly, RateUnit.daily
    ) == Decimal("1000.000")
    assert convert_order_rate(
        Decimal("1000"), RateUnit.daily, RateUnit.hourly
    ) == Decimal("125.000")


def test_conversion_preserves_empty_values_and_supports_contract_monthly_unit() -> None:
    assert convert_order_rate(None, RateUnit.hourly, RateUnit.daily) is None
    assert convert_order_rate(
        Decimal("22000"), RateUnit.monthly, RateUnit.daily
    ) == Decimal("1000.000")
    assert convert_order_rate(
        Decimal("1000"), RateUnit.daily, RateUnit.monthly
    ) == Decimal("22000.000")
    assert convert_order_rate(
        Decimal("16000"), RateUnit.monthly, RateUnit.hourly, 160
    ) == Decimal("100.000")
    assert convert_order_rate(
        Decimal("100"), RateUnit.hourly, RateUnit.monthly, 168
    ) == Decimal("16800.000")


def test_new_order_inherits_both_rates_unit_and_currencies_from_contract() -> None:
    contract = Contract(
        rate_candidate=Decimal("80"),
        rate_client=Decimal("100"),
        rate_unit=RateUnit.hourly,
        billing_hours_per_month=168,
        rate_candidate_currency="eur",
        rate_client_currency="usd",
        currency="PLN",
    )

    fields = inherited_order_rate_fields(contract)

    assert fields == {
        "rate_candidate": Decimal("80"),
        "rate_client": Decimal("100"),
        "rate_unit": RateUnit.hourly,
        "billing_hours_per_month": 168,
        "rate_client_currency": "USD",
        "rate_candidate_currency": "EUR",
        "currency": "USD",
    }


@pytest.mark.asyncio
async def test_unpriced_flow_b_draft_is_initialized_when_contract_gets_rates() -> None:
    contract = Contract(
        id=31,
        rate_candidate=Decimal("80"),
        rate_client=Decimal("100"),
        rate_unit=RateUnit.daily,
        billing_hours_per_month=168,
        rate_candidate_currency="EUR",
        rate_client_currency="USD",
    )
    draft = ClientOrder(
        id=44,
        client_id=7,
        contract_id=contract.id,
        title="PO-44",
        status=ClientOrderStatus.draft,
        rate_candidate=None,
        rate_client=None,
    )
    db = SimpleNamespace(
        scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: [draft]))
    )

    assert await _inherit_rates_into_unpriced_order_drafts(db, contract) == 1
    assert draft.rate_candidate == Decimal("80")
    assert draft.rate_client == Decimal("100")
    assert draft.rate_unit == RateUnit.daily
    assert draft.billing_hours_per_month == 168
    assert draft.rate_client_currency == "USD"
    assert draft.rate_candidate_currency == "EUR"


def test_order_snapshot_migration_and_startup_safety_net_stay_in_sync() -> None:
    backend = Path(__file__).resolve().parents[1]
    migration = (
        backend / "alembic/versions/0249_order_rate_snapshots_offboarding.py"
    ).read_text(encoding="utf-8")
    entrypoint = (backend / "entrypoint.sh").read_text(encoding="utf-8")

    assert 'down_revision = "0248_contract_rate_currencies"' in migration
    for source in (migration, entrypoint):
        assert "rate_candidate = contract.rate_candidate" not in source
        assert (
            "rate_client = COALESCE(order_row.rate_client, contract.rate_client)"
            not in source
        )
        for token in (
            "rate_candidate NUMERIC(12, 3) NULL",
            "rate_unit = COALESCE(contract.rate_unit, 'monthly'::rateunit)",
            "rate_client_currency = COALESCE(",
            "rate_candidate_currency = COALESCE(",
            "client_order_offboarding_cases",
            "remaining_md_snapshot NUMERIC(16, 6)",
            "uses_shared_md_pool BOOLEAN NOT NULL DEFAULT FALSE",
            "md_consultant_ended",
            "decyzja_md_wymagana",
            "usuniecie_puli_md",
            "przeniesienie_puli_md",
        ):
            assert token in source

        alert_fk_tail = source.split("ADD CONSTRAINT fk_dl_alerts_offboarding_case", 1)[
            1
        ].split(";", 1)[0]
        assert "ON DELETE SET NULL NOT VALID" in alert_fk_tail
