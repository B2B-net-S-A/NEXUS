"""Duplikaty w Dzwonieniu (zgłoszenie dzwoniących, decyzje Artura 23.11.2026).

Tabela ukrywa powtórki z kolejnych list (ten sam warunek co kolejka), a „To duplikat”
na karcie zapisuje przykład, którego bramki nie złapały.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.sales import SalesActivity
from app.services.sales.calling_repeats import DUPLICATE_SOURCE
from tests.test_sales_calling_queue import _campaign, _company, _record
from tests.test_sales_companies_api import _headers, _user

URL = "/api/sales/calling"


async def _table(app_client, user, **params) -> dict:
    resp = await app_client.get(f"{URL}/records", params=params, headers=_headers(user))
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_table_hides_repeats_unless_asked(app_client) -> None:
    caller = await _user("sales_view", "sales_edit")
    campaign_id = await _campaign()
    phone = f"7{uuid.uuid4().int % 10**8:08d}"
    called = await _record(
        caller.id, campaign_id, await _company(), state="call_back", phone=phone
    )
    # Ten sam numer z kolejnej listy, przy innej karcie firmy: powtórka.
    repeat = await _record(caller.id, campaign_id, await _company(), phone=phone)
    fresh = await _record(caller.id, campaign_id, await _company())

    hidden = await _table(app_client, caller)
    ids = [item["record_id"] for item in hidden["items"]]
    assert repeat not in ids and fresh in ids and called in ids
    assert hidden["repeats"] == 1
    assert hidden["counts"].get("new") == 1

    shown = await _table(app_client, caller, repeats="true")
    flags = {item["record_id"]: item["repeat"] for item in shown["items"]}
    assert flags[repeat] is True
    assert flags[fresh] is False and flags[called] is False
    assert shown["counts"].get("new") == 2
    assert shown["repeats"] == 1


@pytest.mark.asyncio
async def test_duplicate_report_is_one_note_per_person_and_record(app_client) -> None:
    caller = await _user("sales_view", "sales_edit")
    viewer = await _user("sales_view")
    company_id = await _company()
    record_id = await _record(caller.id, await _campaign(), company_id)

    first = await app_client.post(
        f"{URL}/records/{record_id}/duplicate",
        json={"note": "  Ta sama firma pod inną nazwą  "},
        headers=_headers(caller),
    )
    assert first.status_code == 200, first.text
    assert first.json() == {"created": True}
    again = await app_client.post(
        f"{URL}/records/{record_id}/duplicate", json={}, headers=_headers(caller)
    )
    assert again.json() == {"created": False}

    async with AsyncSessionLocal() as db:
        notes = (
            (
                await db.execute(
                    select(SalesActivity).where(
                        SalesActivity.external_source == DUPLICATE_SOURCE,
                        SalesActivity.company_id == company_id,
                    )
                )
            )
            .scalars()
            .all()
        )
    assert [(n.kind, n.body, n.created_by_user_id) for n in notes] == [
        ("note", "Ta sama firma pod inną nazwą", caller.id)
    ]

    refused = await app_client.post(
        f"{URL}/records/{record_id}/duplicate", json={}, headers=_headers(viewer)
    )
    assert refused.status_code == 403
    missing = await app_client.post(
        f"{URL}/records/999999999/duplicate", json={}, headers=_headers(caller)
    )
    assert missing.status_code == 404
