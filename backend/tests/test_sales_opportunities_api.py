"""Sprzedaż → Szanse (``/api/sales/opportunities``): zakładanie, ruch po etapach, opiekun."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.core.database import AsyncSessionLocal
from app.models.sales import SalesContact, SalesOpportunity
from tests.test_sales_companies_api import _headers, _user

COMPANIES = "/api/sales/companies"
URL = "/api/sales/opportunities"


async def _company(app_client, user) -> int:
    resp = await app_client.post(
        COMPANIES,
        json={"name": f"Szansa Firma {uuid.uuid4().hex[:8]}"},
        headers=_headers(user),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _stages(app_client, user) -> dict[str, int]:
    pipelines = (
        await app_client.get("/api/sales/pipelines", headers=_headers(user))
    ).json()
    sales = next(p for p in pipelines if p["key"] == "sales")
    return {stage["key"]: stage["id"] for stage in sales["stages"]}


@pytest.mark.asyncio
async def test_new_opportunity_lands_on_the_first_open_stage(app_client) -> None:
    rep = await _user("sales_edit")
    company_id = await _company(app_client, rep)
    resp = await app_client.post(
        URL,
        json={
            "company_id": company_id,
            "title": "  Zespół Java  ",
            "mrr_value": "40000",
            "one_off_value": "5000",
            "service_line": "bodyleasing",
            "roles": [{"title": "Java Developer", "count": 3, "skills": ["Java"]}],
        },
        headers=_headers(rep),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["title"] == "Zespół Java"
    assert body["stage"]["key"] == "lead"
    assert (body["status"], body["probability"]) == ("open", 5)
    assert Decimal(body["value"]) == Decimal("45000")
    assert Decimal(body["weighted_value"]) == Decimal("2250.00")
    assert body["owner"]["id"] == rep.id
    assert body["roles"][0]["count"] == 3

    company = (
        await app_client.get(f"{COMPANIES}/{company_id}", headers=_headers(rep))
    ).json()
    assert company["open_opportunities"] == 1


@pytest.mark.asyncio
async def test_move_through_qualification_to_lost_with_reason(app_client) -> None:
    rep = await _user("sales_edit")
    stages = await _stages(app_client, rep)
    company_id = await _company(app_client, rep)
    opp = (
        await app_client.post(
            URL, json={"company_id": company_id, "title": "Ruch"}, headers=_headers(rep)
        )
    ).json()

    moved = await app_client.post(
        f"{URL}/{opp['id']}/move",
        json={"stage_id": stages["offer-sent"]},
        headers=_headers(rep),
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["qualified_at"] is not None
    assert moved.json()["probability"] == 60

    lost = (
        await app_client.post(
            f"{URL}/{opp['id']}/move",
            json={"stage_id": stages["lost"], "lost_reason": "Wybrali konkurencję"},
            headers=_headers(rep),
        )
    ).json()
    assert (lost["status"], lost["lost_reason"]) == ("lost", "Wybrali konkurencję")
    assert lost["lost_at"] is not None
    assert lost["qualified_at"] == moved.json()["qualified_at"]

    reopened = (
        await app_client.post(
            f"{URL}/{opp['id']}/move",
            json={"stage_id": stages["lead"]},
            headers=_headers(rep),
        )
    ).json()
    assert (reopened["status"], reopened["lost_reason"]) == ("open", None)


@pytest.mark.asyncio
async def test_stage_from_another_pipeline_is_refused(app_client) -> None:
    rep = await _user("sales_edit")
    company_id = await _company(app_client, rep)
    opp = (
        await app_client.post(
            URL, json={"company_id": company_id, "title": "Obcy"}, headers=_headers(rep)
        )
    ).json()
    resp = await app_client.post(
        f"{URL}/{opp['id']}/move",
        json={"stage_id": 2_000_000_000},
        headers=_headers(rep),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_only_owner_or_admin_hands_the_opportunity_over(app_client) -> None:
    owner = await _user("sales_edit")
    other = await _user("sales_edit")
    company_id = await _company(app_client, owner)
    opp = (
        await app_client.post(
            URL,
            json={"company_id": company_id, "title": "Opieka"},
            headers=_headers(owner),
        )
    ).json()

    # Inny handlowiec może edytować (otwarta edycja, jak w Atlasie)…
    edited = await app_client.patch(
        f"{URL}/{opp['id']}", json={"campaign": "Jesień"}, headers=_headers(other)
    )
    assert edited.status_code == 200
    # …ale nie przejmie szansy.
    taken = await app_client.patch(
        f"{URL}/{opp['id']}",
        json={"owner_user_id": other.id},
        headers=_headers(other),
    )
    assert taken.status_code == 403
    handed = await app_client.patch(
        f"{URL}/{opp['id']}",
        json={"owner_user_id": other.id},
        headers=_headers(owner),
    )
    assert handed.json()["owner"]["id"] == other.id


@pytest.mark.asyncio
async def test_contacts_link_with_role_and_view_cannot_write(app_client) -> None:
    rep = await _user("sales_edit")
    viewer = await _user("sales_view")
    company_id = await _company(app_client, rep)
    async with AsyncSessionLocal() as db:
        contact = SalesContact(company_id=company_id, full_name="Anna Decydentka")
        db.add(contact)
        await db.commit()
        contact_id = contact.id
    opp = (
        await app_client.post(
            URL,
            json={
                "company_id": company_id,
                "title": "Kontakty",
                "primary_contact_id": contact_id,
            },
            headers=_headers(rep),
        )
    ).json()
    assert [c["id"] for c in opp["contacts"]] == [contact_id]

    linked = (
        await app_client.put(
            f"{URL}/{opp['id']}/contacts/{contact_id}",
            json={"role": "decision_maker"},
            headers=_headers(rep),
        )
    ).json()
    assert linked["contacts"][0]["role"] == "decision_maker"

    read = await app_client.get(f"{URL}/{opp['id']}", headers=_headers(viewer))
    assert read.status_code == 200
    denied = await app_client.post(
        f"{URL}/{opp['id']}/archive", headers=_headers(viewer)
    )
    assert denied.status_code == 403

    unlinked = (
        await app_client.delete(
            f"{URL}/{opp['id']}/contacts/{contact_id}", headers=_headers(rep)
        )
    ).json()
    assert unlinked["contacts"] == [] and unlinked["primary_contact_id"] is None


@pytest.mark.asyncio
async def test_editing_without_breakdown_keeps_the_value(app_client) -> None:
    """Szanse z Atlasa sprzed dealfin01 mają samo ``value`` — formularz edycji
    wysyła puste MRR i jednorazową, a wartość ma zostać."""
    rep = await _user("sales_edit")
    company_id = await _company(app_client, rep)
    opp = (
        await app_client.post(
            URL,
            json={"company_id": company_id, "title": "Stara", "value": "40000"},
            headers=_headers(rep),
        )
    ).json()
    assert Decimal(opp["value"]) == Decimal("40000")
    edited = (
        await app_client.patch(
            f"{URL}/{opp['id']}",
            json={
                "title": "Stara po edycji",
                "mrr_value": None,
                "one_off_value": None,
                "roles": [],
            },
            headers=_headers(rep),
        )
    ).json()
    assert Decimal(edited["value"]) == Decimal("40000")
    recomputed = (
        await app_client.patch(
            f"{URL}/{opp['id']}", json={"mrr_value": "30000"}, headers=_headers(rep)
        )
    ).json()
    assert Decimal(recomputed["value"]) == Decimal("30000")


async def _list(app_client, user, **params) -> set[int]:
    resp = await app_client.get(URL, params=params, headers=_headers(user))
    assert resp.status_code == 200, resp.text
    return {item["id"] for item in resp.json()["items"]}


async def _opportunity_id(app_client, user, company_id: int, **fields) -> int:
    resp = await app_client.post(
        URL,
        json={"company_id": company_id, "title": "Szansa", **fields},
        headers=_headers(user),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_search_finds_opportunity_by_company_nip_only_for_digits(
    app_client,
) -> None:
    rep = await _user("sales_edit")
    nip = str(uuid.uuid4().int)[:10]
    company = await app_client.post(
        COMPANIES,
        json={"name": f"Firma NIP {uuid.uuid4().hex[:8]}", "nip": nip},
        headers=_headers(rep),
    )
    assert company.status_code == 201, company.text
    opp = await _opportunity_id(app_client, rep, company.json()["id"])

    assert await _list(app_client, rep, q=nip) == {opp}
    # Z myślnikami, jak na fakturze.
    assert await _list(app_client, rep, q=f"{nip[:3]}-{nip[3:6]}-{nip[6:]}") == {opp}
    # Fraza z literami nie szuka po cyfrach NIP-u, bo „10CLOUDS” znajdowałoby „10”.
    assert opp not in await _list(app_client, rep, q=f"{nip[:4]}X")


@pytest.mark.asyncio
async def test_filters_by_model_and_created_day_in_company_calendar(app_client) -> None:
    rep = await _user("sales_edit")
    company_id = await _company(app_client, rep)
    core = await _opportunity_id(
        app_client, rep, company_id, service_line="core_solutions"
    )
    leasing = await _opportunity_id(
        app_client, rep, company_id, service_line="bodyleasing"
    )
    # 23:30 UTC 31.12 to już 01.01 w Warszawie.
    async with AsyncSessionLocal() as db:
        row = await db.get(SalesOpportunity, core)
        row.created_at = datetime(2025, 12, 31, 23, 30, tzinfo=timezone.utc)
        row = await db.get(SalesOpportunity, leasing)
        row.created_at = datetime(2025, 12, 31, 22, 30, tzinfo=timezone.utc)
        await db.commit()

    scope = {"company_id": company_id}
    assert await _list(app_client, rep, service_line="core_solutions", **scope) == {
        core
    }
    assert await _list(app_client, rep, created_from="2026-01-01", **scope) == {core}
    assert await _list(app_client, rep, created_to="2025-12-31", **scope) == {leasing}
    assert (
        await _list(
            app_client, rep, created_from="2026-01-02", created_to="2026-01-03", **scope
        )
        == set()
    )
    bad = await app_client.get(
        URL, params={"service_line": "nieznany"}, headers=_headers(rep)
    )
    assert bad.status_code == 422


@pytest.mark.asyncio
async def test_offers_only_lists_opportunities_on_the_offer_stage(app_client) -> None:
    rep = await _user("sales_edit")
    company_id = await _company(app_client, rep)
    stages = await _stages(app_client, rep)
    lead = await _opportunity_id(app_client, rep, company_id)
    sent = await _opportunity_id(app_client, rep, company_id)
    moved = await app_client.post(
        f"{URL}/{sent}/move",
        json={"stage_id": stages["offer-sent"]},
        headers=_headers(rep),
    )
    assert moved.status_code == 200, moved.text

    found = await _list(
        app_client, rep, company_id=company_id, offers_only="true", limit=2000
    )
    assert found == {sent}
    assert lead in await _list(app_client, rep, company_id=company_id)
