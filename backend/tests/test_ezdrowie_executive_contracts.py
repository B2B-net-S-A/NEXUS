"""Struktura umów wykonawczych Centrum e-Zdrowia (ticket 09.2026).

Kontrakt: umowa ramowa-część → 0..N umów wykonawczych; konsultant przypisany
do KONKRETNEJ umowy wykonawczej na reprezentatywnym zamówieniu kontraktu;
ekran przeglądu pokazuje obecnych i planowanych bez przypisania; funkcja
działa wyłącznie dla klienta e-Zdrowia (bramka po ``client_id``).

Dane zmyślone. Bramka jest monkeypatchowana na świeżego klienta jak
w ``test_ezdrowie_project_part.py`` (autouse w conftest pinuje ją na -1,
a ``monkeypatch.setattr`` testu wykonuje się później).
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
from app.models.client_order_group import ClientOrderGroup
from app.models.contract import Contract, ContractStatus
from app.core.scheduling import business_today

pytestmark = pytest.mark.asyncio

EZDROWIE_GATE = "app.services.ezdrowie.EZDROWIE_CLIENT_ID"


async def _seed(*, with_contract: bool = True) -> dict:
    """Klient + kandydat (+ kontrakt) + ramowe cz2/cz4 (+ jedna bez części)
    + wykonawcze: aktywna pod cz2, zakończona pod cz2."""
    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"EZ Struct Client {suffix}")
        cand = Candidate(name=f"Struct {suffix}", lastname=f"Tester{suffix}")
        db.add_all([client, cand])
        await db.flush()
        fc_cz2 = ClientFrameworkContract(
            client_id=client.id,
            name=f"Ramowa cz. II {suffix}",
            status=FrameworkContractStatus.active,
            project_part="cz2",
        )
        fc_cz4 = ClientFrameworkContract(
            client_id=client.id,
            name=f"Ramowa cz. IV {suffix}",
            status=FrameworkContractStatus.active,
            project_part="cz4",
        )
        fc_plain = ClientFrameworkContract(
            client_id=client.id,
            name=f"MSA bez części {suffix}",
            status=FrameworkContractStatus.active,
        )
        db.add_all([fc_cz2, fc_cz4, fc_plain])
        await db.flush()
        ec_active = ClientExecutiveContract(
            client_id=client.id,
            framework_contract_id=fc_cz2.id,
            number=f"TEST/EC/A/{suffix}",
            status="active",
        )
        ec_ended = ClientExecutiveContract(
            client_id=client.id,
            framework_contract_id=fc_cz2.id,
            number=f"TEST/EC/E/{suffix}",
            status="ended",
        )
        db.add_all([ec_active, ec_ended])
        await db.flush()
        contract_id = None
        if with_contract:
            contract = Contract(
                candidate_id=cand.id,
                client_id=client.id,
                start_date=business_today() - timedelta(days=30),
                rate_client=15000,
                rate_candidate=12000,
                status=ContractStatus.active,
            )
            db.add(contract)
            await db.flush()
            contract_id = contract.id
        seeded = {
            "client_id": client.id,
            "cand_id": cand.id,
            "contract_id": contract_id,
            "fc_cz2": fc_cz2.id,
            "fc_cz4": fc_cz4.id,
            "fc_plain": fc_plain.id,
            "ec_active": ec_active.id,
            "ec_active_number": ec_active.number,
            "ec_ended": ec_ended.id,
        }
        await db.commit()
        return seeded


async def _cleanup(seeded: dict) -> None:
    client_id, cand_id = seeded["client_id"], seeded["cand_id"]
    async with AsyncSessionLocal() as db:
        await db.execute(
            ClientOrder.__table__.delete().where(ClientOrder.client_id == client_id)
        )
        await db.execute(
            ClientOrderGroup.__table__.delete().where(
                ClientOrderGroup.client_id == client_id
            )
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


async def _add_order(
    seeded: dict,
    *,
    title: str,
    start_delta_days: int,
    project_part: str | None = None,
    executive_contract_id: int | None = None,
    status: ClientOrderStatus = ClientOrderStatus.active,
) -> int:
    async with AsyncSessionLocal() as db:
        order = ClientOrder(
            client_id=seeded["client_id"],
            contract_id=seeded["contract_id"],
            title=title,
            status=status,
            start_date=business_today() + timedelta(days=start_delta_days),
            project_part=project_part,
            executive_contract_id=executive_contract_id,
        )
        db.add(order)
        await db.flush()
        order_id = order.id
        await db.commit()
        return order_id


async def _order_assignment(order_id: int) -> tuple[int | None, str | None]:
    async with AsyncSessionLocal() as db:
        row = (
            await db.execute(
                select(
                    ClientOrder.executive_contract_id, ClientOrder.project_part
                ).where(ClientOrder.id == order_id)
            )
        ).one()
        return row[0], row[1]


async def test_structure_is_only_for_ezdrowie(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    # Bramka zostaje na -1 (conftest) — świeży klient NIE jest e-Zdrowiem.
    seeded = await _seed()
    client_id = seeded["client_id"]
    try:
        resp = await app_client.get(
            f"/api/clients/{client_id}/contract-structure", headers=app_auth_headers
        )
        assert resp.status_code == 422, resp.text
        assert "wyłącznie Centrum e-Zdrowia" in resp.text

        resp = await app_client.get(
            f"/api/clients/{client_id}/executive-contracts/review",
            headers=app_auth_headers,
        )
        assert resp.status_code == 422

        resp = await app_client.get(
            "/api/clients/99999999/contract-structure", headers=app_auth_headers
        )
        assert resp.status_code == 404
    finally:
        await _cleanup(seeded)


async def test_structure_lists_parts_in_dictionary_order(
    app_client: AsyncClient, app_auth_headers: dict[str, str], monkeypatch
):
    seeded = await _seed()
    client_id = seeded["client_id"]
    monkeypatch.setattr(EZDROWIE_GATE, client_id)
    try:
        resp = await app_client.get(
            f"/api/clients/{client_id}/contract-structure", headers=app_auth_headers
        )
        assert resp.status_code == 200, resp.text
        parts = resp.json()["framework_contracts"]
        # Umowa ramowa BEZ części nie jest częścią struktury.
        assert [p["project_part"] for p in parts] == ["cz2", "cz4"]
        cz2 = parts[0]
        numbers = {ec["number"]: ec for ec in cz2["executive_contracts"]}
        assert seeded["ec_active_number"] in numbers
        # Wszystkie statusy są widoczne (zakończona też), bez przypisań.
        assert numbers[seeded["ec_active_number"]]["consultants_count"] == 0
        assert {ec["status"] for ec in cz2["executive_contracts"]} == {
            "active",
            "ended",
        }
        assert parts[1]["executive_contracts"] == []
    finally:
        await _cleanup(seeded)


async def test_create_executive_contract(
    app_client: AsyncClient, app_auth_headers: dict[str, str], monkeypatch
):
    seeded = await _seed()
    client_id = seeded["client_id"]
    monkeypatch.setattr(EZDROWIE_GATE, client_id)
    number = f"TEST/EC/NEW/{uuid.uuid4().hex[:6]}"
    try:
        resp = await app_client.post(
            f"/api/clients/{client_id}/executive-contracts",
            json={"framework_contract_id": seeded["fc_cz4"], "number": f" {number} "},
            headers=app_auth_headers,
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["status"] == "active"
        assert body["number"] == number
        assert body["project_part"] == "cz4"
        assert body["framework_contract_id"] == seeded["fc_cz4"]

        # Duplikat numeru u tego klienta → 409, nie 500 bez CORS.
        resp = await app_client.post(
            f"/api/clients/{client_id}/executive-contracts",
            json={"framework_contract_id": seeded["fc_cz2"], "number": number},
            headers=app_auth_headers,
        )
        assert resp.status_code == 409, resp.text
        assert "już istnieje" in resp.text

        # Umowa ramowa bez części nie przyjmuje umowy wykonawczej.
        resp = await app_client.post(
            f"/api/clients/{client_id}/executive-contracts",
            json={"framework_contract_id": seeded["fc_plain"], "number": "TEST/X"},
            headers=app_auth_headers,
        )
        assert resp.status_code == 422, resp.text
        assert "nie jest częścią" in resp.text

        # Nowa umowa jest od razu w strukturze pod cz4.
        resp = await app_client.get(
            f"/api/clients/{client_id}/contract-structure", headers=app_auth_headers
        )
        cz4 = resp.json()["framework_contracts"][1]
        assert [ec["number"] for ec in cz4["executive_contracts"]] == [number]
    finally:
        await _cleanup(seeded)


async def test_review_then_assign_updates_representative_order_and_profile(
    app_client: AsyncClient, app_auth_headers: dict[str, str], monkeypatch
):
    seeded = await _seed()
    client_id, contract_id = seeded["client_id"], seeded["contract_id"]
    monkeypatch.setattr(EZDROWIE_GATE, client_id)
    order_id = await _add_order(
        seeded,
        title="Szkic cz2",
        start_delta_days=-10,
        project_part="cz2",
        status=ClientOrderStatus.draft,
    )
    try:
        resp = await app_client.get(
            f"/api/clients/{client_id}/executive-contracts/review",
            headers=app_auth_headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total"] == 1
        row = body["rows"][0]
        assert row["contract_id"] == contract_id
        assert row["bucket"] == "active"
        assert row["legacy_project_part"] == "cz2"
        assert row["representative_order_id"] == order_id
        # Podpowiedź to WYŁĄCZNIE umowa ramowa części — żadnej umowy wykonawczej.
        assert row["suggested_framework_contract_id"] == seeded["fc_cz2"]
        assert "executive_contract_id" not in row

        resp = await app_client.post(
            f"/api/clients/{client_id}/executive-contracts/assignments",
            json={
                "contract_id": contract_id,
                "executive_contract_id": seeded["ec_active"],
            },
            headers=app_auth_headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["order_id"] == order_id
        assert body["created_draft"] is False
        assert body["executive_contract"]["number"] == seeded["ec_active_number"]
        assert body["executive_contract"]["project_part"] == "cz2"

        assert await _order_assignment(order_id) == (seeded["ec_active"], "cz2")

        # Po przypisaniu wiersz znika z przeglądu…
        resp = await app_client.get(
            f"/api/clients/{client_id}/executive-contracts/review",
            headers=app_auth_headers,
        )
        assert resp.json()["total"] == 0

        # …struktura liczy kontrakt…
        resp = await app_client.get(
            f"/api/clients/{client_id}/contract-structure", headers=app_auth_headers
        )
        cz2 = resp.json()["framework_contracts"][0]
        counts = {
            ec["number"]: ec["consultants_count"] for ec in cz2["executive_contracts"]
        }
        assert counts[seeded["ec_active_number"]] == 1

        # …a profil pokazuje numer umowy na wierszu konsultanta.
        resp = await app_client.get(
            f"/api/clients/{client_id}/profile", headers=app_auth_headers
        )
        assert resp.status_code == 200, resp.text
        consultants = resp.json()["active_consultants"]
        assert len(consultants) == 1
        assert (
            consultants[0]["executive_contract"]["number"]
            == (seeded["ec_active_number"])
        )
        assert consultants[0]["project_part"] == "cz2"

        # Pojedyncze zamówienie niesie numer umowy wykonawczej.
        resp = await app_client.get(
            f"/api/clients/{client_id}/orders/{order_id}", headers=app_auth_headers
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["executive_contract_id"] == seeded["ec_active"]
        assert resp.json()["executive_contract_number"] == seeded["ec_active_number"]
    finally:
        await _cleanup(seeded)


async def test_assign_creates_draft_when_contract_has_no_order(
    app_client: AsyncClient, app_auth_headers: dict[str, str], monkeypatch
):
    seeded = await _seed()
    client_id, contract_id = seeded["client_id"], seeded["contract_id"]
    monkeypatch.setattr(EZDROWIE_GATE, client_id)
    try:
        resp = await app_client.get(
            f"/api/clients/{client_id}/executive-contracts/review",
            headers=app_auth_headers,
        )
        row = resp.json()["rows"][0]
        assert row["representative_order_id"] is None
        assert row["legacy_project_part"] is None
        assert row["suggested_framework_contract_id"] is None

        resp = await app_client.post(
            f"/api/clients/{client_id}/executive-contracts/assignments",
            json={
                "contract_id": contract_id,
                "executive_contract_id": seeded["ec_active"],
            },
            headers=app_auth_headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["created_draft"] is True
        order_id = resp.json()["order_id"]
        async with AsyncSessionLocal() as db:
            order = await db.get(ClientOrder, order_id)
            assert order is not None
            assert order.status == ClientOrderStatus.draft
            assert order.contract_id == contract_id
            assert order.title == seeded["ec_active_number"]
            assert order.executive_contract_id == seeded["ec_active"]
            assert order.project_part == "cz2"
    finally:
        await _cleanup(seeded)


async def test_future_extension_does_not_take_over_review_row(
    app_client: AsyncClient, app_auth_headers: dict[str, str], monkeypatch
):
    seeded = await _seed()
    client_id, contract_id = seeded["client_id"], seeded["contract_id"]
    monkeypatch.setattr(EZDROWIE_GATE, client_id)
    current_id = await _add_order(seeded, title="Bieżące", start_delta_days=-5)
    future_id = await _add_order(
        seeded,
        title="Przyszłe",
        start_delta_days=20,
        project_part="cz2",
        executive_contract_id=seeded["ec_active"],
    )
    try:
        # Reprezentant = zamówienie pokrywające DZIŚ — bez umowy, więc do przeglądu.
        resp = await app_client.get(
            f"/api/clients/{client_id}/executive-contracts/review",
            headers=app_auth_headers,
        )
        assert resp.json()["total"] == 1
        assert resp.json()["rows"][0]["representative_order_id"] == current_id

        resp = await app_client.post(
            f"/api/clients/{client_id}/executive-contracts/assignments",
            json={
                "contract_id": contract_id,
                "executive_contract_id": seeded["ec_active"],
            },
            headers=app_auth_headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["order_id"] == current_id
        assert await _order_assignment(current_id) == (seeded["ec_active"], "cz2")
        assert await _order_assignment(future_id) == (seeded["ec_active"], "cz2")
    finally:
        await _cleanup(seeded)


async def test_assignment_refuses_ended_contract_and_foreign_contract(
    app_client: AsyncClient, app_auth_headers: dict[str, str], monkeypatch
):
    seeded = await _seed()
    other = await _seed()
    client_id, contract_id = seeded["client_id"], seeded["contract_id"]
    monkeypatch.setattr(EZDROWIE_GATE, client_id)
    try:
        resp = await app_client.post(
            f"/api/clients/{client_id}/executive-contracts/assignments",
            json={
                "contract_id": contract_id,
                "executive_contract_id": seeded["ec_ended"],
            },
            headers=app_auth_headers,
        )
        assert resp.status_code == 422, resp.text
        assert "zakończona" in resp.text

        # Umowa wykonawcza innego klienta → 422 (nie istnieje u tego klienta).
        resp = await app_client.post(
            f"/api/clients/{client_id}/executive-contracts/assignments",
            json={
                "contract_id": contract_id,
                "executive_contract_id": other["ec_active"],
            },
            headers=app_auth_headers,
        )
        assert resp.status_code == 422, resp.text

        # Kontrakt innego klienta → 422.
        resp = await app_client.post(
            f"/api/clients/{client_id}/executive-contracts/assignments",
            json={
                "contract_id": other["contract_id"],
                "executive_contract_id": seeded["ec_active"],
            },
            headers=app_auth_headers,
        )
        assert resp.status_code == 422, resp.text
        assert "Kontrakt" in resp.text
    finally:
        await _cleanup(seeded)
        await _cleanup(other)


async def test_patch_ended_with_live_assignment_is_409(
    app_client: AsyncClient, app_auth_headers: dict[str, str], monkeypatch
):
    seeded = await _seed()
    client_id = seeded["client_id"]
    monkeypatch.setattr(EZDROWIE_GATE, client_id)
    await _add_order(
        seeded,
        title="Z umową",
        start_delta_days=-3,
        project_part="cz2",
        executive_contract_id=seeded["ec_active"],
    )
    try:
        resp = await app_client.patch(
            f"/api/clients/{client_id}/executive-contracts/{seeded['ec_active']}",
            json={"status": "ended"},
            headers=app_auth_headers,
        )
        assert resp.status_code == 409, resp.text
        assert "przypisanych" in resp.text

        # Notatka i numer bez zmiany statusu przechodzą.
        new_number = f"TEST/EC/R/{uuid.uuid4().hex[:6]}"
        resp = await app_client.patch(
            f"/api/clients/{client_id}/executive-contracts/{seeded['ec_active']}",
            json={"number": new_number, "notes": "aneks"},
            headers=app_auth_headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["number"] == new_number
        assert resp.json()["notes"] == "aneks"
        assert resp.json()["status"] == "active"

        # Zmiana numeru na numer innej umowy → 409.
        async with AsyncSessionLocal() as db:
            ended_number = await db.scalar(
                select(ClientExecutiveContract.number).where(
                    ClientExecutiveContract.id == seeded["ec_ended"]
                )
            )
        resp = await app_client.patch(
            f"/api/clients/{client_id}/executive-contracts/{seeded['ec_active']}",
            json={"number": ended_number},
            headers=app_auth_headers,
        )
        assert resp.status_code == 409, resp.text

        # Umowa bez przypisań daje się zakończyć.
        resp = await app_client.patch(
            f"/api/clients/{client_id}/executive-contracts/{seeded['ec_ended']}",
            json={"status": "active"},
            headers=app_auth_headers,
        )
        assert resp.status_code == 200, resp.text
        resp = await app_client.patch(
            f"/api/clients/{client_id}/executive-contracts/{seeded['ec_ended']}",
            json={"status": "ended"},
            headers=app_auth_headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "ended"
    finally:
        await _cleanup(seeded)


async def _add_group_with_line(seeded: dict, *, executive_contract_id: int) -> int:
    """Karta MD pod umową wykonawczą z jedną aktywną linią kontraktu z seedu."""
    async with AsyncSessionLocal() as db:
        group = ClientOrderGroup(
            client_id=seeded["client_id"],
            order_number=f"MD/{uuid.uuid4().hex[:6]}",
            start_date=business_today() - timedelta(days=5),
            status="active",
            order_type="md",
            md_budget_mode="per_person",
            executive_contract_id=executive_contract_id,
        )
        db.add(group)
        await db.flush()
        line = ClientOrder(
            client_id=seeded["client_id"],
            contract_id=seeded["contract_id"],
            order_group_id=group.id,
            title="Linia karty",
            status=ClientOrderStatus.active,
            start_date=business_today() - timedelta(days=5),
            executive_contract_id=executive_contract_id,
            project_part="cz2",
        )
        db.add(line)
        await db.flush()
        line_id = line.id
        await db.commit()
        return line_id


async def test_live_md_card_blocks_ending_and_assignment_on_its_line(
    app_client: AsyncClient, app_auth_headers: dict[str, str], monkeypatch
):
    """Karta MD wskazuje umowę bezpośrednio: zakończenie → 409; przypisanie
    innej umowy na linii karty → 409 (linia dziedziczy umowę z karty)."""
    seeded = await _seed()
    client_id = seeded["client_id"]
    monkeypatch.setattr(EZDROWIE_GATE, client_id)
    await _add_group_with_line(seeded, executive_contract_id=seeded["ec_active"])
    try:
        resp = await app_client.patch(
            f"/api/clients/{client_id}/executive-contracts/{seeded['ec_active']}",
            json={"status": "ended"},
            headers=app_auth_headers,
        )
        assert resp.status_code == 409, resp.text
        assert "kart" in resp.text

        # Druga aktywna umowa pod cz4, próba przepięcia osoby z linii karty.
        created = await app_client.post(
            f"/api/clients/{client_id}/executive-contracts",
            json={
                "framework_contract_id": seeded["fc_cz4"],
                "number": f"TEST/EC/B/{uuid.uuid4().hex[:6]}",
            },
            headers=app_auth_headers,
        )
        assert created.status_code == 201, created.text
        resp = await app_client.post(
            f"/api/clients/{client_id}/executive-contracts/assignments",
            json={
                "contract_id": seeded["contract_id"],
                "executive_contract_id": created.json()["id"],
            },
            headers=app_auth_headers,
        )
        assert resp.status_code == 409, resp.text
        assert "karcie" in resp.text
    finally:
        await _cleanup(seeded)


async def test_patch_order_with_unchanged_assignment_ignores_ended_contract(
    app_client: AsyncClient, app_auth_headers: dict[str, str], monkeypatch
):
    """Formularz odsyła bieżącą umowę przy edycji notatki — umowa zakończona
    PO przypisaniu nie może wtedy dawać 422; zmiana NA zakończoną nadal 422;
    sama część bez umowy też 422."""
    seeded = await _seed()
    client_id = seeded["client_id"]
    monkeypatch.setattr(EZDROWIE_GATE, client_id)
    order_id = await _add_order(
        seeded,
        title="Na zakończonej",
        start_delta_days=-3,
        project_part="cz2",
        executive_contract_id=seeded["ec_ended"],
    )
    try:
        resp = await app_client.patch(
            f"/api/clients/{client_id}/orders/{order_id}",
            json={"notes": "edycja", "executive_contract_id": seeded["ec_ended"]},
            headers=app_auth_headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["executive_contract_id"] == seeded["ec_ended"]

        resp = await app_client.patch(
            f"/api/clients/{client_id}/orders/{order_id}",
            json={"executive_contract_id": seeded["ec_ended"], "project_part": "cz2"},
            headers=app_auth_headers,
        )
        assert resp.status_code == 422, resp.text

        resp = await app_client.patch(
            f"/api/clients/{client_id}/orders/{order_id}",
            json={"executive_contract_id": None, "project_part": "cz4"},
            headers=app_auth_headers,
        )
        assert resp.status_code == 422, resp.text
        assert "Wybierz umowę wykonawczą" in resp.text
    finally:
        await _cleanup(seeded)
