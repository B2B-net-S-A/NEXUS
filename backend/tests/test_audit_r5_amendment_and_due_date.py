"""Audyt r5 (25.11.2026): ręczny aneks stawki i termin płatności faktury kontraktora.

1. ``ContractAmendmentCreate`` przyjmował stawkę 0 i ujemną, zero godzin
   w miesiącu i dowolny tekst jako jednostkę — handler zapisywał to do
   harmonogramu stawek, marży i dzwonka Finansów. Schemat odmawia (422).
2. Termin płatności faktury kontraktora liczył się od dnia UTC wejścia faktury
   do KSeF, a nie od dnia firmy (Warszawa): faktura pobrana 1.12 o 0:30
   w Warszawie (30.11 23:30 UTC) dostawała termin dzień za wcześnie.

Dane fikcyjne; bez bazy (poza jednym testem trasy, który sprawdza CI).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.models.contract_amendment import ContractAmendmentType
from app.schemas.contract_amendment import ContractAmendmentCreate
from app.services.client_settlements import consultant, contractor_invoices


def _rate_change(**fields) -> ContractAmendmentCreate:
    return ContractAmendmentCreate(
        amendment_type=ContractAmendmentType.rate_change,
        effective_date=date(2026, 12, 1),
        **fields,
    )


# ── Aneks stawki ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("field", ["new_rate_candidate", "new_rate_client"])
@pytest.mark.parametrize("value", ["0", "-10"])
def test_rate_amendment_refuses_zero_and_negative_rates(field, value):
    with pytest.raises(ValidationError):
        _rate_change(**{field: Decimal(value)})


@pytest.mark.parametrize("hours", [0, -168])
def test_rate_amendment_refuses_non_positive_billing_hours(hours):
    with pytest.raises(ValidationError):
        _rate_change(new_billing_hours_per_month=hours)


@pytest.mark.parametrize("unit", ["godzinowa", "weekly", "HOURLY", ""])
def test_rate_amendment_refuses_unknown_unit(unit):
    with pytest.raises(ValidationError):
        _rate_change(new_rate_unit=unit)


def test_rate_amendment_accepts_valid_values():
    data = _rate_change(
        new_rate_candidate=Decimal("120.50"),
        new_rate_client=Decimal("150"),
        new_rate_unit="hourly",
        new_billing_hours_per_month=1,
    )
    assert data.new_rate_unit == "hourly"
    for unit in ("hourly", "daily", "monthly"):
        assert _rate_change(new_rate_unit=unit).new_rate_unit == unit
    # Pola nieustawione zostają puste — aneks zmienia tylko to, co podano.
    assert _rate_change().new_rate_candidate is None


@pytest.mark.asyncio
async def test_amendment_route_answers_422_for_zero_rate(app_client, app_auth_headers):
    # Walidacja ciała przed handlerem: kontrakt nie musi istnieć.
    for body in (
        {"new_rate_candidate": 0},
        {"new_rate_client": -5},
        {"new_billing_hours_per_month": 0},
        {"new_rate_unit": "weekly"},
    ):
        resp = await app_client.post(
            "/api/contracts/2147483647/amendments",
            json={
                "amendment_type": "rate_change",
                "effective_date": "2026-12-01",
                **body,
            },
            headers=app_auth_headers,
        )
        assert resp.status_code == 422, (body, resp.text)


# ── Termin płatności faktury kontraktora ────────────────────────────────────


def _invoice(acquired_at):
    return SimpleNamespace(acquired_at=acquired_at)


def test_due_date_counts_from_the_company_day_not_utc():
    # 30.11 23:30 UTC = 1.12 0:30 w Warszawie → termin 15.12 (1.12 + 14 dni).
    late = _invoice(datetime(2026, 11, 30, 23, 30, tzinfo=timezone.utc))
    assert contractor_invoices.due_date(late, 14) == date(2026, 12, 15)
    # W dzień ten sam dzień w obu strefach.
    noon = _invoice(datetime(2026, 11, 30, 11, 0, tzinfo=timezone.utc))
    assert contractor_invoices.due_date(noon, 14) == date(2026, 12, 14)


def test_due_date_is_empty_without_days_or_acquisition():
    assert contractor_invoices.due_date(_invoice(None), 14) is None
    moment = datetime(2026, 11, 30, 23, 30, tzinfo=timezone.utc)
    assert contractor_invoices.due_date(_invoice(moment), None) is None


@pytest.mark.asyncio
async def test_consultant_portal_due_date_uses_the_company_day(monkeypatch):
    invoice = SimpleNamespace(
        acquired_at=datetime(2026, 11, 30, 23, 30, tzinfo=timezone.utc),
        nip_state=next(iter(contractor_invoices.BOUND)),
        invoice_number="FV/1/12/2026",
        ksef_number="0000000000-20261201-TEST-01",
        net_amount=Decimal("1000"),
    )
    settlement = SimpleNamespace(contract_id=1)

    async def for_month(db, contract_ids, period):
        return {1: [invoice]}

    async def rules_for(db, client_id, period):
        return {}

    async def expected_by_contract(db, contract_ids, period):
        return {}

    monkeypatch.setattr(contractor_invoices, "for_month", for_month)
    monkeypatch.setattr(contractor_invoices, "state", lambda *a: "matches")
    monkeypatch.setattr(consultant.service, "rules_for", rules_for)
    monkeypatch.setattr(
        consultant.settlement_extras, "expected_by_contract", expected_by_contract
    )

    result = await consultant._ksef(None, settlement, 7, "2026-11", 14)

    assert result["due_date"] == "2026-12-15"
    assert "15.12.2026" in result["label"]
