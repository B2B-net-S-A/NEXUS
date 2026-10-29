"""Sprzedaż → Leady: ręczny lead, klient NEXUSA poza sprzedażą, odrzucenie, zamiana na szansę."""

from __future__ import annotations

import uuid

import pytest

from app.core.database import AsyncSessionLocal
from app.models.client import Client
from tests.test_sales_companies_api import _headers, _user

URL = "/api/sales/leads"


@pytest.mark.asyncio
async def test_manual_lead_converts_into_company_and_opportunity(app_client) -> None:
    rep = await _user("sales_edit")
    tag = uuid.uuid4().hex[:8]
    created = await app_client.post(
        URL,
        json={"title": "Szukają 5 testerów", "company_name": f"Czapla Logistyka {tag}"},
        headers=_headers(rep),
    )
    assert created.status_code == 201, created.text
    lead = created.json()
    assert (lead["source"], lead["status"], lead["company_id"]) == (
        "manual",
        "new",
        None,
    )

    again = await app_client.post(
        URL,
        json={
            "title": "Szukają 5 testerów",
            "company_name": f"CZAPLA LOGISTYKA {tag} sp. z o.o.",
        },
        headers=_headers(rep),
    )
    assert again.json()["id"] == lead["id"]  # ten sam sygnał, nie drugi wiersz

    inbox = (await app_client.get(URL, params={"q": tag}, headers=_headers(rep))).json()
    assert [item["id"] for item in inbox["items"]] == [lead["id"]]

    converted = await app_client.post(
        f"{URL}/{lead['id']}/convert", json={}, headers=_headers(rep)
    )
    assert converted.status_code == 200, converted.text
    ids = converted.json()
    opp = (
        await app_client.get(
            f"/api/sales/opportunities/{ids['opportunity_id']}", headers=_headers(rep)
        )
    ).json()
    assert (opp["title"], opp["stage"]["key"], opp["owner"]["id"]) == (
        "Szukają 5 testerów",
        "lead",
        rep.id,
    )
    assert opp["company"]["name"] == f"Czapla Logistyka {tag}"
    # Zamiana leada to założenie szansy — w historii jak z formularza.
    events = (
        await app_client.get(
            f"/api/sales/opportunities/{ids['opportunity_id']}/history",
            headers=_headers(rep),
        )
    ).json()
    assert [(e["kind"], e["new_label"], e["user"]["id"]) for e in events] == [
        ("created", "Lead", rep.id)
    ]

    after = (await app_client.get(f"{URL}/{lead['id']}", headers=_headers(rep))).json()
    assert (after["status"], after["opportunity_id"]) == (
        "converted",
        ids["opportunity_id"],
    )
    twice = await app_client.post(
        f"{URL}/{lead['id']}/convert", json={}, headers=_headers(rep)
    )
    assert twice.json()["opportunity_id"] == ids["opportunity_id"]
    locked = await app_client.patch(
        f"{URL}/{lead['id']}", json={"status": "new"}, headers=_headers(rep)
    )
    assert locked.status_code == 409


@pytest.mark.asyncio
async def test_existing_client_goes_to_delivery_not_to_sales(app_client) -> None:
    rep = await _user("sales_edit")
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        db.add(Client(name=f"Bocian Bank {tag}"))
        await db.commit()
    resp = await app_client.post(
        URL,
        json={"title": "Nowy projekt", "company_name": f"Bocian Bank {tag} S.A."},
        headers=_headers(rep),
    )
    assert resp.status_code == 409
    assert "Delivery Lead" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_dismiss_keeps_reason_and_view_cannot_write(app_client) -> None:
    rep = await _user("sales_edit")
    viewer = await _user("sales_view")
    lead = (
        await app_client.post(
            URL,
            json={
                "title": "Post o rekrutacji",
                "company_name": f"Mewa {uuid.uuid4().hex[:6]}",
            },
            headers=_headers(rep),
        )
    ).json()
    denied = await app_client.patch(
        f"{URL}/{lead['id']}", json={"status": "dismissed"}, headers=_headers(viewer)
    )
    assert denied.status_code == 403
    dismissed = (
        await app_client.patch(
            f"{URL}/{lead['id']}",
            json={"status": "dismissed", "dismissed_reason": "To agencja"},
            headers=_headers(rep),
        )
    ).json()
    assert (dismissed["status"], dismissed["dismissed_reason"]) == (
        "dismissed",
        "To agencja",
    )
    inbox = (await app_client.get(URL, headers=_headers(viewer))).json()
    assert lead["id"] not in [item["id"] for item in inbox["items"]]
    assert inbox["counts"]["dismissed"] >= 1


@pytest.mark.asyncio
async def test_converted_lead_starts_dates_for_its_company(
    app_client, monkeypatch
) -> None:
    """D3: pierwsza szansa w firmie odpala daty — także ta z leada."""
    from app.services.sales import company_dates

    scheduled: list[int] = []
    monkeypatch.setattr(
        company_dates,
        "schedule_company_dates",
        lambda cid: scheduled.append(cid) or True,
    )
    rep = await _user("sales_edit")
    lead = (
        await app_client.post(
            URL,
            json={
                "title": "Zespół data",
                "company_name": f"Sowa Dane {uuid.uuid4().hex[:6]}",
            },
            headers=_headers(rep),
        )
    ).json()
    ids = (
        await app_client.post(
            f"{URL}/{lead['id']}/convert", json={}, headers=_headers(rep)
        )
    ).json()
    assert scheduled == [ids["company_id"]]
