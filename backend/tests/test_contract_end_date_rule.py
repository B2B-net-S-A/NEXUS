"""Reguła zakładki „Zakończeni" (09.2026) — data końca umowy rządzi zamówieniem.

Ticket: o przynależności do „Zakończonych" decyduje wyłącznie umowa z modułu
Kontrakty (status + data zakończenia), nigdy sam upływ okresu zamówienia.
Trzy skutki po stronie backendu, każdy z testem:

* zmiana daty końca umowy (``PATCH /api/contracts/{id}``) nadpisuje datę końca
  otwartego zamówienia tej osoby tą samą datą — do daty włącznie osoba jest
  w „Aktywni", ``completed`` dopiero gdy dzień nadejdzie;
* PRZEDŁUŻENIE umowy nie wydłuża zamówienia (to PO klienta), a wyczyszczenie
  daty (bezterminowa) nie rusza zamówień;
* wskrzeszenie kontraktu żywym zamówieniem czyni go BEZTERMINOWYM zamiast
  przepisywać datę końca zamówienia (``test_order_extension_revives_contract``
  pilnuje ścieżek writerów; tu — czysty ``sync_contract_to_live_order``).
"""

from __future__ import annotations

import uuid
from contextlib import nullcontext
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus, ContractType, ContractWorkMode

pytestmark = pytest.mark.asyncio


async def _seed_active_contract() -> tuple[int, int]:
    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"VeloRule Test {suffix}")
        candidate = Candidate(name=f"Piotr{suffix}", lastname=f"Testowy{suffix}")
        db.add_all([client, candidate])
        await db.flush()
        contract = Contract(
            candidate_id=candidate.id,
            client_id=client.id,
            contract_type=ContractType.b2b,
            work_mode=ContractWorkMode.remote,
            status=ContractStatus.active,
            start_date=date.today() - timedelta(days=100),
            end_date=None,
            rate_candidate=15000,
            rate_client=20000,
        )
        db.add(contract)
        await db.commit()
        return client.id, contract.id


async def _post_active_order(app_client, headers, client_id, contract_id, *, end):
    resp = await app_client.post(
        f"/api/clients/{client_id}/orders",
        data={
            "contract_id": str(contract_id),
            "title": f"K/2026/{uuid.uuid4().hex[:6]}",
            "start_date": (date.today() - timedelta(days=10)).isoformat(),
            "end_date": end.isoformat(),
            "order_status": "active",
            "rate_client": "20000",
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _order(app_client, headers, client_id, order_id):
    resp = await app_client.get(
        f"/api/clients/{client_id}/orders/{order_id}", headers=headers
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_contract_end_date_caps_the_live_order_and_only_shortens(
    app_client, app_auth_headers
):
    today = date.today()
    client_id, contract_id = await _seed_active_contract()
    order_id = await _post_active_order(
        app_client,
        app_auth_headers,
        client_id,
        contract_id,
        end=today + timedelta(days=120),
    )

    # Administracja wpisuje datę końca umowy (np. 30.09): zamówienie dostaje ją
    # natychmiast, osoba zostaje aktywna do tej daty włącznie.
    new_end = today + timedelta(days=30)
    resp = await app_client.patch(
        f"/api/contracts/{contract_id}",
        json={"end_date": new_end.isoformat()},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "active"
    order = await _order(app_client, app_auth_headers, client_id, order_id)
    assert order["end_date"] == new_end.isoformat()
    assert order["status"] == "active"

    activities = await app_client.get(
        f"/api/contracts/{contract_id}/activities", headers=app_auth_headers
    )
    assert activities.status_code == 200, activities.text
    synced = [
        a
        for a in activities.json()
        if (a.get("details") or {}).get("orders_synced_to_end_date") == 1
    ]
    assert synced, "audyt PATCH-a ma nieść liczbę zsynchronizowanych zamówień"

    # Przedłużenie umowy NIE wydłuża zamówienia — to PO klienta.
    resp = await app_client.patch(
        f"/api/contracts/{contract_id}",
        json={"end_date": (today + timedelta(days=90)).isoformat()},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    order = await _order(app_client, app_auth_headers, client_id, order_id)
    assert order["end_date"] == new_end.isoformat()

    # Bezterminowa: zamówienia nietknięte.
    resp = await app_client.patch(
        f"/api/contracts/{contract_id}",
        json={"end_date": None},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["end_date"] is None
    order = await _order(app_client, app_auth_headers, client_id, order_id)
    assert order["end_date"] == new_end.isoformat()
    assert order["status"] == "active"


async def test_past_contract_end_date_completes_the_order_at_once(
    app_client, app_auth_headers
):
    """Data z przeszłości: zamówienie domknięte od razu, nie za noc."""
    today = date.today()
    client_id, contract_id = await _seed_active_contract()
    order_id = await _post_active_order(
        app_client,
        app_auth_headers,
        client_id,
        contract_id,
        end=today + timedelta(days=60),
    )
    ended = today - timedelta(days=1)
    resp = await app_client.patch(
        f"/api/contracts/{contract_id}",
        json={"end_date": ended.isoformat()},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    order = await _order(app_client, app_auth_headers, client_id, order_id)
    assert order["end_date"] == ended.isoformat()
    assert order["status"] == "completed"


async def test_revival_by_live_order_makes_the_contract_indefinite():
    """Czysty serwis: wskrzeszenie nie przepisuje daty końca zamówienia."""
    from app.services.contract_lifecycle import sync_contract_to_live_order

    today = date(2032, 4, 10)
    contract = Contract(
        id=906,
        client_id=1,
        status=ContractStatus.ended,
        end_date=today - timedelta(days=3),
        client_order_end_date=today - timedelta(days=3),
    )

    class _Db:
        def __init__(self):
            self.no_autoflush = nullcontext()
            self.added = []

        async def execute(self, statement):
            return SimpleNamespace(
                one_or_none=lambda: (
                    contract.status,
                    contract.end_date,
                    contract.client_order_end_date,
                )
            )

        def add(self, value):
            self.added.append(value)

    db = _Db()
    order_end = today + timedelta(days=90)
    assert await sync_contract_to_live_order(
        db,
        contract,
        order_start=today - timedelta(days=5),
        order_end=order_end,
        actor_id=7,
        today=today,
    )
    assert contract.status == ContractStatus.active
    assert contract.end_date is None
    # Data z zamówienia ma swoje miejsce: „Koniec zamówienia u klienta".
    assert contract.client_order_end_date == order_end
    assert len(db.added) == 1  # contract_reopened

    # Nieśledzony koniec zamówienia u klienta zostaje NULL — nie wymyślamy daty.
    untracked = Contract(
        id=907,
        client_id=1,
        status=ContractStatus.ended,
        end_date=today - timedelta(days=3),
    )
    contract = untracked
    db = _Db()
    assert await sync_contract_to_live_order(
        db, untracked, order_start=today, order_end=None, actor_id=7, today=today
    )
    assert untracked.end_date is None and untracked.client_order_end_date is None
