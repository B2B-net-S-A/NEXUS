"""Kto dzwoni? Szukanie po numerze (zgłoszenie dzwoniących, 23.11.2026)."""

from __future__ import annotations

import uuid

import pytest

from app.core.database import AsyncSessionLocal
from app.models.sales import SalesCompany
from app.services.sales.calling_lookup import phone_tail
from tests.test_sales_calling_queue import _campaign, _company, _contact, _record
from tests.test_sales_companies_api import _headers, _user

URL = "/api/sales/calling"


def _nine() -> str:
    # Numer na test: ten sam numer w dwóch testach to dla kolejki powtórka (17.11.2026).
    return f"5{uuid.uuid4().int % 10**8:08d}"


def _spaced(nine: str) -> str:
    return f"+48 {nine[:3]} {nine[3:6]} {nine[6:]}"


def test_phone_tail_takes_the_last_nine_digits() -> None:
    assert phone_tail("+48 500-058 777") == "500058777"
    assert phone_tail("0048500058777") == "500058777"
    assert phone_tail("500 058 77") is None
    assert phone_tail(None) is None


@pytest.mark.asyncio
async def test_who_calls_finds_records_of_everyone_and_company_contacts(
    app_client,
) -> None:
    viewer = await _user("sales_view")
    caller = await _user("sales_view", "sales_edit")
    nine = _nine()
    company_id = await _company("Oddzwania")
    record_id = await _record(
        caller.id,
        await _campaign(),
        company_id,
        phone=_spaced(nine),
        person_name="Ewa Testowa",
        state="no_answer",
    )
    other_company = await _company("Kontakt")
    contact_id = await _contact(
        other_company, full_name="Jan Kontakt", phone=None, mobile_phone=f"48{nine}"
    )

    resp = await app_client.get(
        f"{URL}/who-calls", params={"phone": nine}, headers=_headers(viewer)
    )
    assert resp.status_code == 200, resp.text
    matches = resp.json()
    assert [(m["record_id"], m["contact_id"]) for m in matches] == [
        (record_id, None),
        (None, contact_id),
    ]
    first = matches[0]
    assert first["company"]["id"] == company_id
    assert first["person_name"] == "Ewa Testowa"
    assert first["record_state"] == "no_answer"
    assert first["caller_name"] == caller.name
    assert first["do_not_contact"] is False
    # Odpowiedź nie oddaje żadnego numeru.
    assert all("phone" not in match for match in matches)


@pytest.mark.asyncio
async def test_who_calls_marks_objection_and_refuses_short_numbers(app_client) -> None:
    viewer = await _user("sales_view")
    nine = _nine()
    company_id = await _company("Sprzeciw")
    async with AsyncSessionLocal() as db:
        company = await db.get(SalesCompany, company_id)
        company.status = "do_not_contact"
        await db.commit()
    await _record(viewer.id, await _campaign(), company_id, phone=nine)

    resp = await app_client.get(
        f"{URL}/who-calls", params={"phone": _spaced(nine)}, headers=_headers(viewer)
    )
    assert resp.status_code == 200, resp.text
    assert [m["do_not_contact"] for m in resp.json()] == [True]

    short = await app_client.get(
        f"{URL}/who-calls", params={"phone": "500 058"}, headers=_headers(viewer)
    )
    assert short.status_code == 422


@pytest.mark.asyncio
async def test_who_calls_needs_sales_view(app_client) -> None:
    outsider = await _user()
    resp = await app_client.get(
        f"{URL}/who-calls", params={"phone": _nine()}, headers=_headers(outsider)
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_table_search_matches_the_digits_of_a_spaced_number(app_client) -> None:
    caller = await _user("sales_view", "sales_edit")
    nine = _nine()
    record_id = await _record(
        caller.id, await _campaign(), await _company(), phone=_spaced(nine)
    )
    resp = await app_client.get(
        f"{URL}/records", params={"q": nine}, headers=_headers(caller)
    )
    assert resp.status_code == 200, resp.text
    assert [item["record_id"] for item in resp.json()["items"]] == [record_id]
