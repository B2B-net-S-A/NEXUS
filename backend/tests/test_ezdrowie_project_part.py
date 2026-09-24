"""„Część umowy" Centrum e-Zdrowia (ticket #3, Faza C) — po strukturze umów.

Kontrakt (od ticketu „Struktura umów wykonawczych", 09.2026): przy tworzeniu
zamówienia dla client_id e-Zdrowia (Flow A przedłużenie i Flow B nowy
kontraktor) wymagana jest UMOWA WYKONAWCZA, a ``project_part`` jest jej
pochodną z umowy ramowej; oba pola są zabronione u pozostałych klientów.
Profil wystawia część i umowę REPREZENTATYWNEGO zamówienia (pokrywającego
dziś — przyszłe przedłużenie nie przejmuje wiersza).

Bramka po client_id (app/services/ezdrowie.py) — testy monkeypatchują
EZDROWIE_CLIENT_ID na świeżo utworzonego klienta, żeby nie zderzać się
z realnym id=115.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_executive_contract import ClientExecutiveContract
from app.models.client_framework_contract import (
    ClientFrameworkContract,
    FrameworkContractStatus,
)
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.contract import Contract, ContractStatus
from app.core.scheduling import business_today

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
            start_date=business_today() - timedelta(days=30),
            rate_client=15000,
            rate_candidate=12000,
            status=client_status,
        )
        db.add(contract)
        await db.flush()
        ids = (client.id, cand.id, contract.id)
        await db.commit()
        return ids


async def _seed_structure(client_id: int, parts: tuple[str, ...]) -> dict[str, int]:
    """Umowa ramowa-część + jedna aktywna umowa wykonawcza na każdą część.

    Zwraca ``{część: id umowy wykonawczej}``. Numery zmyślone, unikalne per
    klient (UNIQUE ``(client_id, number)``).
    """
    suffix = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        ids: dict[str, int] = {}
        for part in parts:
            fc = ClientFrameworkContract(
                client_id=client_id,
                name=f"Ramowa {part} {suffix}",
                status=FrameworkContractStatus.active,
                project_part=part,
            )
            db.add(fc)
            await db.flush()
            ec = ClientExecutiveContract(
                client_id=client_id,
                framework_contract_id=fc.id,
                number=f"TEST/{part}/{suffix}",
                status="active",
            )
            db.add(ec)
            await db.flush()
            ids[part] = ec.id
        await db.commit()
        return ids


async def _cleanup(client_id: int, cand_id: int) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            ClientOrder.__table__.delete().where(ClientOrder.client_id == client_id)
        )
        await db.execute(
            ClientExecutiveContract.__table__.delete().where(
                ClientExecutiveContract.client_id == client_id
            )
        )
        await db.execute(
            ClientFrameworkContract.__table__.delete().where(
                ClientFrameworkContract.client_id == client_id
            )
        )
        await db.execute(
            Contract.__table__.delete().where(Contract.client_id == client_id)
        )
        await db.execute(Client.__table__.delete().where(Client.id == client_id))
        await db.execute(Candidate.__table__.delete().where(Candidate.id == cand_id))
        await db.commit()


async def test_flow_a_requires_executive_contract_for_ezdrowie(
    app_client: AsyncClient, app_auth_headers: dict[str, str], monkeypatch
):
    client_id, cand_id, contract_id = await _seed()
    monkeypatch.setattr("app.services.ezdrowie.EZDROWIE_CLIENT_ID", client_id)
    executives = await _seed_structure(client_id, ("cz2",))
    try:
        base = {
            "contract_id": str(contract_id),
            "title": "Przedłużenie e-Zdrowie",
            "order_status": "active",
        }
        # Bez umowy wykonawczej → 422; sama część już nie wystarcza.
        resp = await app_client.post(
            f"/api/clients/{client_id}/orders", data=base, headers=app_auth_headers
        )
        assert resp.status_code == 422, resp.text
        assert "Wybierz umowę wykonawczą" in resp.text
        resp = await app_client.post(
            f"/api/clients/{client_id}/orders",
            data={**base, "project_part": "cz2"},
            headers=app_auth_headers,
        )
        assert resp.status_code == 422, resp.text
        assert "Wybierz umowę wykonawczą" in resp.text

        # Z umową → 201; część POCHODNA z umowy ramowej, numer w odpowiedzi.
        resp = await app_client.post(
            f"/api/clients/{client_id}/orders",
            data={**base, "executive_contract_id": str(executives["cz2"])},
            headers=app_auth_headers,
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["project_part"] == "cz2"
        assert resp.json()["executive_contract_id"] == executives["cz2"]
        assert resp.json()["executive_contract_number"]

        # Jawna część niezgodna z umową → 422.
        resp = await app_client.post(
            f"/api/clients/{client_id}/orders",
            data={
                **base,
                "executive_contract_id": str(executives["cz2"]),
                "project_part": "cz4",
            },
            headers=app_auth_headers,
        )
        assert resp.status_code == 422, resp.text
        assert "nie zgadza się" in resp.text

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
            f"/api/clients/{client_id}/orders",
            data={**base, "executive_contract_id": "1"},
            headers=app_auth_headers,
        )
        assert resp.status_code == 422
        assert "wyłącznie Centrum e-Zdrowia" in resp.text

        resp = await app_client.post(
            f"/api/clients/{client_id}/orders", data=base, headers=app_auth_headers
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["project_part"] is None
        assert resp.json()["executive_contract_id"] is None
    finally:
        await _cleanup(client_id, cand_id)


async def test_flow_b_requires_executive_contract_and_forbids_for_others(
    app_client: AsyncClient, app_auth_headers: dict[str, str], monkeypatch
):
    """Flow B (atomic Contract+Order) idzie przez tę samą walidację co Flow A."""
    ez_client, ez_cand, _ = await _seed()
    other_client, other_cand, _ = await _seed()
    monkeypatch.setattr("app.services.ezdrowie.EZDROWIE_CLIENT_ID", ez_client)
    executives = await _seed_structure(ez_client, ("cz5",))
    try:

        def payload(cand_id: int, **extra):
            return {
                "candidate_id": cand_id,
                "title": "Nowy kontraktor",
                "contract_start_date": business_today().isoformat(),
                "order_start_date": business_today().isoformat(),
                # Admin musi podać obie stawki (admin_finance_fields_required).
                "rate_client": 16000,
                "rate_candidate": 12000,
                **extra,
            }

        # e-Zdrowie bez umowy wykonawczej → 422 (także z samą częścią).
        resp = await app_client.post(
            f"/api/clients/{ez_client}/contract-with-order",
            json=payload(ez_cand),
            headers=app_auth_headers,
        )
        assert resp.status_code == 422, resp.text
        assert "Wybierz umowę wykonawczą" in resp.text
        resp = await app_client.post(
            f"/api/clients/{ez_client}/contract-with-order",
            json=payload(ez_cand, project_part="cz5"),
            headers=app_auth_headers,
        )
        assert resp.status_code == 422, resp.text
        assert "Wybierz umowę wykonawczą" in resp.text

        # e-Zdrowie z umową → 201, część pochodna zapisana na Orderze.
        resp = await app_client.post(
            f"/api/clients/{ez_client}/contract-with-order",
            json=payload(ez_cand, executive_contract_id=executives["cz5"]),
            headers=app_auth_headers,
        )
        assert resp.status_code == 201, resp.text
        order_id = resp.json()["order_id"]
        async with AsyncSessionLocal() as db:
            saved = (
                await db.execute(
                    select(
                        ClientOrder.project_part, ClientOrder.executive_contract_id
                    ).where(ClientOrder.id == order_id)
                )
            ).one()
            assert tuple(saved) == ("cz5", executives["cz5"])

        # Inny klient z częścią albo umową → 422.
        resp = await app_client.post(
            f"/api/clients/{other_client}/contract-with-order",
            json=payload(other_cand, project_part="cz2"),
            headers=app_auth_headers,
        )
        assert resp.status_code == 422
        assert "wyłącznie Centrum e-Zdrowia" in resp.text
        resp = await app_client.post(
            f"/api/clients/{other_client}/contract-with-order",
            json=payload(other_cand, executive_contract_id=executives["cz5"]),
            headers=app_auth_headers,
        )
        assert resp.status_code == 422
        assert "wyłącznie Centrum e-Zdrowia" in resp.text
    finally:
        await _cleanup(ez_client, ez_cand)
        await _cleanup(other_client, other_cand)


async def test_patch_part_validation(
    app_client: AsyncClient, app_auth_headers: dict[str, str], monkeypatch
):
    """PATCH: wartość spoza słownika → 422; part u nie-e-Zdrowia → 422."""
    ez_client, ez_cand, ez_contract = await _seed()
    other_client, other_cand, other_contract = await _seed()
    monkeypatch.setattr("app.services.ezdrowie.EZDROWIE_CLIENT_ID", ez_client)
    try:
        async with AsyncSessionLocal() as db:
            ez_order = ClientOrder(
                client_id=ez_client,
                contract_id=ez_contract,
                title="EZ order",
                status=ClientOrderStatus.active,
            )
            other_order = ClientOrder(
                client_id=other_client,
                contract_id=other_contract,
                title="Other order",
                status=ClientOrderStatus.active,
            )
            db.add_all([ez_order, other_order])
            await db.flush()
            ez_order_id, other_order_id = ez_order.id, other_order.id
            await db.commit()

        # e-Zdrowie: cz3 nie istnieje → 422.
        resp = await app_client.patch(
            f"/api/clients/{ez_client}/orders/{ez_order_id}",
            json={"project_part": "cz3"},
            headers=app_auth_headers,
        )
        assert resp.status_code == 422

        # Nie-e-Zdrowie: PATCH z partem albo umową → 422 (pola zabronione).
        resp = await app_client.patch(
            f"/api/clients/{other_client}/orders/{other_order_id}",
            json={"project_part": "cz2"},
            headers=app_auth_headers,
        )
        assert resp.status_code == 422
        assert "wyłącznie Centrum e-Zdrowia" in resp.text
        resp = await app_client.patch(
            f"/api/clients/{other_client}/orders/{other_order_id}",
            json={"executive_contract_id": 1},
            headers=app_auth_headers,
        )
        assert resp.status_code == 422
        assert "wyłącznie Centrum e-Zdrowia" in resp.text
    finally:
        await _cleanup(ez_client, ez_cand)
        await _cleanup(other_client, other_cand)


async def test_patch_executive_contract_and_profile_uses_current_order(
    app_client: AsyncClient, app_auth_headers: dict[str, str], monkeypatch
):
    client_id, cand_id, contract_id = await _seed()
    monkeypatch.setattr("app.services.ezdrowie.EZDROWIE_CLIENT_ID", client_id)
    executives = await _seed_structure(client_id, ("cz2", "cz4", "cz6"))
    try:
        today = business_today()
        async with AsyncSessionLocal() as db:
            db.add_all(
                [
                    # Bieżące (rozpoczęte) zamówienie — umowa pod cz2.
                    ClientOrder(
                        client_id=client_id,
                        contract_id=contract_id,
                        title="Q bieżące",
                        status=ClientOrderStatus.active,
                        start_date=today - timedelta(days=10),
                        project_part="cz2",
                        executive_contract_id=executives["cz2"],
                    ),
                    # Przyszłe przedłużenie — cz4 (NIE może przejąć wiersza).
                    ClientOrder(
                        client_id=client_id,
                        contract_id=contract_id,
                        title="Q przyszłe",
                        status=ClientOrderStatus.active,
                        start_date=today + timedelta(days=20),
                        project_part="cz4",
                        executive_contract_id=executives["cz4"],
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
        assert consultants[0]["executive_contract"]["id"] == executives["cz2"]

        # Przepięcie umowy na bieżącym zamówieniu przestawia część pochodną
        # i profil; sama część (bez umowy) niezgodna z umową → 422.
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
        assert resp.status_code == 422, resp.text
        assert "nie zgadza się" in resp.text

        resp = await app_client.patch(
            f"/api/clients/{client_id}/orders/{current_id}",
            json={"executive_contract_id": executives["cz6"]},
            headers=app_auth_headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["project_part"] == "cz6"
        assert resp.json()["executive_contract_id"] == executives["cz6"]

        profile = await app_client.get(
            f"/api/clients/{client_id}/profile", headers=app_auth_headers
        )
        row = profile.json()["active_consultants"][0]
        assert row["project_part"] == "cz6"
        assert row["executive_contract"]["id"] == executives["cz6"]

        # Jawne `null` czyści oba pola — wiersz wraca do przeglądu.
        resp = await app_client.patch(
            f"/api/clients/{client_id}/orders/{current_id}",
            json={"executive_contract_id": None},
            headers=app_auth_headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["project_part"] is None
        assert resp.json()["executive_contract_id"] is None
    finally:
        await _cleanup(client_id, cand_id)
