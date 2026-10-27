"""Sprzedaż → Firmy (``/api/sales/companies``): bramki, duplikaty, wyszukiwanie, lejek.

Nazwy firm niosą losowy tag — baza testowa jest wspólna dla przebiegu.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token
from app.models.sales import SalesOpportunity, SalesPipeline, SalesPipelineStage
from app.models.user import User, UserRole
from tests._permission_grants import grant_permissions

URL = "/api/sales/companies"


def _headers(user: User) -> dict[str, str]:
    token = create_access_token(subject=user.id, role=user.role.value)
    return {"Authorization": f"Bearer {token}"}


async def _user(*grants: str, role: str = "recruiter") -> User:
    marker = uuid.uuid4().hex[:10]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"sales-{marker}@example.com",
            name=f"Handlowiec {marker}",
            role=UserRole(role),
            roles=[role],
            is_active=True,
            profile_completed=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
    if grants:
        await grant_permissions(user.id, *grants)
    return user


@pytest.mark.asyncio
async def test_without_sales_permission_the_section_is_closed(app_client) -> None:
    recruiter = await _user()
    resp = await app_client.get(URL, headers=_headers(recruiter))
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "permission_denied"


@pytest.mark.asyncio
async def test_view_reads_but_cannot_write(app_client) -> None:
    viewer = await _user("sales_view")
    assert (await app_client.get(URL, headers=_headers(viewer))).status_code == 200
    resp = await app_client.post(
        URL, json={"name": "Cokolwiek"}, headers=_headers(viewer)
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_create_warns_about_duplicate_name_or_nip(app_client) -> None:
    rep = await _user("sales_edit")
    tag = uuid.uuid4().hex[:8]
    digits = f"{uuid.uuid4().int % 10**10:010d}"
    spaced = f"PL {digits[:3]}-{digits[3:6]}-{digits[6:8]}-{digits[8:]}"
    first = await app_client.post(
        URL,
        json={"name": f"Kormoran {tag} S.A.", "nip": spaced},
        headers=_headers(rep),
    )
    assert first.status_code == 201, first.text
    body = first.json()
    assert body["nip"] == digits
    assert body["owner"]["id"] == rep.id
    assert body["open_opportunities"] == 0

    # Ta sama nazwa kanoniczna (bez formy prawnej) — ostrzeżenie, nie zapis.
    same_name = await app_client.post(
        URL, json={"name": f"KORMORAN {tag}"}, headers=_headers(rep)
    )
    assert same_name.status_code == 409
    detail = same_name.json()["detail"]
    assert detail["code"] == "sales_company_duplicate"
    assert [d["id"] for d in detail["duplicates"]] == [body["id"]]

    forced = await app_client.post(
        URL,
        json={"name": f"KORMORAN {tag}", "allow_duplicate": True},
        headers=_headers(rep),
    )
    assert forced.status_code == 201


@pytest.mark.asyncio
async def test_search_ignores_polish_letters_and_archived_companies(app_client) -> None:
    rep = await _user("sales_edit")
    tag = uuid.uuid4().hex[:8]
    created = await app_client.post(
        URL, json={"name": f"Żółw Logistyka {tag}"}, headers=_headers(rep)
    )
    company_id = created.json()["id"]

    found = await app_client.get(
        URL, params={"q": f"zolw logistyka {tag}"}, headers=_headers(rep)
    )
    assert [c["id"] for c in found.json()["items"]] == [company_id]

    archived = await app_client.post(
        f"{URL}/{company_id}/archive", headers=_headers(rep)
    )
    assert archived.json()["archived_at"] is not None
    hidden = await app_client.get(URL, params={"q": tag}, headers=_headers(rep))
    assert hidden.json()["total"] == 0
    shown = await app_client.get(
        URL, params={"q": tag, "archived": True}, headers=_headers(rep)
    )
    assert shown.json()["total"] == 1


@pytest.mark.asyncio
async def test_parent_company_must_exist_and_differ(app_client) -> None:
    rep = await _user("sales_edit")
    tag = uuid.uuid4().hex[:8]
    parent = (
        await app_client.post(
            URL, json={"name": f"mGrupa {tag}"}, headers=_headers(rep)
        )
    ).json()
    child = (
        await app_client.post(
            URL,
            json={"name": f"mLeasing {tag}", "parent_company_id": parent["id"]},
            headers=_headers(rep),
        )
    ).json()
    assert child["parent"] == {"id": parent["id"], "name": f"mGrupa {tag}"}

    self_parent = await app_client.patch(
        f"{URL}/{parent['id']}",
        json={"parent_company_id": parent["id"]},
        headers=_headers(rep),
    )
    assert self_parent.status_code == 422
    missing = await app_client.patch(
        f"{URL}/{parent['id']}",
        json={"parent_company_id": 2_000_000_000},
        headers=_headers(rep),
    )
    assert missing.status_code == 422


@pytest.mark.asyncio
async def test_open_pipeline_counts_only_open_unarchived_opportunities(
    app_client,
) -> None:
    rep = await _user("sales_edit")
    tag = uuid.uuid4().hex[:8]
    company = (
        await app_client.post(URL, json={"name": f"Lejek {tag}"}, headers=_headers(rep))
    ).json()
    async with AsyncSessionLocal() as db:
        pipeline = (
            await db.execute(select(SalesPipeline).where(SalesPipeline.key == "sales"))
        ).scalar_one()
        stage = (
            await db.execute(
                select(SalesPipelineStage).where(
                    SalesPipelineStage.pipeline_id == pipeline.id,
                    SalesPipelineStage.key == "lead",
                )
            )
        ).scalar_one()
        for title, value, status_ in (
            ("Otwarta A", "100000", "open"),
            ("Otwarta B", "50000.50", "open"),
            ("Wygrana", "999", "won"),
        ):
            db.add(
                SalesOpportunity(
                    company_id=company["id"],
                    pipeline_id=pipeline.id,
                    stage_id=stage.id,
                    title=title,
                    value=Decimal(value),
                    status=status_,
                )
            )
        await db.commit()

    got = (await app_client.get(f"{URL}/{company['id']}", headers=_headers(rep))).json()
    assert got["open_opportunities"] == 2
    assert Decimal(got["open_value"]) == Decimal("150000.50")


@pytest.mark.asyncio
async def test_registry_lookup_fills_the_form_without_network(
    app_client, monkeypatch
) -> None:
    from app.api import sales_companies

    seen: list[str] = []

    async def fake_lookup(nip=None, krs=None):
        seen.append(nip)
        if nip == "5260000000":
            return None
        return {
            "name": "BANK PRZYKŁADOWY SPÓŁKA AKCYJNA",
            "regon": "001234567",
            "krs": "0000012345",
            "address": "ul. Prosta 18, 00-850 WARSZAWA",
            "source": "biala_lista",
        }

    monkeypatch.setattr(sales_companies, "lookup_company", fake_lookup)
    rep = await _user("sales_edit")
    viewer = await _user("sales_view")
    ok = await app_client.get(
        f"{URL}/registry", params={"nip": "PL 111-222-33-44"}, headers=_headers(rep)
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["hq_city"] == "Warszawa"
    assert (ok.json()["nip"], ok.json()["krs"]) == ("1112223344", "0000012345")
    assert seen == ["1112223344"]
    missing = await app_client.get(
        f"{URL}/registry", params={"nip": "5260000000"}, headers=_headers(rep)
    )
    assert missing.status_code == 404
    bad = await app_client.get(
        f"{URL}/registry", params={"nip": "12345678901"}, headers=_headers(rep)
    )
    assert bad.status_code == 422
    denied = await app_client.get(
        f"{URL}/registry", params={"nip": "1112223344"}, headers=_headers(viewer)
    )
    assert denied.status_code == 403


@pytest.mark.asyncio
async def test_links_accept_only_http_and_fill_in_https(app_client) -> None:
    rep = await _user("sales_edit")
    tag = uuid.uuid4().hex[:8]
    bad = await app_client.post(
        URL,
        json={"name": f"Link {tag}", "website_url": "javascript:alert(1)"},
        headers=_headers(rep),
    )
    assert bad.status_code == 422
    ok = await app_client.post(
        URL,
        json={"name": f"Link {tag}", "website_url": "firma.example.com"},
        headers=_headers(rep),
    )
    assert ok.json()["website_url"] == "https://firma.example.com"
    lead = await app_client.post(
        "/api/sales/leads",
        json={
            "title": "Sygnał",
            "company_name": f"Link {tag}",
            "url": "data:text/html,x",
        },
        headers=_headers(rep),
    )
    assert lead.status_code == 422
