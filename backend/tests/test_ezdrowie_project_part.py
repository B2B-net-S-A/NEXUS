"""„Część umowy" Centrum e-Zdrowia (ticket #3, Faza C).

Kontrakt: pole ``project_part`` jest wymagane przy tworzeniu zamówienia dla
client_id e-Zdrowia (Flow A przedłużenie i Flow B nowy kontraktor), zabronione
u pozostałych klientów, a Profil wystawia część REPREZENTATYWNEGO zamówienia
(pokrywającego dziś — przyszłe przedłużenie nie przejmuje wiersza).

Bramka po client_id (app/services/ezdrowie.py) — testy monkeypatchują
EZDROWIE_CLIENT_ID na świeżo utworzonego klienta, żeby nie zderzać się
z realnym id=115.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.contract import Contract, ContractStatus

pytestmark = pytest.mark.asyncio


async def _seed(client_status: ContractStatus = ContractStatus.active):
    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"EZ Part Client {suffix}")
        cand = Candidate(name=f"Part {suffix}", lastname=f"Tester{suffix}")
        db.add_all([client, cand])
        await db.flush()
        contract = Contract(
            candidate_id=cand.id,
            client_id=client.id,
            start_date=date.today() - timedelta(days=30),
            rate_client=15000,
            rate_candidate=12000,
            status=client_status,
        )
        db.add(contract)
        await db.flush()
        ids = (client.id, cand.id, contract.id)
        await db.commit()
        return ids


async def _cleanup(client_id: int, cand_id: int) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            ClientOrder.__table__.delete().where(ClientOrder.client_id == client_id)
        )
        await db.execute(
            Contract.__table__.delete().where(Contract.client_id == client_id)
        )
        await db.execute(Client.__table__.delete().where(Client.id == client_id))
        await db.execute(Candidate.__table__.delete().where(Candidate.id == cand_id))
        await db.commit()


async def test_flow_a_requires_part_for_ezdrowie(
    app_client: AsyncClient, app_auth_headers: dict[str, str], monkeypatch
):
    client_id, cand_id, contract_id = await _seed()
    monkeypatch.setattr("app.services.ezdrowie.EZDROWIE_CLIENT_ID", client_id)
    try:
        base = {
            "contract_id": str(contract_id),
            "title": "Przedłużenie e-Zdrowie",
            "order_status": "active",
        }
        # Bez części → 422 z komunikatem z ticketa.
        resp = await app_client.post(
            f"/api/clients/{client_id}/orders", data=base, headers=app_auth_headers
        )
        assert resp.status_code == 422, resp.text
        assert "Wybierz część umowy" in resp.text

        # Z częścią → 201 i part w odpowiedzi.
        resp = await app_client.post(
            f"/api/clients/{client_id}/orders",
            data={**base, "project_part": "cz2"},
            headers=app_auth_headers,
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["project_part"] == "cz2"

        # Wartość spoza słownika (cz.3 celowo nie istnieje) → 422.
        resp = await app_client.post(
            f"/api/clients/{client_id}/orders",
            data={**base, "project_part": "cz3"},
            headers=app_auth_headers,
        )
        assert resp.status_code == 422
    finally:
        await _cleanup(client_id, cand_id)


async def test_flow_a_forbids_part_for_other_clients(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    # EZDROWIE_CLIENT_ID zostaje na realnym 115 — świeży klient nim nie jest.
    client_id, cand_id, contract_id = await _seed()
    try:
        base = {
            "contract_id": str(contract_id),
            "title": "Zwykłe przedłużenie",
            "order_status": "active",
        }
        resp = await app_client.post(
            f"/api/clients/{client_id}/orders",
            data={**base, "project_part": "cz2"},
            headers=app_auth_headers,
        )
        assert resp.status_code == 422
        assert "wyłącznie Centrum e-Zdrowia" in resp.text

        resp = await app_client.post(
            f"/api/clients/{client_id}/orders", data=base, headers=app_auth_headers
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["project_part"] is None
    finally:
        await _cleanup(client_id, cand_id)


async def test_patch_updates_part_and_profile_uses_current_order(
    app_client: AsyncClient, app_auth_headers: dict[str, str], monkeypatch
):
    client_id, cand_id, contract_id = await _seed()
    monkeypatch.setattr("app.services.ezdrowie.EZDROWIE_CLIENT_ID", client_id)
    try:
        today = date.today()
        async with AsyncSessionLocal() as db:
            db.add_all(
                [
                    # Bieżące (rozpoczęte) zamówienie — cz2.
                    ClientOrder(
                        client_id=client_id,
                        contract_id=contract_id,
                        title="Q bieżące",
                        status=ClientOrderStatus.active,
                        start_date=today - timedelta(days=10),
                        project_part="cz2",
                    ),
                    # Przyszłe przedłużenie — cz4 (NIE może przejąć wiersza).
                    ClientOrder(
                        client_id=client_id,
                        contract_id=contract_id,
                        title="Q przyszłe",
                        status=ClientOrderStatus.active,
                        start_date=today + timedelta(days=20),
                        project_part="cz4",
                    ),
                ]
            )
            await db.commit()

        profile = await app_client.get(
            f"/api/clients/{client_id}/profile", headers=app_auth_headers
        )
        assert profile.status_code == 200, profile.text
        consultants = profile.json()["active_consultants"]
        assert len(consultants) == 1
        # Reprezentant = zamówienie pokrywające DZIŚ, nie przyszłe.
        assert consultants[0]["project_part"] == "cz2"

        # Edycja części bieżącego zamówienia natychmiast przestawia profil.
        async with AsyncSessionLocal() as db:
            current_id = await db.scalar(
                select(ClientOrder.id).where(
                    ClientOrder.client_id == client_id,
                    ClientOrder.title == "Q bieżące",
                )
            )
        resp = await app_client.patch(
            f"/api/clients/{client_id}/orders/{current_id}",
            json={"project_part": "cz6"},
            headers=app_auth_headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["project_part"] == "cz6"

        profile = await app_client.get(
            f"/api/clients/{client_id}/profile", headers=app_auth_headers
        )
        assert profile.json()["active_consultants"][0]["project_part"] == "cz6"
    finally:
        await _cleanup(client_id, cand_id)
