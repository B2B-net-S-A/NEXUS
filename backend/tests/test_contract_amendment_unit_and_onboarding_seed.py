"""AN-03 i FE-04 — aneks jednostki z datą przyszłą oraz atomowa lista onboardingu.

AN-03: jednostka rozliczenia i liczba godzin nie mają harmonogramu — zapis
zmienia je od razu. Aneks „od przyszłego miesiąca” przeliczał więc dzisiejsze
kwoty nową jednostką przed dniem jej wejścia w życie. Backend odmawia 422.

FE-04: domyślna lista onboardingowa powstawała z ośmiu osobnych POST-ów
z przeglądarki; podwójne kliknięcie dublowało listę. Teraz jedno wywołanie,
blokada wiersza kontraktu i idempotencja.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.api.contracts import DEFAULT_ONBOARDING_ITEMS
from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus, RateUnit
from app.models.contract_onboarding import ContractOnboardingItem

pytestmark = pytest.mark.asyncio

_UNIT_REFUSAL = (
    "Zmianę jednostki lub liczby godzin wpisz w dniu jej wejścia w życie — "
    "nie da się jej zaplanować z wyprzedzeniem."
)


async def _seed_contract() -> int:
    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Amend Client {unique}")
        candidate = Candidate(name="Amend", lastname=f"Contractor-{unique}")
        db.add_all([client, candidate])
        await db.flush()
        contract = Contract(
            candidate_id=candidate.id,
            client_id=client.id,
            status=ContractStatus.active,
            contract_type="uop",
            start_date=date(2025, 1, 1),
            end_date=None,
            rate_unit=RateUnit.hourly,
            billing_hours_per_month=160,
            rate_client=Decimal("200"),
            rate_candidate=Decimal("150"),
            currency="PLN",
        )
        db.add(contract)
        await db.commit()
        return contract.id


@pytest.mark.parametrize(
    "change",
    [{"new_rate_unit": "monthly"}, {"new_billing_hours_per_month": 168}],
)
async def test_future_unit_or_hours_change_is_refused(
    app_client: AsyncClient, app_auth_headers: dict, change: dict
):
    contract_id = await _seed_contract()
    response = await app_client.post(
        f"/api/contracts/{contract_id}/amendments",
        json={
            "amendment_type": "rate_change",
            "effective_date": (business_today() + timedelta(days=10)).isoformat(),
            **change,
        },
        headers=app_auth_headers,
    )
    assert response.status_code == 422, response.text
    assert response.json()["detail"] == _UNIT_REFUSAL

    after = (
        await app_client.get(f"/api/contracts/{contract_id}", headers=app_auth_headers)
    ).json()
    assert after["rate_unit"] == "hourly"
    assert after["billing_hours_per_month"] == 160


async def test_unit_change_on_its_effective_day_is_accepted(
    app_client: AsyncClient, app_auth_headers: dict
):
    contract_id = await _seed_contract()
    response = await app_client.post(
        f"/api/contracts/{contract_id}/amendments",
        json={
            "amendment_type": "rate_change",
            "effective_date": business_today().isoformat(),
            "new_billing_hours_per_month": 168,
        },
        headers=app_auth_headers,
    )
    assert response.status_code == 201, response.text


async def test_future_rate_only_change_is_still_allowed(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Stawka ma harmonogram, więc może być zaplanowana — reguła jej nie dotyczy."""
    contract_id = await _seed_contract()
    response = await app_client.post(
        f"/api/contracts/{contract_id}/amendments",
        json={
            "amendment_type": "rate_change",
            "effective_date": (business_today() + timedelta(days=10)).isoformat(),
            "new_rate_candidate": 160,
        },
        headers=app_auth_headers,
    )
    assert response.status_code == 201, response.text


async def _onboarding_count(contract_id: int) -> int:
    async with AsyncSessionLocal() as db:
        return int(
            await db.scalar(
                select(func.count(ContractOnboardingItem.id)).where(
                    ContractOnboardingItem.contract_id == contract_id
                )
            )
        )


async def test_onboarding_seed_creates_the_default_list_once(
    app_client: AsyncClient, app_auth_headers: dict
):
    contract_id = await _seed_contract()
    path = f"/api/contracts/{contract_id}/onboarding/seed"

    first = await app_client.post(path, headers=app_auth_headers)
    assert first.status_code == 200, first.text
    assert [item["label"] for item in first.json()] == list(DEFAULT_ONBOARDING_ITEMS)
    assert [item["order"] for item in first.json()] == list(
        range(len(DEFAULT_ONBOARDING_ITEMS))
    )

    second = await app_client.post(path, headers=app_auth_headers)
    assert second.status_code == 200, second.text
    assert [item["id"] for item in second.json()] == [
        item["id"] for item in first.json()
    ]
    assert await _onboarding_count(contract_id) == len(DEFAULT_ONBOARDING_ITEMS)


async def test_parallel_onboarding_seeds_do_not_duplicate_the_list(
    app_client: AsyncClient, app_auth_headers: dict
):
    contract_id = await _seed_contract()
    path = f"/api/contracts/{contract_id}/onboarding/seed"
    responses = await asyncio.gather(
        *(app_client.post(path, headers=app_auth_headers) for _ in range(3))
    )
    assert all(r.status_code == 200 for r in responses), [r.text for r in responses]
    assert await _onboarding_count(contract_id) == len(DEFAULT_ONBOARDING_ITEMS)


async def test_onboarding_seed_keeps_an_existing_list(
    app_client: AsyncClient, app_auth_headers: dict
):
    contract_id = await _seed_contract()
    created = await app_client.post(
        f"/api/contracts/{contract_id}/onboarding",
        json={"label": "Karta dostępu do biura", "order": 0},
        headers=app_auth_headers,
    )
    assert created.status_code == 201, created.text

    seeded = await app_client.post(
        f"/api/contracts/{contract_id}/onboarding/seed", headers=app_auth_headers
    )
    assert seeded.status_code == 200, seeded.text
    assert [item["label"] for item in seeded.json()] == ["Karta dostępu do biura"]


async def test_onboarding_seed_for_missing_contract_is_404(
    app_client: AsyncClient, app_auth_headers: dict
):
    response = await app_client.post(
        "/api/contracts/999999999/onboarding/seed", headers=app_auth_headers
    )
    assert response.status_code == 404
