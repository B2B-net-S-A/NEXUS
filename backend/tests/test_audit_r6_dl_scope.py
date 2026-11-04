"""Runda 6 audytu — zakres Delivery Leada po #1843 (DL-04, DL-05).

DL-04: stary id scalonego klienta przekierowuje (307) na klienta
kanonicznego ZANIM zadziała bramka portfela — wcześniej DL przypisany do
klienta kanonicznego dostawał 403 na starym linku. Przypisanie DL-a do
scalonego duplikatu liczy się jako przypisanie do klienta kanonicznego
(scalenie nie przepina ``delivery_lead_client_assignments``).

DL-05: odmowa zakresu mówi po polsku, a ``/api/clients-lookup`` z
``delivery_scope=true`` (pickery Kontraktów) zwraca DL-owi tylko portfel;
bez parametru lista zostaje org-wide (pickery rekrutacji).

Baza testowa jest wspólna — każdy test zakłada własnych klientów i konta.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import update

from app.core.database import AsyncSessionLocal
from app.models.client import Client
from app.services.access_scope import DL_CLIENT_OUT_OF_SCOPE_DETAIL
from tests.test_dl_client_scope import _client, _delivery_lead

pytestmark = pytest.mark.asyncio


async def _merge(source_id: int, target_id: int) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Client)
            .where(Client.id == source_id)
            .values(merged_into_client_id=target_id, hidden=True)
        )
        await db.commit()


async def test_merged_client_redirects_before_the_portfolio_gate(
    app_client: AsyncClient,
) -> None:
    canonical = await _client("Kanoniczny")
    duplicate = await _client("Duplikat")
    await _merge(duplicate, canonical)
    headers = await _delivery_lead(app_client, assigned_client_ids=(canonical,))

    for suffix in ("", "/profile"):
        response = await app_client.get(
            f"/api/clients/{duplicate}{suffix}",
            headers=headers,
            follow_redirects=False,
        )
        assert response.status_code == 307, response.text
        assert response.headers["location"].endswith(
            f"/api/clients/{canonical}{suffix}"
        )


async def test_assignment_on_merged_duplicate_counts_for_canonical(
    app_client: AsyncClient,
) -> None:
    canonical = await _client("Kanoniczny B")
    duplicate = await _client("Duplikat B")
    await _merge(duplicate, canonical)
    headers = await _delivery_lead(app_client, assigned_client_ids=(duplicate,))

    response = await app_client.get(f"/api/clients/{canonical}", headers=headers)
    assert response.status_code == 200, response.text


async def test_out_of_scope_refusal_is_polish(app_client: AsyncClient) -> None:
    own = await _client("Własny")
    foreign = await _client("Obcy")
    headers = await _delivery_lead(app_client, assigned_client_ids=(own,))

    response = await app_client.get(f"/api/clients/{foreign}", headers=headers)
    assert response.status_code == 403, response.text
    assert response.json()["detail"] == DL_CLIENT_OUT_OF_SCOPE_DETAIL
    assert DL_CLIENT_OUT_OF_SCOPE_DETAIL == "Ten klient jest poza Twoim portfelem."


async def test_clients_lookup_delivery_scope_narrows_only_on_request(
    app_client: AsyncClient,
) -> None:
    own = await _client(f"Lookup {uuid.uuid4().hex[:6]}")
    foreign = await _client(f"Lookup {uuid.uuid4().hex[:6]}")
    headers = await _delivery_lead(app_client, assigned_client_ids=(own,))

    scoped = await app_client.get(
        "/api/clients-lookup", params={"delivery_scope": "true"}, headers=headers
    )
    assert scoped.status_code == 200, scoped.text
    scoped_ids = {row["id"] for row in scoped.json()}
    assert own in scoped_ids
    assert foreign not in scoped_ids

    org = await app_client.get("/api/clients-lookup", headers=headers)
    assert org.status_code == 200, org.text
    assert {own, foreign} <= {row["id"] for row in org.json()}
