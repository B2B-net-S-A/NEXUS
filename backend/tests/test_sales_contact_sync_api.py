"""Kontakty jako jedna lista (decyzje Artura z 13.11.2026), z bazą.

Bot Kontakty i rutyna Cognism zapisują osoby w zakładce Kontakty karty firmy,
stanowisko z nowszego źródła nadpisuje obecne, odejście daje „nie pracuje”.
Reguły: ``docs/claude/sprzedaz/kontakty-jedna-lista.md``. Nazwy i adresy są
fikcyjne (repo jest publiczne).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any, Optional

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.client import Client
from app.models.sales import (
    SalesBotResult,
    SalesCompanyContact,
    SalesContact,
    SalesOpportunity,
    SalesOpportunityEvent,
)
from app.services.sales import contact_sync, factories
from app.services.sales.bot_tasks import people
from app.services.sales.decision_map import decision_entries
from app.services.sales.motion import decision_people
from tests.test_sales_bot_people_api import _bot_person, _map
from tests.test_sales_companies_api import _headers, _user
from tests.test_sales_factories import _account, _company, _person
from tests.test_sales_signals_api import URL as RUNS
from tests.test_sales_signals_api import _run

CONTACTS = "/api/sales/contacts"
SRC = "https://firma.example/zarzad"
OLD = datetime(2026, 1, 10, 9, 0, tzinfo=timezone.utc)
RECENT = datetime(2026, 11, 1, 9, 0, tzinfo=timezone.utc)


def _tag() -> str:
    return uuid.uuid4().hex[:8]


async def _contact(
    company_id: int,
    name: str,
    *,
    title: Optional[str] = None,
    email: Optional[str] = None,
    updated: datetime = OLD,
) -> int:
    async with AsyncSessionLocal() as db:
        contact = SalesContact(
            company_id=company_id,
            full_name=name,
            title=title,
            email=email,
            source="manual",
            created_at=updated,
            updated_at=updated,
        )
        db.add(contact)
        await db.flush()
        db.add(
            SalesCompanyContact(
                company_id=company_id,
                contact_id=contact.id,
                title=title,
                is_primary=True,
            )
        )
        await db.commit()
        return contact.id


async def _report(app_client, company_id: int, firm: dict[str, Any]) -> dict:
    run_id, token = await _run([company_id], kind="people")
    resp = await app_client.post(
        f"{RUNS}/{run_id}",
        json={"checked_firms": 1, "firms": [{"company_ref": company_id, **firm}]},
        headers={"X-Run-Token": token},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _contacts(company_id: int) -> dict[str, tuple[SalesContact, Any]]:
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(SalesContact, SalesCompanyContact)
                .outerjoin(
                    SalesCompanyContact,
                    (SalesCompanyContact.contact_id == SalesContact.id)
                    & (SalesCompanyContact.company_id == company_id),
                )
                .where(SalesContact.company_id == company_id)
            )
        ).all()
    return {contact.full_name: (contact, link) for contact, link in rows}


async def _changes(company_id: int) -> list[dict[str, Any]]:
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(SalesBotResult.payload).where(
                    SalesBotResult.company_id == company_id,
                    SalesBotResult.kind == contact_sync.KIND,
                )
            )
        ).scalars()
        return [change for payload in rows for change in payload["changes"]]


@pytest.mark.asyncio
async def test_bot_people_land_in_contacts_and_newer_titles_win(
    app_client, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "SALES_BOT_TASKS_ENABLED", True)
    owner = await _user("sales_edit")
    company_id = await _company(f"Fabryka {_tag()}", owner_user_id=owner.id)
    account_id, _ = await _account(
        [
            _person("Jan Fikcyjny", 1, role_in_company="Dyrektor IT"),
            _person("Ewa Przykładowa", 1, role_in_company="CFO"),
        ],
        company_id=company_id,
    )
    await _contact(company_id, "Jan Fikcyjny", title="Dyrektor IT", updated=OLD)
    await _contact(company_id, "Przykładowa Ewa", title="CFO", updated=RECENT)
    await _contact(company_id, "Piotr Wzorcowy", email="piotr@firma.example")
    await _contact(company_id, "Zofia Nawiasowa (Head of HR)")

    reply = await _report(
        app_client,
        company_id,
        {
            "people": [
                # Źródło z października jest nowsze niż stanowisko ze stycznia.
                _bot_person("Jan Fikcyjny", title="CIO", published="2026-10-01"),
                # Źródło z czerwca jest starsze niż ręczna zmiana z listopada.
                _bot_person("Ewa Przykładowa", title="CEO", published="2026-06-01"),
                # Ten sam e-mail co kontakt: bez dubla, choć nazwisko inne.
                _bot_person(
                    "P. Wzorcowy",
                    email="Piotr@firma.example",
                    email_source_url=SRC,
                ),
                _bot_person(
                    "Anna Testowa",
                    title="CTO",
                    email="anna@firma.example",
                    email_source_url=SRC,
                    phone="+48 22 100 20 30",
                ),
            ]
        },
    )
    assert reply["contact_changes"] == 4
    found = await _contacts(company_id)
    assert set(found) == {
        "Jan Fikcyjny",
        "Przykładowa Ewa",
        "Piotr Wzorcowy",
        "Zofia Nawiasowa",
        "Anna Testowa",
    }
    jan, jan_link = found["Jan Fikcyjny"]
    assert (jan.title, jan_link.title) == ("CIO", "CIO")
    assert found["Przykładowa Ewa"][0].title == "CFO"
    anna, anna_link = found["Anna Testowa"]
    assert (anna.title, anna.email, anna.source) == (
        "CTO",
        "anna@firma.example",
        "bot-kontakty",
    )
    # Telefon bez własnego źródła odpada już w raporcie.
    assert anna.phone is None and anna_link.is_current is True
    assert found["Zofia Nawiasowa"][0].title == "Head of HR"

    entries = {entry["name"]: entry for entry in await _map(account_id)}
    assert entries["Jan Fikcyjny"]["role_in_company"] == "CIO"
    assert entries["Ewa Przykładowa"]["role_in_company"] == "CFO"
    async with AsyncSessionLocal() as db:
        events = (
            await db.execute(
                select(SalesOpportunityEvent).where(
                    SalesOpportunityEvent.opportunity_id == account_id,
                    SalesOpportunityEvent.field == "decision_map",
                    SalesOpportunityEvent.user_id.is_(None),
                )
            )
        ).scalars()
        assert any("CIO" in (e.new_value or "") for e in events)

    changes = {(c["name"], c["change"]): c for c in await _changes(company_id)}
    assert set(changes) == {
        ("Jan Fikcyjny", "title"),
        ("Anna Testowa", "added"),
        ("Zofia Nawiasowa", "split"),
        # Puste stanowisko dostaje wartość ze źródła bez porównywania dat.
        ("Piotr Wzorcowy", "title"),
    }
    assert changes[("Jan Fikcyjny", "title")]["before"] == "Dyrektor IT"
    assert changes[("Jan Fikcyjny", "title")]["as_of"] == "2026-10-01"

    history = await app_client.get(
        f"/api/sales/companies/{company_id}/bot-history", headers=_headers(owner)
    )
    assert history.status_code == 200, history.text
    lines = {
        line["label"]: line
        for item in history.json()["items"]
        if item["bot"] == "Kontakty"
        for line in item["lines"]
    }
    assert (lines["Jan Fikcyjny"]["before"], lines["Jan Fikcyjny"]["after"]) == (
        "Dyrektor IT",
        "CIO",
    )
    assert lines["Anna Testowa"]["source"] == "https://firma.example/zespol"

    # Ten sam raport drugi raz niczego nie dubluje.
    again = await _report(
        app_client,
        company_id,
        {"people": [_bot_person("Anna Testowa", title="CTO")]},
    )
    assert again["contact_changes"] == 0
    assert len(await _contacts(company_id)) == 5


@pytest.mark.asyncio
async def test_person_who_left_is_kept_as_not_working_and_can_come_back(
    app_client, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "SALES_BOT_TASKS_ENABLED", True)
    owner = await _user("sales_edit")
    company_id = await _company(f"Fabryka {_tag()}", owner_user_id=owner.id)
    await _account(
        [
            _person("Ewa Przykładowa", 1, role_in_company="Prezes Zarządu"),
            _person("Marek Mapowy", 2),
        ],
        company_id=company_id,
    )
    ewa_id = await _contact(company_id, "Ewa Przykładowa", title="Prezes Zarządu")
    await _contact(company_id, "Adam Abacki", title="CTO")

    reply = await _report(
        app_client,
        company_id,
        {
            "left": [
                {
                    "full_name": "Ewa Przykładowa",
                    "title": "Prezes Zarządu",
                    "source_url": SRC,
                    "published": "2026-10-02",
                    "left_on": "2026-10-01",
                },
                # Osoba z mapy bez kontaktu: kontakt z historią, „nie pracuje”.
                {
                    "full_name": "Marek Mapowy",
                    "source_url": SRC,
                    "published": "2026-10-02",
                },
                # Nieznana osoba, która odeszła, nie trafia do Kontaktów.
                {
                    "full_name": "Ktoś Obcy",
                    "source_url": SRC,
                    "published": "2026-10-02",
                },
            ]
        },
    )
    assert reply["contact_changes"] == 2
    found = await _contacts(company_id)
    assert "Ktoś Obcy" not in found
    ewa, ewa_link = found["Ewa Przykładowa"]
    assert ewa.archived_at is None
    assert (ewa_link.is_current, ewa_link.ended_at) == (False, date(2026, 10, 1))
    assert found["Marek Mapowy"][1].is_current is False

    listed = await app_client.get(
        CONTACTS, params={"company_id": company_id}, headers=_headers(owner)
    )
    assert listed.status_code == 200, listed.text
    names = [item["full_name"] for item in listed.json()["items"]]
    assert names[0] == "Adam Abacki"
    assert set(names[1:]) == {"Ewa Przykładowa", "Marek Mapowy"}

    by_name = {entry["name"]: entry for entry in await _entries_for(company_id)}
    assert by_name["Ewa Przykładowa"]["active"] is False
    assert by_name["Marek Mapowy"]["active"] is False
    assert not factories.waits_for_first_contact(by_name["Ewa Przykładowa"])

    # Nowsze źródło z datą znów pokazuje osobę w firmie: wraca jako pracująca.
    back = await _report(
        app_client,
        company_id,
        {
            "people": [
                _bot_person(
                    "Ewa Przykładowa", title="Prezes Zarządu", published="2026-11-05"
                )
            ]
        },
    )
    assert back["contact_changes"] == 1
    async with AsyncSessionLocal() as db:
        link = await db.get(SalesCompanyContact, (company_id, ewa_id))
        assert (link.is_current, link.ended_at) == (True, None)


async def _entries_for(company_id: int) -> list[dict[str, Any]]:
    async with AsyncSessionLocal() as db:
        opp = await db.scalar(
            select(SalesOpportunity).where(SalesOpportunity.company_id == company_id)
        )
        [entries] = await decision_people(
            db, [(company_id, decision_entries(opp.custom_fields))]
        )
        return entries


@pytest.mark.asyncio
async def test_nexus_client_card_gets_no_contacts_from_the_bot(
    app_client, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "SALES_BOT_TASKS_ENABLED", True)
    tag = _tag()
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Klient Powiazany {tag}")
        db.add(client)
        await db.commit()
        client_id = client.id
    company_id = await _company(f"Karta Klienta {tag}", client_id=client_id)
    await _contact(company_id, "Jan Fikcyjny", title="Dyrektor IT")

    reply = await _report(
        app_client,
        company_id,
        {
            "people": [
                _bot_person("Anna Testowa", title="CTO"),
                _bot_person("Jan Fikcyjny", title="CIO", published="2026-10-01"),
            ]
        },
    )
    assert reply["contact_changes"] == 0
    found = await _contacts(company_id)
    assert set(found) == {"Jan Fikcyjny"}
    assert found["Jan Fikcyjny"][0].title == "Dyrektor IT"


@pytest.mark.asyncio
async def test_cognism_people_join_contacts_and_inactive_stays_visible(
    app_client, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "SALES_COGNISM_PEOPLE_ENABLED", True)
    monkeypatch.setattr(settings, "SALES_BOT_TASKS_ENABLED", True)
    tag = _tag()
    name, domain = f"Fabryka {tag}", f"f{tag}.example"
    profile = "https://app.cognism.com/search/prospects/contacts/"
    observed_before = "2026-10-01T08:00:00+00:00"
    company_id = await _company(
        name,
        domain=domain,
        custom_fields={
            people.COGNISM_MAP_KEY: [
                {
                    "full_name": "Ewa Przykładowa",
                    "title": "Prezes Zarządu",
                    "source_url": f"{profile}ewa-profile-{tag}",
                    "observed_at": observed_before,
                    "source": "cognism",
                    "active": True,
                }
            ]
        },
    )
    await _contact(company_id, "Ewa Przykładowa", title="Prezes Zarządu")
    left_id = await _contact(company_id, "Olga Odeszła", title="CFO")
    async with AsyncSessionLocal() as db:
        link = await db.get(SalesCompanyContact, (company_id, left_id))
        link.is_current = False
        await db.commit()

    run_id, token = await _run(
        [company_id], kind="people", request={"source": "cognism"}
    )
    now = datetime.now(timezone.utc).isoformat()
    person = {
        "observed_at": now,
        "dnc": False,
        "email": None,
        "phone": None,
    }
    report = {
        "firms": [
            {
                "company_ref": company_id,
                "status": "matched",
                "company_name": name,
                "company_domain": domain,
                "people": [
                    {
                        **person,
                        "full_name": "Ewa Przykładowa",
                        "title": "Prezes Zarządu",
                        "source_url": f"{profile}ewa-profile-{tag}",
                        "active": False,
                    },
                    {
                        **person,
                        "full_name": "Jan Fikcyjny",
                        "title": "CIO",
                        "source_url": f"{profile}jan-profile-{tag}",
                        "active": True,
                        "email": f"jan@{domain}",
                        "email_type": "work",
                    },
                    # Odczyt Cognism nie przywraca osoby, która nie pracuje.
                    {
                        **person,
                        "full_name": "Olga Odeszła",
                        "title": "CFO",
                        "source_url": f"{profile}olga-profile-{tag}",
                        "active": True,
                    },
                ],
            }
        ]
    }
    resp = await app_client.post(
        f"{RUNS}/{run_id}", json=report, headers={"X-Run-Token": token}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["contact_changes"] == 2
    found = await _contacts(company_id)
    assert found["Ewa Przykładowa"][1].is_current is False
    jan, _ = found["Jan Fikcyjny"]
    assert (jan.title, jan.email, jan.source) == ("CIO", f"jan@{domain}", "cognism")
    assert found["Olga Odeszła"][1].is_current is False

    editor = await _user("sales_edit")
    response = await app_client.get(
        f"/api/sales/bot-people/companies/{company_id}/map", headers=_headers(editor)
    )
    assert response.status_code == 200, response.text
    shown = {p["full_name"]: p for p in response.json()["people"]}
    assert shown["Ewa Przykładowa"]["active"] is False
    assert shown["Jan Fikcyjny"]["active"] is True
    assert shown["Olga Odeszła"]["active"] is False

    # Przykład z kopii z 13.11: Cognism wciąż pokazuje osobę jako aktywną, ale
    # opublikowane źródło sprzed odczytu mówi, że odeszła. Odczyt Cognism nie
    # dowodzi, że osoba dalej pracuje, więc odejście wygrywa.
    reply = await _report(
        app_client,
        company_id,
        {
            "left": [
                {
                    "full_name": "Jan Fikcyjny",
                    "source_url": SRC,
                    "published": "2026-10-07",
                    "left_on": "2026-10-01",
                }
            ]
        },
    )
    assert reply["contact_changes"] == 1
    assert (await _contacts(company_id))["Jan Fikcyjny"][1].is_current is False


@pytest.mark.asyncio
async def test_manual_title_change_shows_on_the_company_list(app_client) -> None:
    editor = await _user("sales_edit")
    company_id = await _company()
    contact_id = await _contact(company_id, "Jan Fikcyjny", title="Dyrektor IT")
    resp = await app_client.patch(
        f"{CONTACTS}/{contact_id}", json={"title": "CIO"}, headers=_headers(editor)
    )
    assert resp.status_code == 200, resp.text
    [here] = [c for c in resp.json()["companies"] if c["company_id"] == company_id]
    assert here["title"] == "CIO"
