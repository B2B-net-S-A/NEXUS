"""Ręczny aneks, który niczego nie zmienia, nie powstaje (decyzja Artura 19.11.2026).

Na produkcji 19.11.2026 trzy kontrakty miały po 2–3 identyczne aneksy z okna
„Dodaj aneks”, a jedno „przedłużenie” skracało koniec umowy. Serwer przyjmował
każdy wpis, a aneksu nie da się usunąć. Reguła odmawia duplikatu (409), aneksu
bez zmiany i przedłużenia na wcześniejszą datę (422) tylko przy ręcznym zapisie.
Stawkę porównuje z harmonogramem w dniu kroku, więc przesunięcie dnia wejścia tej
samej stawki przechodzi.

Kwoty w testach są umowne.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from app.models.contract_amendment import ContractAmendmentType
from app.schemas.contract_amendment import ContractAmendmentCreate
from app.services.contract_amendment_guard import (
    REASON_DUPLICATE,
    REASON_EXTENSION_SHORTENS,
    REASON_NO_CHANGE,
    AmendmentBaseline,
    find_redundant_amendment,
    requested_values,
    same_amendment,
)


@dataclass
class _Saved:
    id: int
    new_values: Optional[dict]
    created_at: datetime


def _baseline(**overrides) -> AmendmentBaseline:
    values = {
        "candidate_rate": Decimal("100"),
        "client_rate": Decimal("200"),
        "rate_unit": "hourly",
        "billing_hours_per_month": 168,
        "end_date": None,
        "project_name": "Projekt",
        "team_name": "Zespół",
    }
    values.update(overrides)
    return AmendmentBaseline(**values)


def _rate(**fields) -> ContractAmendmentCreate:
    return ContractAmendmentCreate(
        amendment_type=ContractAmendmentType.rate_change,
        effective_date=fields.pop("effective_date", date(2026, 7, 1)),
        **fields,
    )


def _extension(new_end: Optional[date]) -> ContractAmendmentCreate:
    return ContractAmendmentCreate(
        amendment_type=ContractAmendmentType.extension,
        effective_date=date(2026, 7, 1),
        new_end_date=new_end,
    )


_SAVED_AT = datetime(2026, 6, 29, 11, 0, tzinfo=timezone.utc)


# ── Czysta reguła (bez bazy) ────────────────────────────────────────────────


def test_identical_rate_change_is_a_duplicate():
    saved = _Saved(7, {"rate_client": 190, "rate_candidate": 95}, _SAVED_AT)
    data = _rate(new_rate_client=Decimal("190"), new_rate_candidate=Decimal("95.0"))

    refused = find_redundant_amendment(
        data,
        _baseline(candidate_rate=Decimal("95"), client_rate=Decimal("190")),
        [saved],
    )

    assert refused is not None
    assert refused.status_code == 409
    assert refused.detail() == {
        "reason": REASON_DUPLICATE,
        "message": "Taki aneks już jest (zapisany 29.06.2026). "
        "Drugi taki sam niczego nie zmieni.",
        "amendment_id": 7,
    }


def test_duplicate_message_uses_the_company_calendar_day():
    late_evening_utc = datetime(2026, 6, 29, 22, 30, tzinfo=timezone.utc)
    saved = _Saved(3, {"rate_client": 190}, late_evening_utc)

    refused = find_redundant_amendment(
        _rate(new_rate_client=Decimal("190")),
        _baseline(client_rate=Decimal("190")),
        [saved],
    )

    assert refused is not None
    assert "30.06.2026" in refused.message


def test_returning_to_values_overridden_the_same_day_is_not_a_duplicate():
    first = _Saved(1, {"rate_client": 190}, _SAVED_AT)
    correction = _Saved(2, {"rate_client": 185}, _SAVED_AT + timedelta(minutes=5))

    refused = find_redundant_amendment(
        _rate(new_rate_client=Decimal("190")),
        _baseline(client_rate=Decimal("185")),
        [first, correction],
    )

    assert refused is None


def test_same_day_with_other_rate_fields_is_not_the_same_amendment():
    saved = _Saved(7, {"rate_client": 190, "rate_candidate": 95}, _SAVED_AT)

    assert not same_amendment(
        ContractAmendmentType.rate_change,
        {"rate_client": Decimal("190")},
        saved.new_values,
    )


def test_rate_already_in_the_schedule_on_the_step_day_is_no_change():
    refused = find_redundant_amendment(
        _rate(new_rate_client=Decimal("190")),
        _baseline(client_rate=Decimal("190")),
        [],
    )

    assert refused is not None
    assert (refused.status_code, refused.reason) == (422, REASON_NO_CHANGE)
    assert "01.07.2026" in refused.message


def test_moving_a_rate_to_an_earlier_day_passes():
    """Stawka „na dziś” jest już nowa, ale w dniu kroku obowiązuje stara.

    Tak wyglądała poprawka dnia wejścia stawki w zgłoszeniu: zrzut ``old_values``
    pokazywał „X → X”, a krok zmieniał stawkę na pierwsze dni miesiąca.
    """
    refused = find_redundant_amendment(
        _rate(new_rate_client=Decimal("180")),
        _baseline(client_rate=Decimal("200")),
        [],
    )

    assert refused is None


def test_one_changed_field_is_enough():
    refused = find_redundant_amendment(
        _rate(new_rate_client=Decimal("200"), new_rate_candidate=Decimal("110")),
        _baseline(),
        [],
    )

    assert refused is None


def test_unit_switch_with_the_same_number_is_a_change():
    refused = find_redundant_amendment(
        _rate(new_rate_client=Decimal("200"), new_rate_unit="monthly"),
        _baseline(),
        [],
    )

    assert refused is None


def test_rate_change_without_any_rate_is_left_to_the_router():
    # Router odpowiada wtedy 422 „At least one rate field must change”.
    assert find_redundant_amendment(_rate(), _baseline(), []) is None


def test_extension_to_the_current_end_is_no_change():
    refused = find_redundant_amendment(
        _extension(date(2026, 9, 30)), _baseline(end_date=date(2026, 9, 30)), []
    )

    assert refused is not None
    assert (refused.status_code, refused.reason) == (422, REASON_NO_CHANGE)


def test_extension_that_shortens_the_agreement_is_refused():
    refused = find_redundant_amendment(
        _extension(date(2026, 7, 31)), _baseline(end_date=date(2026, 8, 31)), []
    )

    assert refused is not None
    assert (refused.status_code, refused.reason) == (422, REASON_EXTENSION_SHORTENS)
    assert "31.08.2026" in refused.message
    assert "Zakończ współpracę" in refused.message


def test_longer_extension_passes():
    assert (
        find_redundant_amendment(
            _extension(date(2026, 12, 31)), _baseline(end_date=date(2026, 8, 31)), []
        )
        is None
    )


def test_extension_of_an_agreement_without_end_date_is_left_to_existing_rules():
    # Bezterminowa umowa B2B: o odmowie decyduje reguła daty końca B2B.
    assert (
        find_redundant_amendment(_extension(date(2026, 12, 31)), _baseline(), [])
        is None
    )
    assert find_redundant_amendment(_extension(None), _baseline(), []) is None


def test_identical_extension_is_a_duplicate_even_after_a_later_change():
    saved = _Saved(19, {"end_date": "2026-09-30", "status": "active"}, _SAVED_AT)

    refused = find_redundant_amendment(
        _extension(date(2026, 9, 30)), _baseline(end_date=date(2026, 12, 31)), [saved]
    )

    assert refused is not None
    assert (refused.status_code, refused.amendment_id) == (409, 19)


def test_scope_change_to_the_same_project_is_no_change():
    data = ContractAmendmentCreate(
        amendment_type=ContractAmendmentType.scope_change,
        effective_date=date(2026, 7, 1),
        new_project_name="Projekt",
    )

    refused = find_redundant_amendment(data, _baseline(), [])

    assert refused is not None
    assert refused.reason == REASON_NO_CHANGE


def test_early_termination_is_left_to_the_termination_window():
    data = ContractAmendmentCreate(
        amendment_type=ContractAmendmentType.early_termination,
        effective_date=date(2026, 7, 1),
    )

    assert requested_values(data) == {}
    assert find_redundant_amendment(data, _baseline(), []) is None


# ── Trasa API (baza; sprawdza CI) ────────────────────────────────────────────


async def _seed_contract(
    *, contract_type: str = "b2b", end_date: Optional[date] = None
):
    from app.core.database import AsyncSessionLocal
    from app.core.scheduling import business_today
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.contract import Contract, ContractStatus, ContractType, RateUnit

    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Aneks bez zmiany {suffix}")
        candidate = Candidate(
            name="Aneks",
            lastname=f"Osoba{suffix}",
            email=f"amendment-guard-{suffix}@example.test",
        )
        db.add_all([client, candidate])
        await db.flush()
        contract = Contract(
            candidate_id=candidate.id,
            client_id=client.id,
            contract_type=ContractType(contract_type),
            status=ContractStatus.active,
            start_date=business_today() - timedelta(days=200),
            end_date=end_date,
            rate_unit=RateUnit.hourly,
            currency="PLN",
            rate_candidate=Decimal("100"),
            rate_client=Decimal("200"),
        )
        db.add(contract)
        await db.commit()
        return contract.id


async def _amendment_count(contract_id: int) -> int:
    from sqlalchemy import func, select

    from app.core.database import AsyncSessionLocal
    from app.models.contract_amendment import ContractAmendment

    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(func.count())
            .select_from(ContractAmendment)
            .where(ContractAmendment.contract_id == contract_id)
        )


async def test_second_identical_rate_annex_is_refused_by_the_route(
    app_client, app_auth_headers
):
    from app.core.scheduling import business_today

    contract_id = await _seed_contract()
    payload = {
        "amendment_type": "rate_change",
        "effective_date": (business_today() + timedelta(days=30)).isoformat(),
        "new_rate_client": 210,
        "new_rate_candidate": 105,
    }
    first = await app_client.post(
        f"/api/contracts/{contract_id}/amendments",
        json=payload,
        headers=app_auth_headers,
    )
    assert first.status_code == 201, first.text

    second = await app_client.post(
        f"/api/contracts/{contract_id}/amendments",
        json=payload,
        headers=app_auth_headers,
    )

    assert second.status_code == 409, second.text
    assert second.json()["detail"]["reason"] == REASON_DUPLICATE
    assert second.json()["detail"]["amendment_id"] == first.json()["id"]
    assert await _amendment_count(contract_id) == 1


async def test_rate_annex_equal_to_the_schedule_is_refused_by_the_route(
    app_client, app_auth_headers
):
    from app.core.scheduling import business_today

    contract_id = await _seed_contract()

    resp = await app_client.post(
        f"/api/contracts/{contract_id}/amendments",
        json={
            "amendment_type": "rate_change",
            "effective_date": (business_today() - timedelta(days=10)).isoformat(),
            "new_rate_client": 200,
        },
        headers=app_auth_headers,
    )

    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["reason"] == REASON_NO_CHANGE
    assert await _amendment_count(contract_id) == 0


async def test_extension_shortening_a_mandate_is_refused_by_the_route(
    app_client, app_auth_headers
):
    from app.core.scheduling import business_today

    end = business_today() + timedelta(days=60)
    contract_id = await _seed_contract(contract_type="uzlecenie", end_date=end)

    resp = await app_client.post(
        f"/api/contracts/{contract_id}/amendments",
        json={
            "amendment_type": "extension",
            "effective_date": business_today().isoformat(),
            "new_end_date": (end - timedelta(days=31)).isoformat(),
        },
        headers=app_auth_headers,
    )

    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["reason"] == REASON_EXTENSION_SHORTENS
    assert await _amendment_count(contract_id) == 0
