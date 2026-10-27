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
    assert "group" not in body  # grupa to osobne zapytanie (panel nie czeka)
    group = (
        await app_client.get(
            f"{URL}/{parent_id}/people/group", headers=_headers(viewer)
        )
    ).json()
    assert group == [
        {
            "company": {"id": child_id, "name": child_name},
            "relation": "child",
            "counts": {"via_us": 0, "current": 1, "past": 0, "unknown": 0},
        }
    ]

    child_group = (
        await app_client.get(f"{URL}/{child_id}/people/group", headers=_headers(viewer))
    ).json()
    assert [g["relation"] for g in child_group] == ["parent"]


@pytest.mark.asyncio
async def test_slow_subsidiary_does_not_break_the_group(
    app_client, monkeypatch
) -> None:
    """Limit czasu skanu jednej spółki → jej liczby „brak”, reszta grupy zostaje."""
    from fastapi import HTTPException

    from app.api import sales_company_people

    viewer = await _user("sales_view")
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        parent = SalesCompany(name=f"Grupa {tag}", normalized_name=f"grupa {tag}")
        db.add(parent)
        await db.flush()
        db.add_all(
            [
                SalesCompany(
                    name=f"Szybka {tag}",
                    normalized_name=f"szybka {tag}",
                    parent_company_id=parent.id,
                ),
                SalesCompany(
                    name=f"Wolna {tag}",
                    normalized_name=f"wolna {tag}",
                    parent_company_id=parent.id,
                ),
            ]
        )
        await db.commit()
        parent_id = parent.id

    real = sales_company_people._people_for

    async def flaky(db, company, *, limit):
        if company.name.startswith("Wolna"):
            raise HTTPException(503, detail={"error": "lookup_timeout"})
        return await real(db, company, limit=limit)

    monkeypatch.setattr(sales_company_people, "_people_for", flaky)
    group = (
        await app_client.get(
            f"{URL}/{parent_id}/people/group", headers=_headers(viewer)
        )
    ).json()
    by_name = {g["company"]["name"]: g["counts"] for g in group}
    assert by_name[f"Wolna {tag}"] is None
    assert by_name[f"Szybka {tag}"] == {
        "via_us": 0,
        "current": 0,
        "past": 0,
        "unknown": 0,
    }


@pytest.mark.asyncio
async def test_panel_needs_sales_view(app_client) -> None:
    recruiter = await _user()
    resp = await app_client.get(f"{URL}/1/people", headers=_headers(recruiter))
    assert resp.status_code == 403
