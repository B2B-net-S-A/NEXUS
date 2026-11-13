"""Dzwonienie po liście zmian od osób dzwoniących (decyzje Artura 13.11.2026).

Import z podziałem na osoby i „Typem usługi”, bramka NIP-u, zakładka „Nie odebrane”,
oferta → Leady, spotkanie → uzupełniona szansa, edycja danych z karty, zmiana statusu
z Tabeli bez telefonu, kolejność Tabeli i filtr dat, Przypomnienia. Dane są fikcyjne.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.sales import SalesActivity, SalesCallRecord, SalesContact, SalesLead
from app.services.sales import calling, calling_crm
from app.services.sales.calling_file import ListRow, parse_list_file
from app.services.sales.calling_import import (
    NIP_LOADED_DETAIL,
    caller_keys,
    row_assignee,
    row_note,
)
from tests.test_sales_calling_import import _phone, _post
from tests.test_sales_calling_queue import (
    _calls,
    _campaign,
    _company,
    _contact,
    _get_record,
    _opportunity,
    _queue,
    _record,
    _save,
)
from tests.test_sales_companies_api import _headers, _user

URL = "/api/sales/calling"
HEADER = "Nazwa firmy;NIP;Numer kontaktu;Adres mailowy;Imię i nazwisko;Stanowisko;LinkedIn;Typ usługi;Kto dzwoni;Uwagi o firmie"


def _nip() -> str:
    return f"{uuid.uuid4().int % 10**10:010d}"


def _csv(*rows: str) -> bytes:
    return "\n".join((HEADER, *rows)).encode("utf-8")


async def _lead(record_id: int) -> SalesLead | None:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(SalesLead).where(
                SalesLead.fingerprint == calling_crm.lead_fingerprint(record_id)
            )
        )


# ── Plik: nowe kolumny ────────────────────────────────────────────────────


def test_list_reads_service_caller_and_company_notes() -> None:
    payload = _csv(
        "Firma A;5260001234;600 100 200;jan@firma-a.pl;Jan Nowak;CTO;"
        "linkedin.com/in/jan;Body leasing;Bianca;Szukają Javy od stycznia"
    )
    [row] = parse_list_file("lista.csv", payload).rows
    assert (row.service, row.caller) == ("Body leasing", "Bianca")
    assert row.note == "Szukają Javy od stycznia"
    assert row_note(row) == "Typ usługi: Body leasing\nSzukają Javy od stycznia"
    assert row_note(ListRow(line=2, company="B")) is None


def test_caller_column_matches_a_unique_first_name_or_full_name() -> None:
    people = [(1, "Bianca Kowalska"), (2, "Marcel Nowak"), (3, "Marcel Zieliński")]
    keys = caller_keys(people)
    row = ListRow(line=2, company="X", caller="Bianca")
    assert row_assignee(row, 9, keys) == 1
    # Dwóch Marceli: samo imię nikogo nie wskazuje, pełne imię i nazwisko tak.
    assert row_assignee(ListRow(line=2, company="X", caller="Marcel"), 9, keys) == 9
    assert (
        row_assignee(ListRow(line=2, company="X", caller="Marcel Zielinski"), 9, keys)
        == 3
    )
    assert row_assignee(ListRow(line=2, company="X"), 9, keys) == 9
    assert row_assignee(row, 9, None) == 9


# ── Import: osoba z kolumny i bramka NIP-u ───────────────────────────────


@pytest.mark.asyncio
async def test_import_assigns_rows_by_the_caller_column(app_client) -> None:
    importer = await _user("sales_view", "sales_edit")
    other = await _user("sales_view", "sales_edit")
    campaign_id = await _campaign()
    tag = uuid.uuid4().hex[:8]
    payload = _csv(
        f"Firma {tag} A;{_nip()};{_phone()};;Jan A;CTO;;Body leasing;{other.name};",
        f"Firma {tag} B;{_nip()};{_phone()};;Jan B;CTO;;;Ktoś Nieznany;",
    )
    preview = await _post(app_client, importer, campaign_id, payload)
    assert preview.status_code == 200, preview.text
    rows = preview.json()["rows"]
    assert [row["assignee"]["id"] for row in rows] == [other.id, importer.id]

    saved = await _post(app_client, importer, campaign_id, payload, preview=False)
    assert saved.status_code == 200, saved.text
    async with AsyncSessionLocal() as db:
        records = list(
            (
                await db.execute(
                    select(SalesCallRecord)
                    .where(SalesCallRecord.campaign_id == campaign_id)
                    .order_by(SalesCallRecord.id)
                )
            ).scalars()
        )
    assert [r.assigned_user_id for r in records] == [other.id, importer.id]
    assert records[0].note == "Typ usługi: Body leasing"


@pytest.mark.asyncio
async def test_next_import_adds_only_companies_with_a_new_nip(app_client) -> None:
    importer = await _user("sales_view", "sales_edit")
    tag = uuid.uuid4().hex[:8]
    known_nip, new_nip = _nip(), _nip()
    first = _csv(f"Firma {tag} A;{known_nip};{_phone()};;Jan A;CTO;;;;")
    assert (
        await _post(app_client, importer, await _campaign(), first, preview=False)
    ).json()["added"] == 1
    # Druga lista, inna kampania, inna osoba i numer: ten sam NIP już był.
    second = _csv(
        f"Firma {tag} A sp. z o.o.;{known_nip};{_phone()};;Ewa A;CEO;;;;",
        f"Firma {tag} C;{new_nip};{_phone()};;Jan C;CTO;;;;",
    )
    campaign_id = await _campaign()
    body = (await _post(app_client, importer, campaign_id, second)).json()
    assert [(row["fate"], row["detail"]) for row in body["rows"]] == [
        ("already_in_campaign", NIP_LOADED_DETAIL),
        ("new_company", body["rows"][1]["detail"]),
    ]
    saved = await _post(app_client, importer, campaign_id, second, preview=False)
    assert saved.json()["added"] == 1


# ── Kolejka: „Nie odebrane” ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_answer_has_its_own_tab_whatever_the_date(app_client) -> None:
    caller = await _user("sales_view", "sales_edit")
    campaign_id = await _campaign()
    now = datetime.now(timezone.utc)
    later = await _record(
        caller.id,
        campaign_id,
        await _company(),
        state="no_answer",
        callback_on=business_today() + timedelta(days=5),
        last_outcome_at=now - timedelta(hours=1),
    )
    earlier = await _record(
        caller.id,
        campaign_id,
        await _company(),
        state="no_answer",
        callback_on=business_today(),
        last_outcome_at=now - timedelta(days=1),
    )
    queue = await _queue(app_client, caller)
    assert [item["record_id"] for item in queue["no_answer"]] == [earlier, later]
    assert queue["counts"]["no_answer"] == 2
    assert queue["callbacks"] == [] and queue["counts"]["later"] == 0


# ── Oferta → Leady, spotkanie → szansa ───────────────────────────────────


@pytest.mark.asyncio
async def test_offer_sent_writes_a_full_lead_once_per_record(app_client) -> None:
    caller = await _user("sales_view", "sales_edit")
    company_id = await _company(nip="5260009999")
    contact_id = await _contact(company_id, linkedin_url="https://linkedin.com/in/x")
    record_id = await _record(
        caller.id,
        await _campaign(),
        company_id,
        contact_id=contact_id,
        person_name="Jan Testowy",
        person_title="CTO",
        email="jan@example.com",
        note="Typ usługi: Body leasing",
    )
    resp = await _save(
        app_client, caller, record_id, outcome="offer_sent", note="Wysłałem PDF"
    )
    assert resp.status_code == 200, resp.text
    lead = await _lead(record_id)
    assert lead is not None
    assert (lead.source, lead.status, lead.company_id) == (
        "manual",
        "contacted",
        company_id,
    )
    assert lead.assignee_user_id == caller.id
    assert lead.payload["origin"] == "calling"
    assert lead.payload["email"] == "jan@example.com"
    assert lead.payload["linkedin"] == "https://linkedin.com/in/x"
    for fact in ("Jan Testowy, CTO", "600 100 200", "NIP: 5260009999", "Wysłałem PDF"):
        assert fact in lead.summary
    # Kolejna oferta odświeża ten sam wpis, bez drugiego leada.
    async with AsyncSessionLocal() as db:
        record = await db.get(SalesCallRecord, record_id)
        record.state = "call_back"
        await db.commit()
    again = await _save(app_client, caller, record_id, outcome="offer_sent", never=True)
    assert again.status_code == 200, again.text
    async with AsyncSessionLocal() as db:
        leads = (
            await db.execute(
                select(SalesLead).where(
                    SalesLead.fingerprint == calling_crm.lead_fingerprint(record_id)
                )
            )
        ).scalars()
        [only] = list(leads)
    assert "Bez ponownego kontaktu" in only.summary


@pytest.mark.asyncio
async def test_meeting_closes_the_lead_and_fills_the_opportunity(app_client) -> None:
    caller = await _user("sales_view", "sales_edit")
    company_id = await _company()
    contact_id = await _contact(company_id)
    record_id = await _record(
        caller.id,
        await _campaign(),
        company_id,
        contact_id=contact_id,
        person_name="Jan Testowy",
        email="jan@example.com",
    )
    assert (
        await _save(app_client, caller, record_id, outcome="offer_sent")
    ).status_code == 200
    opp_id = await _opportunity(caller.id, company_id, stage="qualifying-meeting")
    async with AsyncSessionLocal() as db:
        (await db.get(SalesCallRecord, record_id)).state = "call_back"
        await db.commit()
    booked = await _save(
        app_client, caller, record_id, outcome="meeting_booked", opportunity_id=opp_id
    )
    assert booked.status_code == 200, booked.text
    lead = await _lead(record_id)
    assert (lead.status, lead.opportunity_id) == ("converted", opp_id)
    async with AsyncSessionLocal() as db:
        from app.models.sales import SalesOpportunity

        opp = await db.get(SalesOpportunity, opp_id)
    assert "jan@example.com" in opp.description
    assert opp.primary_contact_id == contact_id


# ── Edycja danych i zmiana statusu ───────────────────────────────────────


@pytest.mark.asyncio
async def test_card_edits_the_record_and_the_contact(app_client) -> None:
    caller = await _user("sales_view", "sales_edit")
    viewer = await _user("sales_view")
    company_id = await _company()
    contact_id = await _contact(company_id)
    record_id = await _record(
        caller.id, await _campaign(), company_id, contact_id=contact_id
    )
    url = f"{URL}/records/{record_id}"
    assert (
        await app_client.patch(url, json={"phone": "1"}, headers=_headers(viewer))
    ).status_code == 403
    bad = await app_client.patch(
        url, json={"email": "nie-adres"}, headers=_headers(caller)
    )
    assert bad.status_code == 422
    resp = await app_client.patch(
        url,
        json={
            "email": "Nowy@Example.com",
            "phone": "601 222 333",
            "person_title": "CEO",
        },
        headers=_headers(caller),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["email"] == "nowy@example.com"
    record = await _get_record(record_id)
    assert (record.phone, record.person_title) == ("601 222 333", "CEO")
    async with AsyncSessionLocal() as db:
        contact = await db.get(SalesContact, contact_id)
    assert (contact.email, contact.phone, contact.title) == (
        "nowy@example.com",
        "601 222 333",
        "CEO",
    )


@pytest.mark.asyncio
async def test_table_status_change_is_a_correction_not_a_call(app_client) -> None:
    caller = await _user("sales_view", "sales_edit")
    company_id = await _company()
    record_id = await _record(
        caller.id, await _campaign(), company_id, state="no_answer"
    )
    url = f"{URL}/records/{record_id}/state"
    resp = await app_client.post(
        url, json={"state": "offer_sent"}, headers=_headers(caller)
    )
    assert resp.status_code == 200, resp.text
    assert (
        resp.json()["callback_on"]
        == calling.workdays_after(
            business_today(), calling.OFFER_CALLBACK_WORKDAYS
        ).isoformat()
    )
    record = await _get_record(record_id)
    assert (record.state, record.attempts) == ("offer_sent", 0)
    assert await _calls(company_id) == []
    assert (await _lead(record_id)).status == "contacted"
    # Spotkanie i sprzeciw tylko z karty rozmowy.
    for state in ("meeting_booked", "do_not_contact", "not_now"):
        refused = await app_client.post(
            url, json={"state": state}, headers=_headers(caller)
        )
        assert refused.status_code == 422


# ── Tabela i Przypomnienia ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_table_is_ordered_by_last_change_and_filters_callback_dates(
    app_client,
) -> None:
    caller = await _user("sales_view", "sales_edit")
    campaign_id = await _campaign()
    today = business_today()
    older = await _record(
        caller.id,
        campaign_id,
        await _company(),
        state="call_back",
        callback_on=today + timedelta(days=2),
    )
    newer = await _record(
        caller.id,
        campaign_id,
        await _company(),
        state="call_back",
        callback_on=today + timedelta(days=9),
    )
    async with AsyncSessionLocal() as db:
        (await db.get(SalesCallRecord, older)).updated_at = datetime.now(
            timezone.utc
        ) - timedelta(days=3)
        await db.commit()
    params: dict[str, Any] = {"campaign_id": campaign_id}
    resp = await app_client.get(
        f"{URL}/records", params=params, headers=_headers(caller)
    )
    body = resp.json()
    assert [item["record_id"] for item in body["items"]] == [newer, older]
    assert body["items"][0]["modified_at"] is not None
    params["callback_from"] = (today + timedelta(days=5)).isoformat()
    filtered = (
        await app_client.get(f"{URL}/records", params=params, headers=_headers(caller))
    ).json()
    assert [item["record_id"] for item in filtered["items"]] == [newer]
    assert filtered["total"] == 1
    # Druga strona: offset przesuwa okno (zamiast „Pokazano 200 z 239”).
    page = (
        await app_client.get(
            f"{URL}/records",
            params={"campaign_id": campaign_id, "limit": 1, "offset": 1},
            headers=_headers(caller),
        )
    ).json()
    assert [item["record_id"] for item in page["items"]] == [older]


@pytest.mark.asyncio
async def test_reminders_list_dated_callbacks_and_offers(app_client) -> None:
    caller = await _user("sales_view", "sales_edit")
    other = await _user("sales_view", "sales_edit")
    campaign_id = await _campaign()
    today = business_today()
    late = await _record(
        caller.id,
        campaign_id,
        await _company(),
        state="offer_sent",
        callback_on=today - timedelta(days=1),
    )
    soon = await _record(
        caller.id,
        campaign_id,
        await _company(),
        state="call_back",
        callback_on=today + timedelta(days=4),
    )
    await _record(caller.id, campaign_id, await _company(), state="offer_sent")
    await _record(caller.id, campaign_id, await _company(), state="no_answer")
    theirs = await _record(
        other.id, campaign_id, await _company(), state="call_back", callback_on=today
    )
    mine = (await app_client.get(f"{URL}/reminders", headers=_headers(caller))).json()
    assert [item["record_id"] for item in mine] == [late, soon]
    until_today = (
        await app_client.get(
            f"{URL}/reminders",
            params={"until": today.isoformat()},
            headers=_headers(caller),
        )
    ).json()
    assert [item["record_id"] for item in until_today] == [late]
    everyone = (
        await app_client.get(
            f"{URL}/reminders",
            params={"scope": "all", "caller_id": other.id},
            headers=_headers(caller),
        )
    ).json()
    assert [item["record_id"] for item in everyone] == [theirs]


@pytest.mark.asyncio
async def test_no_call_is_logged_by_the_table_or_the_card_edit(app_client) -> None:
    caller = await _user("sales_view", "sales_edit")
    company_id = await _company()
    record_id = await _record(caller.id, await _campaign(), company_id)
    await app_client.patch(
        f"{URL}/records/{record_id}",
        json={"note": "Dzwonić po 10"},
        headers=_headers(caller),
    )
    async with AsyncSessionLocal() as db:
        count = (
            await db.execute(
                select(SalesActivity.id).where(SalesActivity.company_id == company_id)
            )
        ).all()
    assert count == []
    assert (await _get_record(record_id)).note == "Dzwonić po 10"
