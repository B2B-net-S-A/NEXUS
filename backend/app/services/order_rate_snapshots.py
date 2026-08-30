"""Snapshot and conversion helpers for client-order rates.

An order owns the unit/currencies in which its two rates were agreed.  A
Contract is only the default at creation time; using the live contract on
every read made historical orders silently change when the contract changed.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from app.models.contract import Contract, RateUnit


HOURS_PER_DAY = Decimal("8")
DAYS_PER_MONTH = Decimal("22")
RATE_SCALE = Decimal("0.001")


def convert_order_rate(
    value: Optional[Decimal | int | float],
    from_unit: RateUnit,
    to_unit: RateUnit,
    billing_hours_per_month: int = 160,
) -> Optional[Decimal]:
    """Convert a rate while preserving the fixed 1 MD = 8 h invariant.

    Each direct pair preserves the same normalization used by margin
    analytics: hour↔MD is always 8, month↔MD is 22, while month↔hour uses the
    order's billing-hours snapshot.  Bridging every pair through MD would turn
    a 160-hour monthly rate into a 176-hour one.
    """

    if value is None:
        return None
    amount = Decimal(str(value))
    if from_unit == to_unit:
        return amount.quantize(RATE_SCALE, rounding=ROUND_HALF_UP)

    if {from_unit, to_unit} == {RateUnit.hourly, RateUnit.daily}:
        converted = (
            amount * HOURS_PER_DAY
            if from_unit == RateUnit.hourly
            else amount / HOURS_PER_DAY
        )
    elif {from_unit, to_unit} == {RateUnit.daily, RateUnit.monthly}:
        converted = (
            amount * DAYS_PER_MONTH
            if from_unit == RateUnit.daily
            else amount / DAYS_PER_MONTH
        )
    else:
        hours = Decimal(str(billing_hours_per_month or 160))
        converted = amount * hours if from_unit == RateUnit.hourly else amount / hours
    return converted.quantize(RATE_SCALE, rounding=ROUND_HALF_UP)


def inherited_order_rate_fields(
    contract: Contract,
    *,
    rate_candidate: Optional[Decimal] = None,
    rate_client: Optional[Decimal] = None,
) -> dict[str, object]:
    """Columns copied from Contract when a new standalone order is created."""

    return {
        "rate_candidate": (
            rate_candidate if rate_candidate is not None else contract.rate_candidate
        ),
        "rate_client": rate_client if rate_client is not None else contract.rate_client,
        "rate_unit": contract.rate_unit,
        "billing_hours_per_month": contract.billing_hours_per_month or 160,
        "rate_client_currency": contract.resolved_rate_client_currency,
        "rate_candidate_currency": contract.resolved_rate_candidate_currency,
        # Compatibility alias always follows the client/revenue side.
        "currency": contract.resolved_rate_client_currency,
    }
