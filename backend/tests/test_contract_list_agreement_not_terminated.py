"""Lista kontraktów: filtr „Umowa nierozwiązana” (decyzja Artura 28.10.2026).

Na kopii produkcji z 22.10 69 z 73 zakończonych albo kończących się
kontraktów B2B nie miało zapisanego rozwiązania umowy. Filtr
``agreement_not_terminated`` zbiera je w rejestrze: typ B2B, status
„Zakończony” albo „Kończący się”, ``agreement_termination_mode`` puste.
Seedy niosą unikalny marker, a asercje idą przez ``?q=<marker>``.
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import timedelta

import pytest
from httpx import AsyncClient

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.contract import Contract, ContractStatus, ContractType
from tests.test_contractor_consolidation import (
    _role_headers,
    _seed_candidate,
    _seed_client,
    _seed_contract,
)

pytestmark = pytest.mark.asyncio


async def _seed(
    marker: str,
    first: str,
    *,
    status: ContractStatus,
    contract_type: ContractType = ContractType.b2b,
    terminated: bool = False,
    client_id: int | None = None,
) -> tuple[int, int]:
    cand = await _seed_candidate(
        marker, email=f"{first.lower()}-{marker.lower()}@example.com", first_name=first
    )
    cli = client_id or await _seed_client(f"Klient {first} {marker}")
    cid = await _seed_contract(cand, cli, status=status)
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, cid)
        contract.contract_type = contract_type
        if terminated:
            # Komplet albo nic — CHECK `ck_contracts_agreement_termination_coherence`.
            contract.agreement_termination_mode = "mutual_agreement"
            contract.agreement_termination_party = "company"
            contract.agreement_termination_signed_on = business_today()
            contract.agreement_last_day = business_today() + timedelta(days=10)
        await db.commit()
    return cid, cli


async def _seed_matrix(marker: str) -> dict[str, int]:
    ids: dict[str, int] = {}
    rows = [
        ("Ended", ContractStatus.ended, ContractType.b2b, False),
        ("Ending", ContractStatus.ending, ContractType.b2b, False),
        ("Signed", ContractStatus.ended, ContractType.b2b, True),
        ("Zlecenie", ContractStatus.ended, ContractType.uzlecenie, False),
        ("Active", ContractStatus.active, ContractType.b2b, False),
    ]
    for first, status, contract_type, terminated in rows:
        ids[first], ids[f"client:{first}"] = await _seed(
            marker,
            first,
            status=status,
            contract_type=contract_type,
            terminated=terminated,
        )
    return ids


async def _ids(app_client: AsyncClient, headers: dict, **params) -> set[int]:
    resp = await app_client.get(
        "/api/contracts", params={"page_size": 50, **params}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    return {row["id"] for row in resp.json()["items"]}


@pytest.mark.parametrize("grouped", ["true", "false"])
async def test_only_b2b_ended_or_ending_without_termination(
    app_client: AsyncClient, app_auth_headers: dict, grouped: str
):
    marker = f"Ant{uuid.uuid4().hex[:6]}"
    ids = await _seed_matrix(marker)

    found = await _ids(
        app_client,
        app_auth_headers,
        q=marker,
        group_by_candidate=grouped,
        agreement_not_terminated="true",
    )
    # Umowa zlecenie, rozwiązana umowa B2B i aktywny projekt wypadają.
    assert found == {ids["Ended"], ids["Ending"]}

    # Bez filtra wszystkie pięć jest na liście (kontrola seedów).
    assert len(await _ids(app_client, app_auth_headers, q=marker)) == 5


async def test_combines_with_status_filter(
    app_client: AsyncClient, app_auth_headers: dict
):
    marker = f"Ans{uuid.uuid4().hex[:6]}"
    ids = await _seed_matrix(marker)

    ended_only = await _ids(
        app_client,
        app_auth_headers,
        q=marker,
        status="ended",
        agreement_not_terminated="true",
    )
    assert ended_only == {ids["Ended"]}
    # Status spoza zbioru filtra daje pustą listę, nie ignoruje filtra.
    assert (
        await _ids(
            app_client,
            app_auth_headers,
            q=marker,
            status="active",
            agreement_not_terminated="true",
        )
        == set()
    )


async def test_export_honours_filter(app_client: AsyncClient, app_auth_headers: dict):
    marker = f"Ane{uuid.uuid4().hex[:6]}"
    ids = await _seed_matrix(marker)
    resp = await app_client.get(
        "/api/contracts/export",
        params={"q": marker, "format": "csv", "agreement_not_terminated": "true"},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    rows = list(csv.reader(io.StringIO(resp.content.decode("utf-8-sig"))))
    exported = {int(row[0]) for row in rows[1:] if row and row[0].isdigit()}
    assert exported == {ids["Ended"], ids["Ending"]}


async def test_delivery_lead_sees_only_assigned_clients(app_client: AsyncClient):
    marker = f"And{uuid.uuid4().hex[:6]}"
    ids = await _seed_matrix(marker)
    headers = await _role_headers(
        app_client, "delivery_lead", assigned_client_id=ids["client:Ended"]
    )
    found = await _ids(app_client, headers, q=marker, agreement_not_terminated="true")
    assert found == {ids["Ended"]}


@pytest.mark.parametrize("role", ["recruiter", "head_of_recruitment"])
async def test_role_without_delivery_view_is_denied(app_client: AsyncClient, role: str):
    headers = await _role_headers(app_client, role)
    resp = await app_client.get(
        "/api/contracts",
        params={"agreement_not_terminated": "true"},
        headers=headers,
    )
    assert resp.status_code == 403, resp.text
