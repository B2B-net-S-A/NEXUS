"""Kolejka po Excelu dzwoniących (decyzje Artura 11.11.2026): „Nie zainteresowany”,
„Zły numer / brak danych”, licznik „Dziś”, widok „Tabela” i LinkedIn z importu.

Baza testowa jest wspólna, więc każdy test ma własnego dzwoniącego. Dane fikcyjne.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pytest

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.sales import SalesActivity, SalesCallRecord, SalesContact
from app.services import sales_schema as schema
from app.services.sales import calling
from app.services.sales.calling_file import linkedin_url, parse_list_file
from tests.test_sales_calling_queue import (
    URL,
    _campaign,
    _company,
    _contact,
    _get_record,
    _queue,
    _record,
    _save,
)
from tests.test_sales_companies_api import _headers, _user

WEDNESDAY = date(2026, 11, 18)


# ── Daty powrotu ──────────────────────────────────────────────────────────


def test_not_interested_returns_after_half_a_year_or_never() -> None:
    default = calling.resolve_callback("not_interested", None, WEDNESDAY)
    assert default is not None and default >= WEDNESDAY + timedelta(days=182)
    assert default.weekday() < 5
    picked = WEDNESDAY + timedelta(days=90)
    assert calling.resolve_callback("not_interested", picked, WEDNESDAY) == picked
    assert (
        calling.resolve_callback("not_interested", None, WEDNESDAY, never=True) is None
    )
    # „Zły numer” zamyka rekord: data z formularza się nie liczy.
    assert calling.resolve_callback("bad_contact", picked, WEDNESDAY) is None


def test_new_outcomes_are_in_both_dictionaries() -> None:
    for outcome in ("not_interested", "bad_contact"):
        assert outcome in schema.CALL_OUTCOMES
        assert outcome in schema.CALL_QUEUE_OUTCOMES
        assert outcome in schema.CK_CALL_RECORD_STATE
    assert "not_interested" in " ".join(schema.CALL_OUTCOMES_V2_DDL)


def test_previous_business_day_skips_weekend_and_holiday() -> None:
    assert calling.previous_business_day(date(2026, 11, 16)) == date(2026, 11, 13)
    # 11.11 to święto: czwartek 12.11 → wtorek 10.11.
    assert calling.previous_business_day(date(2026, 11, 12)) == date(2026, 11, 10)


@pytest.mark.parametrize(
    ("cell", "expected"),
    [
        (
            "https://www.linkedin.com/in/jan-testowy",
            "https://www.linkedin.com/in/jan-testowy",
        ),
        ("linkedin.com/in/jan", "https://linkedin.com/in/jan"),
        ("https://pl.linkedin.com/in/jan", "https://pl.linkedin.com/in/jan"),
        ("https://evil.example/linkedin.com/in/jan", None),
        ("javascript:alert(1)", None),
        ("tak", None),
        (None, None),
    ],
)
def test_linkedin_cell_accepts_only_profile_urls(cell: Any, expected: Any) -> None:
    assert linkedin_url(cell) == expected


def test_list_file_reads_the_linkedin_column() -> None:
    payload = (
        "Firma;Imię;Nazwisko;Telefon;LinkedIn\n"
        "Testowa;Jan;Testowy;600100200;https://www.linkedin.com/in/jan-testowy\n"
    ).encode()
    [row] = parse_list_file("lista.csv", payload).rows
    assert row.linkedin == "https://www.linkedin.com/in/jan-testowy"


# ── Kolejka ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_not_interested_and_bad_contact_leave_the_queue(app_client) -> None:
    caller = await _user("sales_view", "sales_edit")
    campaign_id = await _campaign()
    never_id = await _record(caller.id, campaign_id, await _company())
    later_id = await _record(caller.id, campaign_id, await _company())
    bad_id = await _record(caller.id, campaign_id, await _company())

    resp = await _save(
        app_client, caller, never_id, outcome="not_interested", never=True
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["callback_on"] is None
    resp = await _save(app_client, caller, later_id, outcome="not_interested")
    assert resp.status_code == 200, resp.text
    assert resp.json()["callback_on"] is not None
    resp = await _save(app_client, caller, bad_id, outcome="bad_contact")
    assert resp.status_code == 200, resp.text

    queue = await _queue(app_client, caller, campaign_id=campaign_id)
    assert queue["callbacks"] == [] and queue["new"] == []
    # Pół roku czekania nie zasłania „wróci w swoim dniu”.
    assert queue["counts"]["later"] == 0
    assert (await _get_record(bad_id)).state == "bad_contact"


@pytest.mark.asyncio
async def test_not_interested_comes_back_on_its_day(app_client) -> None:
    caller = await _user("sales_view", "sales_edit")
    campaign_id = await _campaign()
    record_id = await _record(
        caller.id,
        campaign_id,
        await _company(),
        state="not_interested",
        callback_on=business_today(),
    )
    queue = await _queue(app_client, caller, campaign_id=campaign_id)
    assert [item["record_id"] for item in queue["callbacks"]] == [record_id]


@pytest.mark.asyncio
async def test_today_counts_count_own_calls_only(app_client) -> None:
    caller = await _user("sales_view", "sales_edit")
    other = await _user("sales_view", "sales_edit")
    campaign_id = await _campaign()
    for outcome in ("no_answer", "offer_sent", "not_interested"):
        record_id = await _record(caller.id, campaign_id, await _company())
        resp = await _save(app_client, caller, record_id, outcome=outcome)
        assert resp.status_code == 200, resp.text
    queue = await _queue(app_client, caller)
    assert queue["today_counts"] == {"calls": 3, "talks": 2, "offers": 1, "meetings": 0}
    assert queue["yesterday"] < queue["today"]
    assert (await _queue(app_client, other))["today_counts"]["calls"] == 0


# ── Tabela ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_table_lists_all_own_records_with_counts_and_filter(app_client) -> None:
    caller = await _user("sales_view", "sales_edit")
    other = await _user("sales_view", "sales_edit")
    campaign_id = await _campaign()
    new_id = await _record(caller.id, campaign_id, await _company())
    closed_id = await _record(
        caller.id, campaign_id, await _company(), state="not_interested"
    )
    await _record(caller.id, campaign_id, await _company(), state="do_not_contact")
    await _record(other.id, campaign_id, await _company())

    resp = await app_client.get(
        f"{URL}/records", params={"campaign_id": campaign_id}, headers=_headers(caller)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Sprzeciwu nie ma w tabeli ani w licznikach (numer nie może wyjść z API).
    assert body["counts"] == {"new": 1, "not_interested": 1}
    assert {item["record_id"] for item in body["items"]} == {new_id, closed_id}

    resp = await app_client.get(
        f"{URL}/records",
        params={"campaign_id": campaign_id, "state": "not_interested"},
        headers=_headers(caller),
    )
    body = resp.json()
    assert [item["record_id"] for item in body["items"]] == [closed_id]
    assert body["total"] == 1 and body["counts"]["new"] == 1

    bad = await app_client.get(
        f"{URL}/records", params={"state": "do_not_contact"}, headers=_headers(caller)
    )
    assert bad.status_code == 422


@pytest.mark.asyncio
async def test_table_search_matches_company_person_and_phone(app_client) -> None:
    caller = await _user("sales_view", "sales_edit")
    campaign_id = await _campaign()
    company_id = await _company("Szukana")
    record_id = await _record(
        caller.id,
        campaign_id,
        company_id,
        person_name="Ewa Znaleziona",
        phone="511 222 333",
    )
    await _record(caller.id, campaign_id, await _company("Inna"))
    for query in ("Szukana", "znalezion", "511 222"):
        resp = await app_client.get(
            f"{URL}/records",
            params={"campaign_id": campaign_id, "q": query},
            headers=_headers(caller),
        )
        assert [item["record_id"] for item in resp.json()["items"]] == [record_id], (
            query
        )


@pytest.mark.asyncio
async def test_table_needs_sales_view(app_client) -> None:
    outsider = await _user()
    resp = await app_client.get(f"{URL}/records", headers=_headers(outsider))
    assert resp.status_code == 403


# ── Karta i import ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_card_shows_the_contact_linkedin(app_client) -> None:
    caller = await _user("sales_view", "sales_edit")
    company_id = await _company()
    contact_id = await _contact(
        company_id, linkedin_url="https://www.linkedin.com/in/jan-testowy"
    )
    record_id = await _record(
        caller.id, await _campaign(), company_id, contact_id=contact_id
    )
    resp = await app_client.get(f"{URL}/records/{record_id}", headers=_headers(caller))
    assert resp.status_code == 200, resp.text
    assert resp.json()["linkedin_url"] == "https://www.linkedin.com/in/jan-testowy"


@pytest.mark.asyncio
async def test_import_fills_an_empty_linkedin_but_keeps_an_existing_one(
    app_client,
) -> None:
    caller = await _user("sales_view", "sales_edit")
    campaign_id = await _campaign()
    # Baza testowa jest wspólna: losowa firma i numer, żeby bramki importu nie
    # złapały wiersza z poprzedniego biegu.
    marker = uuid.uuid4().hex[:8]
    phone = f"6{uuid.uuid4().int % 10**8:08d}"
    payload = (
        "Firma;Osoba;Telefon;LinkedIn\n"
        f"Nowa Firma LI {marker};Anna Nowa;{phone};https://www.linkedin.com/in/anna-{marker}\n"
    ).encode()
    resp = await app_client.post(
        f"{URL}/campaigns/{campaign_id}/import",
        files={"file": ("lista.csv", payload, "text/csv")},
        data={"contact_source": "Test LinkedIn"},
        headers=_headers(caller),
    )
    assert resp.status_code == 200, resp.text
    async with AsyncSessionLocal() as db:
        from sqlalchemy import select

        record = (
            await db.execute(
                select(SalesCallRecord).where(
                    SalesCallRecord.campaign_id == campaign_id
                )
            )
        ).scalar_one()
        contact = await db.get(SalesContact, record.contact_id)
    assert contact.linkedin_url == f"https://www.linkedin.com/in/anna-{marker}"


@pytest.mark.asyncio
async def test_new_outcomes_land_in_the_call_log(app_client) -> None:
    caller = await _user("sales_view", "sales_edit")
    company_id = await _company()
    record_id = await _record(caller.id, await _campaign(), company_id)
    resp = await _save(app_client, caller, record_id, outcome="bad_contact")
    assert resp.status_code == 200, resp.text
    async with AsyncSessionLocal() as db:
        from sqlalchemy import select

        [call] = (
            await db.execute(
                select(SalesActivity).where(
                    SalesActivity.company_id == company_id, SalesActivity.kind == "call"
                )
            )
        ).scalars()
    assert call.outcome == "bad_contact"
    assert call.subject.startswith("Zły numer / brak danych")
    assert call.occurred_at <= datetime.now(timezone.utc)


def test_day_totals_model_matches_the_ddl() -> None:
    import re

    from app.models.sales import SalesCallDayTotal

    ddl = next(
        statement
        for statement in schema.CALL_OUTCOMES_V2_DDL
        if "CREATE TABLE IF NOT EXISTS sales_call_day_totals (" in statement
    )
    declared = set(re.findall(r"^\s+([a-z_0-9]+) [A-Z]", ddl, re.MULTILINE))
    assert set(SalesCallDayTotal.__table__.columns.keys()) == declared
    assert (
        "DROP TABLE IF EXISTS sales_call_day_totals"
        in schema.CALL_OUTCOMES_V2_DOWNGRADE_DDL
    )
