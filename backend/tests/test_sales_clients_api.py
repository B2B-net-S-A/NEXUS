"""Sprzedaż ↔ Klienci: wybór klienta, powiązanie (jeden klient = jedna firma), zakładka."""

from __future__ import annotations

import uuid

import pytest

from app.core.database import AsyncSessionLocal
from app.models.client import Client
from tests.test_sales_companies_api import _headers, _user

URL = "/api/sales/clients"


@pytest.mark.asyncio
async def test_link_company_with_client_and_show_it_on_the_client_card(
    app_client,
) -> None:
    rep = await _user("sales_edit")
    viewer = await _user("sales_view")
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Żuraw Energia {tag}")
        db.add(client)
        await db.commit()
        client_id = client.id
    company = (
        await app_client.post(
            "/api/sales/companies", json={"name": f"Zuraw {tag}"}, headers=_headers(rep)
        )
    ).json()
    other = (
        await app_client.post(
            "/api/sales/companies", json={"name": f"Inna {tag}"}, headers=_headers(rep)
        )
    ).json()
    opp = (
        await app_client.post(
            "/api/sales/opportunities",
            json={"company_id": company["id"], "title": "Zespół"},
            headers=_headers(rep),
        )
    ).json()

    options = (
        await app_client.get(
            f"{URL}/options",
            params={"q": f"zuraw energia {tag}"},
            headers=_headers(rep),
        )
    ).json()
    assert options == [{"id": client_id, "name": f"Żuraw Energia {tag}"}]
    assert (
        await app_client.get(
            f"{URL}/options", params={"q": "zu"}, headers=_headers(viewer)
        )
    ).status_code == 403

    linked = await app_client.put(
        f"{URL}/link/{company['id']}",
        json={"client_id": client_id},
        headers=_headers(rep),
    )
    assert linked.json() == {"id": client_id, "name": f"Żuraw Energia {tag}"}
    card = (
        await app_client.get(
            f"/api/sales/companies/{company['id']}", headers=_headers(rep)
        )
    ).json()
    assert (card["client"]["id"], card["lifecycle_stage"]) == (client_id, "customer")

    taken = await app_client.put(
        f"{URL}/link/{other['id']}",
        json={"client_id": client_id},
        headers=_headers(rep),
    )
    assert taken.status_code == 409

    summary = (
        await app_client.get(f"{URL}/{client_id}/summary", headers=_headers(viewer))
    ).json()
    assert summary["company"]["id"] == company["id"]
    assert [o["id"] for o in summary["opportunities"]] == [opp["id"]]

    unlinked = await app_client.put(
        f"{URL}/link/{company['id']}", json={"client_id": None}, headers=_headers(rep)
    )
    assert unlinked.json() is None
    empty = (
        await app_client.get(f"{URL}/{client_id}/summary", headers=_headers(viewer))
    ).json()
    assert empty == {"company": None, "opportunities": []}


@pytest.mark.asyncio
async def test_client_search_ignores_the_legal_form_of_the_sales_name(
    app_client,
) -> None:
    """Firma w Sprzedaży „Kania S.A.”, klient w NEXUSIE „Kania” — ma się znaleźć."""
    rep = await _user("sales_edit")
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Kania{tag}")
        db.add(client)
        await db.commit()
        client_id = client.id
    found = (
        await app_client.get(
            f"{URL}/options", params={"q": f"Kania{tag} S.A."}, headers=_headers(rep)
        )
    ).json()
    assert [option["id"] for option in found] == [client_id]
