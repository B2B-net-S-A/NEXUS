"""„Dodaj przedłużenie" i „Zakończ zamówienie" — walidacja (audyt 24.09.2026).

* S6 — stawki bez ``ge=0`` i limitu cyfr: ujemna stawka aktywowała szkic,
  przepełnienie NUMERIC kończyło się 500, „NaN" zapisywało się jako wartość.
* S7 — koniec przed startem → 422; domyślny status ``active`` przy
  niekompletnym zamówieniu okresowym → szkic; ``completed``/``cancelled``
  przy tworzeniu → 422.
* W2 — pusty szkic z podpisu umowy jest wchłaniany przez przedłużenie.
* N2 — „Zakończ zamówienie" na szkicu → 409 z podpowiedzią.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.contract import Contract, ContractStatus, ContractType, RateUnit

pytestmark = pytest.mark.asyncio


async def _seed(*, rate_client: Decimal | None = Decimal("150.000")) -> tuple[int, int]:
    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Walidacja {suffix}")
        candidate = Candidate(name=f"Ola{suffix}", lastname=f"Test{suffix}")
        db.add_all([client, candidate])
        await db.flush()
        contract = Contract(
            candidate_id=candidate.id,
            client_id=client.id,
            contract_type=ContractType.b2b,
            status=ContractStatus.active,
            start_date=business_today() - timedelta(days=100),
            rate_candidate=Decimal("100.000"),
            rate_client=rate_client,
            rate_unit=RateUnit.hourly,
            currency="PLN",
            rate_candidate_currency="PLN",
        )
        db.add(contract)
        await db.commit()
        return client.id, contract.id


def _form(contract_id: int, **extra) -> dict[str, str]:
    today = business_today()
    data = {
        "contract_id": str(contract_id),
        "title": f"Z/{uuid.uuid4().hex[:6]}",
        "order_type": "periodic",
        "start_date": today.isoformat(),
        "end_date": (today + timedelta(days=90)).isoformat(),
        "rate_client": "150",
    }
    data.update(extra)
    return data


@pytest.mark.parametrize(
    "field, value",
    [
        ("rate_client", "-5"),
        ("rate_candidate", "-1"),
        ("rate_client", "1234567890123"),
        ("total_value", "NaN"),
        ("total_value", "-10"),
        ("total_value", "99999999999999"),
    ],
)
async def test_extension_rejects_invalid_amounts(
    app_client, app_auth_headers, field, value
):
    client_id, contract_id = await _seed()
    resp = await app_client.post(
        f"/api/clients/{client_id}/orders",
        data=_form(contract_id, **{field: value}),
        headers=app_auth_headers,
    )
    assert resp.status_code == 422, resp.text


async def test_extension_rejects_end_before_start(app_client, app_auth_headers):
    client_id, contract_id = await _seed()
    today = business_today()
    resp = await app_client.post(
        f"/api/clients/{client_id}/orders",
        data=_form(
            contract_id,
            start_date=today.isoformat(),
            end_date=(today - timedelta(days=1)).isoformat(),
        ),
        headers=app_auth_headers,
    )
    assert resp.status_code == 422, resp.text
    assert "wcześniejsza" in resp.text


@pytest.mark.parametrize("status_value", ["completed", "cancelled"])
async def test_extension_cannot_be_created_as_history(
    app_client, app_auth_headers, status_value
):
    client_id, contract_id = await _seed()
    resp = await app_client.post(
        f"/api/clients/{client_id}/orders",
        data=_form(contract_id, order_status=status_value),
        headers=app_auth_headers,
    )
    assert resp.status_code == 422, resp.text


async def test_incomplete_periodic_extension_is_saved_as_draft(
    app_client, app_auth_headers
):
    """Domyślny status ``active`` bez stawki klienta → szkic, nie aktywne."""
    client_id, contract_id = await _seed(rate_client=None)
    data = _form(contract_id)
    data.pop("rate_client")
    resp = await app_client.post(
        f"/api/clients/{client_id}/orders", data=data, headers=app_auth_headers
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["status"] == "draft"


async def test_patch_rejects_end_before_start(app_client, app_auth_headers):
    client_id, contract_id = await _seed()
    created = await app_client.post(
        f"/api/clients/{client_id}/orders",
        data=_form(contract_id),
        headers=app_auth_headers,
    )
    assert created.status_code == 201, created.text
    order_id = created.json()["id"]
    resp = await app_client.patch(
        f"/api/clients/{client_id}/orders/{order_id}",
        json={"end_date": (business_today() - timedelta(days=5)).isoformat()},
        headers=app_auth_headers,
    )
    assert resp.status_code == 422, resp.text


async def test_extension_absorbs_the_empty_signing_draft(app_client, app_auth_headers):
    client_id, contract_id = await _seed()
    async with AsyncSessionLocal() as db:
        shell = ClientOrder(
            client_id=client_id,
            contract_id=contract_id,
            title="Ola Test — Java Developer",
            status=ClientOrderStatus.draft,
            start_date=business_today() - timedelta(days=100),
            notes="Auto-utworzone po potwierdzeniu obustronnego podpisania umowy.",
        )
        kept = ClientOrder(
            client_id=client_id,
            contract_id=contract_id,
            title="Szkic ręczny",
            status=ClientOrderStatus.draft,
            notes="wpisane ręcznie",
        )
        db.add_all([shell, kept])
        await db.commit()
        shell_id, kept_id = shell.id, kept.id

    resp = await app_client.post(
        f"/api/clients/{client_id}/orders",
        data=_form(contract_id),
        headers=app_auth_headers,
    )
    assert resp.status_code == 201, resp.text

    async with AsyncSessionLocal() as db:
        ids = set(
            (
                await db.scalars(
                    select(ClientOrder.id).where(ClientOrder.contract_id == contract_id)
                )
            ).all()
        )
    assert shell_id not in ids, "pusty szkic z podpisu wchłonięty"
    assert kept_id in ids, "szkic wpisany przez człowieka zostaje"
    assert resp.json()["id"] in ids


async def test_closing_a_draft_is_refused_with_a_hint(app_client, app_auth_headers):
    client_id, contract_id = await _seed()
    async with AsyncSessionLocal() as db:
        draft = ClientOrder(
            client_id=client_id,
            contract_id=contract_id,
            title="Szkic",
            status=ClientOrderStatus.draft,
        )
        db.add(draft)
        await db.commit()
        draft_id = draft.id

    resp = await app_client.post(
        f"/api/clients/{client_id}/orders/{draft_id}/close",
        json={"closure_date": business_today().isoformat()},
        headers=app_auth_headers,
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["code"] == "order_is_draft"
