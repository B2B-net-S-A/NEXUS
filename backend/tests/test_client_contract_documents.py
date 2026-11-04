"""Ekran „Umowy klientów”: lista i pliki bez kwot i bez sekcji Delivery.

Decyzja Artura 04.11.2026: uprawnienie otwiera tylko te trasy. Odpowiedź nie ma
notatek ani warunków, a samo nadanie nie otwiera kontraktów ani starych tras umów.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest
from httpx import AsyncClient

from app.services import storage_service
from tests._permission_grants import grant_permissions

BASE = "/api/client-contract-documents"
PERMISSION = "client_contracts_view"


async def _account(
    app_client: AsyncClient, role: str, *, assigned_client_id: int | None = None
) -> tuple[int, dict[str, str]]:
    from app.core.database import AsyncSessionLocal
    from app.core.security import hash_password
    from app.models.team_structure import DeliveryLeadClientAssignment
    from app.models.user import User, UserRole

    email = f"ccd-{role}-{uuid.uuid4().hex[:8]}@example.com"
    password = f"P4ss_{uuid.uuid4().hex[:6]}!"
    async with AsyncSessionLocal() as db:
        user = User(
            email=email,
            password_hash=hash_password(password),
            name=f"Ccd {role}",
            role=UserRole(role),
            roles=[role],
            is_active=True,
        )
        db.add(user)
        await db.flush()
        if assigned_client_id is not None:
            db.add(
                DeliveryLeadClientAssignment(
                    delivery_lead_user_id=user.id, client_id=assigned_client_id
                )
            )
        await db.commit()
        user_id = user.id
    login = await app_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert login.status_code == 200, login.text
    return user_id, {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _seed_contract(*, deleted: bool = False) -> tuple[int, int, int]:
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client
    from app.models.client_contract_amendment import ClientContractAmendment
    from app.models.client_framework_contract import ClientFrameworkContract

    async with AsyncSessionLocal() as db:
        client = Client(
            name=f"CcdClient-{uuid.uuid4().hex[:6]}",
            deleted_at=datetime.now(timezone.utc) if deleted else None,
        )
        db.add(client)
        await db.flush()
        contract = ClientFrameworkContract(
            client_id=client.id,
            name="Umowa ramowa",
            effective_date=date(2026, 1, 1),
            notes="stawka 1500 zł za dzień",
            currency="PLN",
            filename="umowa.pdf",
            file_path="ccd/umowa.pdf",
            content_type="application/pdf",
        )
        db.add(contract)
        await db.flush()
        amendment = ClientContractAmendment(
            framework_contract_id=contract.id,
            name="Aneks 1",
            effective_date=date(2026, 6, 1),
            changes_summary="nowa stawka 1600 zł",
            filename="aneks.pdf",
            file_path="ccd/aneks.pdf",
            content_type="application/pdf",
        )
        db.add(amendment)
        await db.commit()
        return client.id, contract.id, amendment.id


@pytest.fixture
def stored_files(monkeypatch, tmp_path):
    contract_file = tmp_path / "umowa.pdf"
    contract_file.write_bytes(b"%PDF-umowa")
    amendment_file = tmp_path / "aneks.pdf"
    amendment_file.write_bytes(b"%PDF-aneks")
    monkeypatch.setattr(
        storage_service,
        "get_client_framework_contract_path",
        lambda _path: contract_file,
    )
    monkeypatch.setattr(
        storage_service,
        "get_client_contract_amendment_path",
        lambda _path: amendment_file,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role", ["employee", "recruiter", "delivery_lead", "finance", "user"]
)
async def test_without_the_permission_every_route_is_denied(
    app_client: AsyncClient, role: str
) -> None:
    _, contract_id, amendment_id = await _seed_contract()
    _, headers = await _account(app_client, role)

    for path in (
        BASE,
        f"{BASE}/{contract_id}/file",
        f"{BASE}/{contract_id}/amendments/{amendment_id}/file",
    ):
        response = await app_client.get(path, headers=headers)
        assert response.status_code == 403, path


@pytest.mark.asyncio
async def test_the_list_carries_documents_without_notes_or_terms(
    app_client: AsyncClient,
) -> None:
    client_id, contract_id, amendment_id = await _seed_contract()
    user_id, headers = await _account(app_client, "employee")
    await grant_permissions(user_id, PERMISSION)

    response = await app_client.get(BASE, headers=headers)

    assert response.status_code == 200, response.text
    row = next(item for item in response.json() if item["id"] == contract_id)
    assert row["client_id"] == client_id
    assert row["has_file"] is True
    assert set(row) == {
        "id",
        "client_id",
        "client_name",
        "name",
        "status",
        "effective_date",
        "expiry_date",
        "filename",
        "has_file",
        "amendments",
    }
    assert row["amendments"] == [
        {
            "id": amendment_id,
            "name": "Aneks 1",
            "effective_date": "2026-06-01",
            "filename": "aneks.pdf",
            "has_file": True,
        }
    ]
    assert "stawk" not in response.text


@pytest.mark.asyncio
async def test_the_holder_downloads_contract_and_amendment_files(
    app_client: AsyncClient, stored_files
) -> None:
    _, contract_id, amendment_id = await _seed_contract()
    user_id, headers = await _account(app_client, "employee")
    await grant_permissions(user_id, PERMISSION)

    contract = await app_client.get(f"{BASE}/{contract_id}/file", headers=headers)
    amendment = await app_client.get(
        f"{BASE}/{contract_id}/amendments/{amendment_id}/file", headers=headers
    )

    assert contract.status_code == 200
    assert contract.content == b"%PDF-umowa"
    assert amendment.status_code == 200
    assert amendment.content == b"%PDF-aneks"


@pytest.mark.asyncio
async def test_the_permission_does_not_open_delivery_or_amounts(
    app_client: AsyncClient,
) -> None:
    client_id, contract_id, amendment_id = await _seed_contract()
    user_id, headers = await _account(app_client, "employee")
    await grant_permissions(user_id, PERMISSION)

    for path in (
        f"/api/clients/{client_id}/framework-contracts",
        f"/api/clients/{client_id}/framework-contracts/{contract_id}",
        f"/api/clients/{client_id}/framework-contracts/{contract_id}/file",
        f"/api/clients/{client_id}/framework-contracts/{contract_id}"
        f"/amendments/{amendment_id}/text",
        f"/api/clients/{client_id}/contract-terms",
        "/api/contracts",
    ):
        response = await app_client.get(path, headers=headers)
        assert response.status_code == 403, path


@pytest.mark.asyncio
async def test_amendment_of_another_contract_and_missing_records_give_404(
    app_client: AsyncClient, stored_files
) -> None:
    _, contract_id, _ = await _seed_contract()
    _, other_contract_id, other_amendment_id = await _seed_contract()
    user_id, headers = await _account(app_client, "employee")
    await grant_permissions(user_id, PERMISSION)

    crossed = await app_client.get(
        f"{BASE}/{contract_id}/amendments/{other_amendment_id}/file", headers=headers
    )
    missing = await app_client.get(f"{BASE}/2147483000/file", headers=headers)

    assert crossed.status_code == 404
    assert missing.status_code == 404
    assert other_contract_id != contract_id


@pytest.mark.asyncio
async def test_a_deleted_client_disappears_from_list_and_files(
    app_client: AsyncClient, stored_files
) -> None:
    _, contract_id, _ = await _seed_contract(deleted=True)
    user_id, headers = await _account(app_client, "employee")
    await grant_permissions(user_id, PERMISSION)

    listing = await app_client.get(BASE, headers=headers)
    file_response = await app_client.get(f"{BASE}/{contract_id}/file", headers=headers)

    assert contract_id not in {row["id"] for row in listing.json()}
    assert file_response.status_code == 404


@pytest.mark.asyncio
async def test_delivery_lead_with_the_permission_stays_within_assigned_clients(
    app_client: AsyncClient, stored_files
) -> None:
    client_id, contract_id, _ = await _seed_contract()
    _, foreign_contract_id, _ = await _seed_contract()
    user_id, headers = await _account(
        app_client, "delivery_lead", assigned_client_id=client_id
    )
    await grant_permissions(user_id, PERMISSION)

    listing = await app_client.get(BASE, headers=headers)
    own = await app_client.get(f"{BASE}/{contract_id}/file", headers=headers)
    foreign = await app_client.get(
        f"{BASE}/{foreign_contract_id}/file", headers=headers
    )

    assert [row["id"] for row in listing.json()] == [contract_id]
    assert own.status_code == 200
    assert foreign.status_code == 403


@pytest.mark.asyncio
async def test_the_list_sorts_clients_regardless_of_letter_case(
    app_client: AsyncClient,
) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client
    from app.models.client_framework_contract import ClientFrameworkContract

    marker = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        for name in (f"bb{marker}", f"AA{marker}", f"CC{marker}"):
            client = Client(name=name)
            db.add(client)
            await db.flush()
            db.add(ClientFrameworkContract(client_id=client.id, name="Umowa"))
        await db.commit()
    user_id, headers = await _account(app_client, "employee")
    await grant_permissions(user_id, PERMISSION)

    response = await app_client.get(BASE, headers=headers)

    names = [row["client_name"] for row in response.json()]
    assert [name for name in names if name.endswith(marker)] == [
        f"AA{marker}",
        f"bb{marker}",
        f"CC{marker}",
    ]


@pytest.mark.asyncio
async def test_contract_of_a_merged_duplicate_shows_under_the_target_client(
    app_client: AsyncClient,
) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client
    from app.models.client_framework_contract import ClientFrameworkContract

    marker = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        target = Client(name=f"Firma S.A. {marker}")
        db.add(target)
        await db.flush()
        duplicate = Client(
            name=f"ZZ duplikat {marker}", merged_into_client_id=target.id
        )
        db.add(duplicate)
        await db.flush()
        own = ClientFrameworkContract(client_id=target.id, name=f"Własna {marker}")
        moved = ClientFrameworkContract(
            client_id=duplicate.id, name=f"Z duplikatu {marker}"
        )
        db.add_all([own, moved])
        await db.commit()
        target_id, target_name = target.id, target.name
    user_id, headers = await _account(app_client, "employee")
    await grant_permissions(user_id, PERMISSION)

    response = await app_client.get(BASE, headers=headers)

    rows = [row for row in response.json() if row["name"].endswith(marker)]
    assert len(rows) == 2
    assert {row["client_id"] for row in rows} == {target_id}
    assert {row["client_name"] for row in rows} == {target_name}


@pytest.mark.asyncio
async def test_a_file_missing_on_disk_is_a_404_not_a_server_error(
    app_client: AsyncClient, monkeypatch
) -> None:
    def missing(path: str):
        raise FileNotFoundError(path)

    monkeypatch.setattr(storage_service, "get_client_framework_contract_path", missing)
    monkeypatch.setattr(storage_service, "get_client_contract_amendment_path", missing)
    _, contract_id, amendment_id = await _seed_contract()
    user_id, headers = await _account(app_client, "employee")
    await grant_permissions(user_id, PERMISSION)

    contract = await app_client.get(f"{BASE}/{contract_id}/file", headers=headers)
    amendment = await app_client.get(
        f"{BASE}/{contract_id}/amendments/{amendment_id}/file", headers=headers
    )

    assert contract.status_code == 404
    assert amendment.status_code == 404
