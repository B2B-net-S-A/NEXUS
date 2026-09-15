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
# Kontrakt trzyma stawki z 6 miejscami (NUMERIC(16,6), migracja 0309): stawka
# dzienna ÷ 8 ma do 5 miejsc po przecinku (1001,55 zł/MD = 125,19375 zł/h),
# a zaokrąglenie do 0,001 zmieniałoby kwotę po powrocie do MD.
CONTRACT_RATE_SCALE = Decimal("0.000001")


def convert_order_rate(
    value: Optional[Decimal | int | float],
    from_unit: RateUnit,
    to_unit: RateUnit,
    billing_hours_per_month: int = 160,
    *,
    scale: Decimal = RATE_SCALE,
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
        return amount.quantize(scale, rounding=ROUND_HALF_UP)

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
    return converted.quantize(scale, rounding=ROUND_HALF_UP)


# 22 MD × 8 h. Kontrakt przeliczony z MD na godziny (decyzja 14.09.2026:
# stawki w Kontraktach są godzinowe) liczy tyle godzin w miesiącu — i po tym
# go rozpoznajemy: zamówienia dziedziczące z takiego kontraktu dalej są w MD.
MD_BILLING_HOURS_PER_MONTH = 176


def order_unit_for_contract(contract: Contract) -> RateUnit:
    """Jednostka, w której zamówienie DZIEDZICZY stawki z kontraktu.

    Kontrakt nie jest już w MD (``contract_order_sync.contract_unit_for_order``),
    ale zamówienia u klienta rozliczanego w MD nadal mają być w MD — ticket
    wprost: zamówienia nie zmieniają formatu. Kontrakt godzinowy liczony
    176 h/mc powstał z MD, więc dziedziczące zamówienie wraca do MD; każdy inny
    kontrakt przekazuje swoją jednostkę jak dotąd.
    """
    unit = RateUnit(contract.rate_unit)
    if (
        unit == RateUnit.hourly
        and contract.billing_hours_per_month == MD_BILLING_HOURS_PER_MONTH
    ):
        return RateUnit.daily
    return unit


def contract_rate_in_unit(
    value: Optional[Decimal | int | float],
    contract: Contract,
    to_unit: RateUnit,
    *,
    scale: Decimal = RATE_SCALE,
) -> Optional[Decimal]:
    """Stawka kontraktu wyrażona w jednostce zamówienia.

    Godziny miesiąca bierzemy z KONTRAKTU: to one mówią, ile miesięcznie znaczy
    jego stawka godzinowa. 125 zł/h kontraktu 176-godzinnego to 22 000 zł/mc,
    nie 20 000 — liczba godzin zamówienia opisuje inną kwotę.
    """
    return convert_order_rate(
        value,
        RateUnit(contract.rate_unit),
        RateUnit(to_unit),
        contract.billing_hours_per_month or 160,
        scale=scale,
    )


def order_rate_in_contract_unit(
    value: Optional[Decimal | int | float],
    from_unit: RateUnit,
    contract: Contract,
) -> Optional[Decimal]:
    """Stawka zamówienia w jednostce kontraktu (precyzja kontraktu, godziny kontraktu)."""
    return convert_order_rate(
        value,
        RateUnit(from_unit),
        RateUnit(contract.rate_unit),
        contract.billing_hours_per_month or 160,
        scale=CONTRACT_RATE_SCALE,
    )


def inherited_order_rate_fields(
    contract: Contract,
    *,
    rate_candidate: Optional[Decimal] = None,
    rate_client: Optional[Decimal] = None,
) -> dict[str, object]:
    """Columns copied from Contract when a new standalone order is created.

    Kwoty (także podane jawnie) są w jednostce kontraktu i są przeliczane na
    jednostkę zamówienia (``order_unit_for_contract``) z precyzją zamówienia.
    """

    unit = order_unit_for_contract(contract)
    same_unit = unit == RateUnit(contract.rate_unit)
    return {
        "rate_candidate": contract_rate_in_unit(
            rate_candidate if rate_candidate is not None else contract.rate_candidate,
            contract,
            unit,
        ),
        "rate_client": contract_rate_in_unit(
            rate_client if rate_client is not None else contract.rate_client,
            contract,
            unit,
        ),
        "rate_unit": unit,
        "billing_hours_per_month": (
            contract.billing_hours_per_month or 160 if same_unit else 160
        ),
        "rate_client_currency": contract.resolved_rate_client_currency,
        "rate_candidate_currency": contract.resolved_rate_candidate_currency,
        # Compatibility alias always follows the client/revenue side.
        "currency": contract.resolved_rate_client_currency,
    }
