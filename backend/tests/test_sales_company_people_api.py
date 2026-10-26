"""Sprzedaż → „Kogo znamy w firmie”: osoby z bazy z pełnym profilem i grupa kapitałowa."""

from __future__ import annotations

import uuid

import pytest

from app.core.database import AsyncSessionLocal
from app.models.client import Client
from app.models.contract import ContractStatus
from app.models.sales import SalesCompany
from app.services.company_names import normalize_company_name
from tests.test_integrations_companies_db import _candidate, _contract
from tests.test_sales_companies_api import _headers, _user

URL = "/api/sales/companies"


@pytest.mark.asyncio
async def test_panel_shows_people_with_contact_details_and_group_counts(
    app_client,
) -> None:
    viewer = await _user("sales_view")
    tag = uuid.uuid4().hex[:8]
    name = f"Pelikan Bank {tag}"
    child_name = f"Pelikan Leasing {tag}"
    async with AsyncSessionLocal() as db:
        client = Client(name=name)
        db.add(client)
        await db.flush()
        placed = await _candidate(db, f"Umieszczony{tag}")
        db.add(_contract(placed.id, client.id, ContractStatus.active))
        former = await _candidate(
            db,
            f"Byly{tag}",
            experience=[
                {"company": name, "role": "Analityk", "start": "2019", "end": "2022"}
            ],
        )
        leasing = await _candidate(
            db,
            f"Leasing{tag}",
            experience=[
                {"company": child_name, "role": "Tester", "start": "2023", "end": None}
            ],
        )
        parent = SalesCompany(name=name, normalized_name=normalize_company_name(name))
        db.add(parent)
        await db.flush()
        child = SalesCompany(
            name=child_name,
            normalized_name=normalize_company_name(child_name),
            parent_company_id=parent.id,
        )
        db.add(child)
        await db.commit()
        ids = (parent.id, child.id, client.id, placed.id, former.id, leasing.id)
    parent_id, child_id, client_id, placed_id, former_id, leasing_id = ids

    resp = await app_client.get(f"{URL}/{parent_id}/people", headers=_headers(viewer))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["matched_client"]["id"] == client_id
    by_id = {p["candidate_id"]: p for p in body["people"]}
    assert by_id[placed_id]["relationship"] == "via_us"
    assert by_id[former_id]["relationship"] == "past"
    # D4: handlowiec widzi pełny profil (kontakt), nie tylko imię i inicjał.
    assert by_id[former_id]["email"] == f"byly{tag}@example.com"
    assert leasing_id not in by_id
    assert body["group"] == [
        {
            "company": {"id": child_id, "name": child_name},
            "relation": "child",
            "counts": {"via_us": 0, "current": 1, "past": 0, "unknown": 0},
        }
    ]

    child_view = (
        await app_client.get(f"{URL}/{child_id}/people", headers=_headers(viewer))
    ).json()
    assert [g["relation"] for g in child_view["group"]] == ["parent"]


@pytest.mark.asyncio
async def test_panel_needs_sales_view(app_client) -> None:
    recruiter = await _user()
    resp = await app_client.get(f"{URL}/1/people", headers=_headers(recruiter))
    assert resp.status_code == 403
