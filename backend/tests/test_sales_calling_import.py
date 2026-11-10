"""Sprzedaż → Dzwonienie: import listy do kampanii, każda bramka i ścieżki odmowy.

Dane są fikcyjne; nazwy firm niosą losowy znacznik, bo baza testowa jest wspólna.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import pytest
from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal
from app.models.client import Client
from app.models.sales import (
    SalesCallRecord,
    SalesCompany,
    SalesCompanyAlias,
    SalesContact,
    SalesOpportunity,
)
from app.services.company_names import normalize_company_name
from app.services.sales import calling_file
from app.services.sales.calling_import import (
    IN_CAMPAIGN_DETAIL,
    NO_PHONE_DETAIL,
    OBJECTION_DETAIL,
    REPEATED_DETAIL,
)
from tests.test_sales_calling_queue import (
    _campaign,
    _company,
    _contact,
    _opportunity,
    _queue,
    _record,
)
from tests.test_sales_companies_api import _headers, _user

URL = "/api/sales/calling"
HEADER = "Firma;Osoba;Stanowisko;Telefon;E-mail;WWW"
SOURCE = "Lista z konferencji branżowej"


def _tag() -> str:
    return uuid.uuid4().hex[:10]


def _phone() -> str:
    """Numer tylko dla tego testu: sprzeciw z innego testu idzie za numerem."""

    return f"5{uuid.uuid4().int % 10**8:08d}"


def _csv(*rows: str) -> bytes:
    return "\n".join((HEADER, *rows)).encode("utf-8")


async def _post(
    app_client,
    user,
    campaign_id: int,
    payload: bytes,
    *,
    preview: bool = True,
    filename: str = "lista.csv",
    source: Optional[str] = SOURCE,
    assignee: Optional[int] = None,
):
    data: dict[str, Any] = {}
    if source is not None:
        data["contact_source"] = source
    if assignee is not None:
        data["assignee_user_id"] = str(assignee)
    suffix = "/import/preview" if preview else "/import"
    return await app_client.post(
        f"{URL}/campaigns/{campaign_id}{suffix}",
        files={"file": (filename, payload, "text/csv")},
        data=data,
        headers=_headers(user),
    )


async def _fates(app_client, user, campaign_id: int, payload: bytes, **kwargs: Any):
    resp = await _post(app_client, user, campaign_id, payload, **kwargs)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    return body, [(row["fate"], row["detail"]) for row in body["rows"]]


async def _named_company(name: str, **fields: Any) -> int:
    async with AsyncSessionLocal() as db:
        company = SalesCompany(
            name=name, normalized_name=normalize_company_name(name), **fields
        )
        db.add(company)
        await db.commit()
        return company.id


async def _record_count(campaign_id: int) -> int:
    async with AsyncSessionLocal() as db:
        return int(
            await db.scalar(
                select(func.count(SalesCallRecord.id)).where(
                    SalesCallRecord.campaign_id == campaign_id
                )
            )
        )


# ── Dostęp i walidacja pliku ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_import_needs_edit_permission_and_an_existing_campaign(
    app_client,
) -> None:
    viewer = await _user("sales_view")
    caller = await _user("sales_edit")
    campaign_id = await _campaign()
    payload = _csv(f"Firma {_tag()};Jan Testowy;CTO;{_phone()};;")
    for preview in (True, False):
        denied = await _post(app_client, viewer, campaign_id, payload, preview=preview)
        assert denied.status_code == 403
        missing = await _post(
            app_client, caller, 2_000_000_000, payload, preview=preview
        )
        assert missing.status_code == 404
    assert await _record_count(campaign_id) == 0


@pytest.mark.parametrize(
    ("filename", "payload", "status_code", "detail"),
    [
        ("lista.pdf", b"%PDF-1.7", 422, calling_file.BAD_TYPE_DETAIL),
        (
            "lista.xlsx",
            b"firma;telefon\nA;600100200\n",
            422,
            calling_file.UNREADABLE_DETAIL,
        ),
        (
            "lista.csv",
            b"firma;osoba\nA;Jan\n",
            422,
            calling_file.NO_PHONE_COLUMN_DETAIL,
        ),
        (
            "lista.csv",
            b"firma;telefon\n" + b"x" * calling_file.MAX_FILE_BYTES,
            413,
            calling_file.TOO_BIG_DETAIL,
        ),
        (
            "lista.csv",
            (
                "firma;telefon\n"
                + "\n".join(
                    f"F{i};600100{i:03d}" for i in range(calling_file.MAX_ROWS + 1)
                )
            ).encode(),
            422,
            calling_file.TOO_MANY_ROWS_DETAIL,
        ),
    ],
)
@pytest.mark.asyncio
async def test_file_is_validated_at_the_boundary(
    app_client, filename: str, payload: bytes, status_code: int, detail: str
) -> None:
    caller = await _user("sales_edit")
    campaign_id = await _campaign()
    resp = await _post(
        app_client, caller, campaign_id, payload, preview=False, filename=filename
    )
    assert (resp.status_code, resp.json()["detail"]) == (status_code, detail)
    assert await _record_count(campaign_id) == 0


@pytest.mark.asyncio
async def test_import_requires_the_contact_source_but_preview_does_not(
    app_client,
) -> None:
    caller = await _user("sales_edit")
    campaign_id = await _campaign()
    payload = _csv(f"Firma {_tag()};Jan Testowy;CTO;{_phone()};;")
    for source in (None, "  ", "ab"):
        refused = await _post(
            app_client, caller, campaign_id, payload, preview=False, source=source
        )
        assert refused.status_code == 422
        assert refused.json()["detail"] == "Wpisz, skąd masz kontakty z tej listy."
    assert await _record_count(campaign_id) == 0
    preview = await _post(app_client, caller, campaign_id, payload, source=None)
    assert preview.status_code == 200 and preview.json()["addable"] == 1


@pytest.mark.asyncio
async def test_assignee_must_be_an_active_sales_editor(app_client) -> None:
    caller = await _user("sales_edit")
    colleague = await _user("sales_edit")
    viewer = await _user("sales_view")
    campaign_id = await _campaign()
    payload = _csv(f"Firma {_tag()};Jan Testowy;CTO;{_phone()};;")
    for wrong in (viewer.id, 2_000_000_000):
        refused = await _post(
            app_client, caller, campaign_id, payload, preview=False, assignee=wrong
        )
        assert refused.status_code == 422
    done = await _post(
        app_client, caller, campaign_id, payload, preview=False, assignee=colleague.id
    )
    assert done.status_code == 200 and done.json()["added"] == 1
    assert (await _queue(app_client, colleague))["counts"]["new"] == 1
    assert (await _queue(app_client, caller))["counts"]["new"] == 0


# ── Bramki ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_preview_shows_the_fate_of_every_row_and_saves_nothing(
    app_client,
) -> None:
    caller = await _user("sales_edit")
    other = await _user("sales_edit")
    campaign_id = await _campaign()
    tag = _tag()

    linked_id = await _named_company(f"Bielik Systemy {tag} S.A.")
    by_domain_id = await _named_company(
        f"Stara Nazwa {tag}", domain=f"https://www.sokol-{tag}.example/"
    )
    in_campaign_id = await _named_company(f"Czajka {tag}")
    await _record(caller.id, campaign_id, in_campaign_id, phone="+48 600 300 300")
    own_opp_id = await _named_company(f"Derkacz {tag}")
    await _opportunity(caller.id, own_opp_id, stage="offer-sent")
    busy_id = await _named_company(f"Dudek {tag}")
    await _record(other.id, await _campaign(), busy_id, state="offer_sent")
    led_id = await _named_company(f"Gil {tag}")
    await _opportunity(other.id, led_id, stage="qualified")
    client_name = f"Jemiołuszka Bank {tag}"
    async with AsyncSessionLocal() as db:
        db.add(Client(name=client_name))
        await db.commit()
    objected_id = await _named_company(f"Kowalik {tag}")
    await _contact(
        objected_id,
        full_name="Ewa Sprzeciw",
        do_not_contact_at=datetime.now(timezone.utc),
    )
    silenced_id = await _named_company(f"Krogulec {tag}", status="do_not_contact")
    assert silenced_id

    payload = _csv(
        f"Nowa Firma {tag};Adam Nowy;CTO;600 400 001;adam@nowa-{tag}.example;",
        f"Bielik Systemy {tag} sp. z o.o.;Ola Znana;CIO;600 400 002;;",
        f"Sokół {tag};Piotr Domena;IT;600 400 003;piotr@sokol-{tag}.example;",
        f"Czajka {tag};;;600300300;;",
        f"Nowa Firma {tag};Adam Nowy;CTO;600 400 001;;",
        f"Derkacz {tag};Jan Mój;CTO;600 400 004;;",
        f"Dudek {tag};Jan Cudzy;CTO;600 400 005;;",
        f"Gil {tag};Jan Prowadzony;CTO;600 400 006;;",
        f"{client_name};Jan Klient;CTO;600 400 007;;",
        f"Kowalik {tag};Ewa Sprzeciw;CFO;600 400 008;;",
        f"Krogulec {tag};Jan Cichy;CTO;600 400 009;;",
        f"Łozówka {tag};Jan Bez;CTO;;;",
    )
    body, fates = await _fates(app_client, caller, campaign_id, payload)
    assert [fate for fate, _detail in fates] == [
        "new_company",
        "linked",
        "linked",
        "already_in_campaign",
        "already_in_campaign",
        "already_in_campaign",
        "other_caller",
        "other_caller",
        "client",
        "do_not_contact",
        "do_not_contact",
        "no_phone",
    ]
    details = [detail for _fate, detail in fates]
    assert f"nowa-{tag}.example" in details[0] and "dojdzie nowa osoba" in details[0]
    assert "po nazwie" in details[1]
    assert "po domenie" in details[2]
    assert details[3] == IN_CAMPAIGN_DETAIL
    assert details[4] == REPEATED_DETAIL
    assert "Oferta wysłana" in details[5]
    assert other.name in details[6]
    assert "Lead kwalifikowany" in details[7] and other.name in details[7]
    assert client_name in details[8] and "Delivery Lead" in details[8]
    assert details[9] == details[10] == OBJECTION_DETAIL
    assert details[11] == NO_PHONE_DETAIL
    assert (body["total"], body["addable"], body["to_decide"]) == (12, 3, 6)
    assert body["counts"] == {
        "new_company": 1,
        "linked": 2,
        "already_in_campaign": 3,
        "other_caller": 2,
        "client": 1,
        "do_not_contact": 2,
        "no_phone": 1,
    }
    assert [row["to_decide"] for row in body["rows"]] == [False] * 6 + [True] * 6
    assert body["rows"][0]["line"] == 2
    # Podgląd niczego nie zapisał.
    assert await _record_count(campaign_id) == 1
    async with AsyncSessionLocal() as db:
        assert (
            await db.scalar(
                select(SalesCompany.id).where(
                    SalesCompany.normalized_name
                    == normalize_company_name(f"Nowa Firma {tag}")
                )
            )
        ) is None
    assert linked_id and by_domain_id


@pytest.mark.asyncio
async def test_import_adds_only_rows_that_passed_the_gates(app_client) -> None:
    caller = await _user("sales_edit")
    campaign_id = await _campaign()
    tag = _tag()
    linked_id = await _named_company(f"Bielik Systemy {tag}")
    known_contact = await _contact(
        linked_id, full_name="Ola Znana", email=f"ola@bielik-{tag}.example", phone=None
    )
    client_name = f"Jemiołuszka Bank {tag}"
    async with AsyncSessionLocal() as db:
        db.add(Client(name=client_name))
        await db.commit()
    payload = _csv(
        f"Nowa Firma {tag};Adam Nowy;CTO;600 400 001;adam@nowa-{tag}.example;",
        f"Nowa Firma {tag};Beata Druga;CFO;600 400 002;;",
        f"Bielik Systemy {tag};Ola Znana;CIO;600 400 003;ola@bielik-{tag}.example;",
        f"{client_name};Jan Klient;CTO;600 400 007;;",
        f"Łozówka {tag};Jan Bez;CTO;;;",
    )
    resp = await _post(app_client, caller, campaign_id, payload, preview=False)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["added"], body["total"]) == (3, 5)
    assert body["counts"]["client"] == 1 and body["counts"]["no_phone"] == 1

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
        assert [r.person_name for r in records] == [
            "Adam Nowy",
            "Beata Druga",
            "Ola Znana",
        ]
        assert {r.state for r in records} == {"new"}
        assert {r.contact_source for r in records} == {SOURCE}
        assert {r.assigned_user_id for r in records} == {caller.id}
        # Dwa wiersze nowej firmy dostają jedną kartę, z domeną z adresu osoby.
        assert records[0].company_id == records[1].company_id
        new_company = await db.get(SalesCompany, records[0].company_id)
        assert (new_company.domain, new_company.source) == (
            f"nowa-{tag}.example",
            "call_campaign",
        )
        assert new_company.created_by_user_id == caller.id
        new_contact = await db.get(SalesContact, records[0].contact_id)
        assert (new_contact.full_name, new_contact.title, new_contact.source) == (
            "Adam Nowy",
            "CTO",
            "call_campaign",
        )
        # Istniejąca karta i osoba zostają te same; pusta domena się uzupełnia.
        assert (records[2].company_id, records[2].contact_id) == (
            linked_id,
            known_contact,
        )
        assert (await db.get(SalesCompany, linked_id)).domain == f"bielik-{tag}.example"
        assert (
            await db.scalar(
                select(SalesCompany.id).where(
                    SalesCompany.normalized_name == normalize_company_name(client_name)
                )
            )
        ) is None

    queue = await _queue(app_client, caller)
    assert queue["counts"]["new"] == 3
    assert queue["new"][0]["campaign"]["id"] == campaign_id
    # Ten sam plik drugi raz niczego nie dubluje.
    again = await _post(app_client, caller, campaign_id, payload, preview=False)
    assert again.json()["added"] == 0
    assert again.json()["counts"]["already_in_campaign"] == 3
    assert await _record_count(campaign_id) == 3


@pytest.mark.asyncio
async def test_objection_follows_the_person_to_another_company(app_client) -> None:
    caller = await _user("sales_edit")
    campaign_id = await _campaign()
    tag = _tag()
    phone = f"7{uuid.uuid4().int % 10**8:08d}"
    await _contact(
        await _company(),
        full_name="Ewa Sprzeciw",
        phone=phone,
        do_not_contact_at=datetime.now(timezone.utc),
    )
    closed_phone = f"8{uuid.uuid4().int % 10**8:08d}"
    await _record(
        caller.id,
        await _campaign(),
        await _company(),
        state="do_not_contact",
        phone=closed_phone,
    )
    payload = _csv(
        f"Inna Firma {tag};Ewa Sprzeciw;CFO;+48 {phone};;",
        f"Trzecia Firma {tag};Jan Zamknięty;CTO;{closed_phone};;",
    )
    _body, fates = await _fates(app_client, caller, campaign_id, payload)
    assert fates == [("do_not_contact", OBJECTION_DETAIL)] * 2
    done = await _post(app_client, caller, campaign_id, payload, preview=False)
    assert done.json()["added"] == 0


@pytest.mark.asyncio
async def test_closed_opportunity_of_another_caller_does_not_block_the_company(
    app_client,
) -> None:
    caller = await _user("sales_edit")
    other = await _user("sales_edit")
    tag = _tag()
    company_id = await _named_company(f"Kwiczoł {tag}")
    opp_id = await _opportunity(other.id, company_id)
    logged = await app_client.post(
        f"{URL}/opportunities/{opp_id}/outcome",
        json={"outcome": "no_answer"},
        headers=_headers(other),
    )
    assert logged.status_code == 200, logged.text
    payload = _csv(f"Kwiczoł {tag};Jan Wolny;CTO;{_phone()};;")
    _body, fates = await _fates(app_client, caller, await _campaign(), payload)
    assert [fate for fate, _ in fates] == ["other_caller"]
    # Szansa przegrana: jej rekord kolejki nie trzyma już firmy u tamtej osoby.
    async with AsyncSessionLocal() as db:
        (await db.get(SalesOpportunity, opp_id)).status = "lost"
        await db.commit()
    _body, fates = await _fates(app_client, caller, await _campaign(), payload)
    assert [fate for fate, _ in fates] == ["linked"]


@pytest.mark.asyncio
async def test_joined_alias_and_linked_client_card_are_recognised(app_client) -> None:
    caller = await _user("sales_edit")
    campaign_id = await _campaign()
    tag = _tag()
    card_id = await _named_company(f"Pustułka Group {tag}")
    alias = f"Dawna Pustułka {tag}"
    async with AsyncSessionLocal() as db:
        db.add(
            SalesCompanyAlias(
                company_id=card_id,
                alias=alias,
                normalized_alias=normalize_company_name(alias),
                status="joined",
            )
        )
        client = Client(name=f"Zupełnie Inna Nazwa {tag}")
        db.add(client)
        await db.flush()
        linked = SalesCompany(
            name=f"Rybitwa {tag}",
            normalized_name=normalize_company_name(f"Rybitwa {tag}"),
            client_id=client.id,
        )
        db.add(linked)
        await db.commit()
    payload = _csv(
        f"{alias};Jan Alias;CTO;600 400 001;;",
        f"Rybitwa {tag};Jan Powiązany;CTO;600 400 002;;",
        "B2B NET;Jan Nasz;CTO;600 400 003;;",
    )
    _body, fates = await _fates(app_client, caller, campaign_id, payload)
    assert [fate for fate, _ in fates] == ["linked", "client", "client"]
    assert f"Zupełnie Inna Nazwa {tag}" in fates[1][1]
    assert fates[2][1] == "To nasza firma, do kolejki nie trafia."
