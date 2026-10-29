"""Sprzedaż → historia zmian szansy (``GET /api/sales/opportunities/{id}/history``).

Jak „Historia zmian” deala w Atlasie: kto, kiedy, które pole, co było i co
jest. Zapis przy założeniu, ruchu po etapach, edycji, archiwum i scaleniu
firm; import z Atlasa nie zapisuje (pilnuje tego test importu).
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal
from app.models.sales import SalesOpportunityEvent
from tests.test_sales_companies_api import _headers, _user
from tests.test_sales_opportunities_api import COMPANIES, URL, _company, _stages


async def _opportunity(app_client, user, company_id: int, **extra) -> dict:
    resp = await app_client.post(
        URL,
        json={"company_id": company_id, "title": "Historia", **extra},
        headers=_headers(user),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _history(app_client, user, opportunity_id: int) -> list[dict]:
    resp = await app_client.get(
        f"{URL}/{opportunity_id}/history", headers=_headers(user)
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _changes(events: list[dict]) -> list[tuple]:
    return [(e["kind"], e["field"], e["old_value"], e["new_value"]) for e in events]


@pytest.mark.asyncio
async def test_move_records_stage_status_and_reason_with_author(app_client) -> None:
    rep = await _user("sales_edit")
    stages = await _stages(app_client, rep)
    company_id = await _company(app_client, rep)
    opp = await _opportunity(app_client, rep, company_id)

    created = await _history(app_client, rep, opp["id"])
    assert _changes(created) == [("created", "stage_id", None, str(stages["lead"]))]
    assert created[0]["new_label"] == "Lead"
    assert created[0]["user"]["id"] == rep.id

    await app_client.post(
        f"{URL}/{opp['id']}/move",
        json={"stage_id": stages["lost"], "lost_reason": "Wybrali konkurencję"},
        headers=_headers(rep),
    )
    # Ten sam etap drugi raz to nie zmiana.
    await app_client.post(
        f"{URL}/{opp['id']}/move",
        json={"stage_id": stages["lost"], "lost_reason": "Wybrali konkurencję"},
        headers=_headers(rep),
    )
    events = await _history(app_client, rep, opp["id"])
    moved = {e["field"]: e for e in events if e["kind"] == "updated"}
    assert set(moved) == {"stage_id", "status", "lost_reason"}
    assert (moved["stage_id"]["old_label"], moved["stage_id"]["new_value"]) == (
        "Lead",
        str(stages["lost"]),
    )
    assert (moved["status"]["old_value"], moved["status"]["new_value"]) == (
        "open",
        "lost",
    )
    assert moved["lost_reason"]["new_value"] == "Wybrali konkurencję"
    assert events[-1]["kind"] == "created"  # najnowsze na górze


@pytest.mark.asyncio
async def test_patch_records_only_tracked_fields_that_changed(app_client) -> None:
    owner = await _user("sales_edit")
    heir = await _user("sales_edit")
    company_id = await _company(app_client, owner)
    opp = await _opportunity(
        app_client, owner, company_id, mrr_value="40000", margin_pct="20"
    )

    resp = await app_client.patch(
        f"{URL}/{opp['id']}",
        json={
            "title": "Historia po zmianie",
            "mrr_value": "45000",
            "margin_pct": "20.00",  # ta sama marża — bez wpisu
            "expected_close_date": "2026-12-15",
            "campaign": "Jesień",  # pole spoza historii
            "owner_user_id": heir.id,
        },
        headers=_headers(owner),
    )
    assert resp.status_code == 200, resp.text
    events = await _history(app_client, owner, opp["id"])
    updated = {
        e["field"]: (e["old_value"], e["new_value"])
        for e in events
        if e["kind"] == "updated"
    }
    assert updated == {
        "title": ("Historia", "Historia po zmianie"),
        "value": ("40000", "45000"),
        "mrr_value": ("40000", "45000"),
        "expected_close_date": (None, "2026-12-15"),
        "owner_user_id": (str(owner.id), str(heir.id)),
    }
    handover = next(e for e in events if e["field"] == "owner_user_id")
    assert (handover["old_label"], handover["new_label"]) == (owner.name, heir.name)


@pytest.mark.asyncio
async def test_archive_and_restore_are_recorded(app_client) -> None:
    rep = await _user("sales_edit")
    company_id = await _company(app_client, rep)
    opp = await _opportunity(app_client, rep, company_id)
    await app_client.post(f"{URL}/{opp['id']}/archive", headers=_headers(rep))
    await app_client.post(f"{URL}/{opp['id']}/archive", headers=_headers(rep))
    await app_client.post(f"{URL}/{opp['id']}/restore", headers=_headers(rep))
    kinds = [e["kind"] for e in await _history(app_client, rep, opp["id"])]
    assert kinds == ["restored", "archived", "created"]


@pytest.mark.asyncio
async def test_company_merge_is_recorded_on_moved_opportunities(app_client) -> None:
    rep = await _user("sales_edit")
    tag = uuid.uuid4().hex[:8]
    target = (
        await app_client.post(
            COMPANIES, json={"name": f"Cel {tag}"}, headers=_headers(rep)
        )
    ).json()
    source = (
        await app_client.post(
            COMPANIES, json={"name": f"Źródło {tag}"}, headers=_headers(rep)
        )
    ).json()
    opp = await _opportunity(app_client, rep, source["id"])
    merged = await app_client.post(
        f"{COMPANIES}/{target['id']}/merge",
        json={"source_id": source["id"]},
        headers=_headers(rep),
    )
    assert merged.status_code == 200, merged.text

    event = (await _history(app_client, rep, opp["id"]))[0]
    assert (event["kind"], event["field"]) == ("company_merged", "company_id")
    assert (event["old_label"], event["new_label"]) == (
        f"Źródło {tag}",
        f"Cel {tag}",
    )
    assert event["user"]["id"] == rep.id


@pytest.mark.asyncio
async def test_history_needs_sales_view_and_404_for_unknown(app_client) -> None:
    rep = await _user("sales_edit")
    viewer = await _user("sales_view")
    outsider = await _user()
    company_id = await _company(app_client, rep)
    opp = await _opportunity(app_client, rep, company_id)

    assert len(await _history(app_client, viewer, opp["id"])) == 1
    denied = await app_client.get(
        f"{URL}/{opp['id']}/history", headers=_headers(outsider)
    )
    assert denied.status_code == 403
    missing = await app_client.get(f"{URL}/2000000000/history", headers=_headers(rep))
    assert missing.status_code == 404
    # Odmowa niczego nie zapisała.
    async with AsyncSessionLocal() as db:
        count = await db.scalar(
            select(func.count())
            .select_from(SalesOpportunityEvent)
            .where(SalesOpportunityEvent.opportunity_id == opp["id"])
        )
    assert count == 1
