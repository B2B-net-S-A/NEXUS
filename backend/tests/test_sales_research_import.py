"""Sprzedaż → lista osób z researchu do map Fabryk IT (``…/it-factories/research-import``).

Przegląd przed zapisem (dopasowanie firmy, wybór karty, klient NEXUSA, osoba już
na mapie) i akceptacja (osoba na mapie, konto i karta, gdy ich brak, historia).
Dane są fikcyjne, a nazwy niosą losowy tag: baza testowa jest wspólna.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest
from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal
from app.models.client import Client
from app.models.sales import (
    SalesCompany,
    SalesContact,
    SalesOpportunity,
    SalesOpportunityEvent,
    SalesPipelineStage,
)
from app.models.team_structure import DeliveryLeadClientAssignment
from app.services.company_names import normalize_company_name
from app.services.sales import research_file, research_import
from app.services.sales.decision_map import decision_entries
from tests.test_integrations_companies_db import _candidate
from tests.test_sales_companies_api import _headers, _user
from tests.test_sales_factories import (
    FIRST_CONTACT,
    LOST,
    _account,
    _company,
    _person,
    _stage_ids,
)

URL = "/api/sales/it-factories/research-import"
HEADER = "Firma;Imię i nazwisko;Stanowisko;E-mail;LinkedIn;Pewność;Strona www"
SOURCE = "Lista testowa z researchu"
WIP = research_import.NEW_ACCOUNT_STAGE_KEY


def _tag() -> str:
    return uuid.uuid4().hex[:10]


def _csv(*rows: str, header: str = HEADER) -> bytes:
    return "\n".join((header, *rows)).encode("utf-8")


async def _preview(app_client, user, payload: bytes, filename: str = "lista.csv"):
    return await app_client.post(
        f"{URL}/preview",
        files={"file": (filename, payload, "text/csv")},
        headers=_headers(user),
    )


async def _plan(app_client, user, payload: bytes) -> dict[str, Any]:
    resp = await _preview(app_client, user, payload)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _person_in(row: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    """Wiersz przeglądu odesłany do zapisu, jak robi to ekran."""

    fields = (
        "line",
        "company",
        "name",
        "role_in_company",
        "email",
        "phone",
        "linkedin_url",
        "source_url",
        "domain",
        "notes",
        "confidence",
        "decision_level",
    )
    return {**{field: row[field] for field in fields}, **overrides}


async def _accept(app_client, user, people: list[dict[str, Any]], **body: Any):
    return await app_client.post(
        f"{URL}/people",
        json={"source_label": SOURCE, "people": people, **body},
        headers=_headers(user),
    )


async def _outcomes(app_client, user, people: list[dict[str, Any]], **body: Any):
    resp = await _accept(app_client, user, people, **body)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _wip_stage_id() -> int:
    """Etap „Mapa decyzyjna w trakcie”, na którym zaczyna nowe konto z listy."""

    pipeline_id, stages = await _stage_ids()
    async with AsyncSessionLocal() as db:
        stage = await db.scalar(
            select(SalesPipelineStage).where(
                SalesPipelineStage.pipeline_id == pipeline_id,
                SalesPipelineStage.key == WIP,
            )
        )
        if stage is None:
            stage = SalesPipelineStage(
                pipeline_id=pipeline_id,
                key=WIP,
                name="Mapa decyzyjna w trakcie",
                position=1,
                probability=5,
                outcome="open",
            )
            db.add(stage)
            await db.commit()
        return stage.id


async def _map(opportunity_id: int) -> list[dict[str, Any]]:
    async with AsyncSessionLocal() as db:
        opp = await db.get(SalesOpportunity, opportunity_id)
        return decision_entries(opp.custom_fields)


async def _events(opportunity_id: int) -> list[SalesOpportunityEvent]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.execute(
                    select(SalesOpportunityEvent)
                    .where(SalesOpportunityEvent.opportunity_id == opportunity_id)
                    .order_by(SalesOpportunityEvent.id)
                )
            ).scalars()
        )


async def _cards_named(name: str) -> list[SalesCompany]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.execute(
                    select(SalesCompany).where(
                        SalesCompany.normalized_name == normalize_company_name(name)
                    )
                )
            ).scalars()
        )


def _company_of(plan: dict[str, Any], name: str) -> dict[str, Any]:
    return next(c for c in plan["companies"] if c["name"] == name)


# ── Dostęp ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_import_needs_sales_edit(app_client) -> None:
    payload = _csv("Firma Testowa;Jan Fikcyjny;Manager;;;;")
    person = {"line": 2, "company": "Firma Testowa", "name": "Jan Fikcyjny"}
    for user in (await _user(), await _user("sales_view")):
        preview = await _preview(app_client, user, payload)
        assert preview.status_code == 403
        assert preview.json()["detail"]["code"] == "permission_denied"
        accept = await _accept(app_client, user, [person])
        assert accept.status_code == 403
        assert accept.json()["detail"]["code"] == "permission_denied"
    assert await _cards_named("Firma Testowa") == []


# ── Plik ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bad_rows_are_listed_and_the_rest_is_planned(app_client) -> None:
    rep = await _user("sales_edit")
    tag = _tag()
    payload = _csv(
        f"Perkoz {tag};Jan Fikcyjny;Head of Data;jan@;javascript:alert(1);Pewne;",
        f";Bez Firmy {tag};Manager;;;;",
        f"Perkoz {tag};;Manager;;;;",
        f"Perkoz {tag};Ewa Zmyślona;Data Manager;;;;",
    )

    plan = await _plan(app_client, rep, payload)

    assert [(row["line"], row["reason"]) for row in plan["skipped"]] == [
        (3, research_file.NO_COMPANY_REASON),
        (4, research_file.NO_PERSON_REASON),
    ]
    first, second = plan["rows"]
    assert (first["name"], first["confidence"], first["decision_level"]) == (
        "Jan Fikcyjny",
        "confirmed",
        2,
    )
    # Zły adres i link odpadają z ostrzeżeniem, wiersz zostaje.
    assert (first["email"], first["linkedin_url"]) == (None, None)
    assert len(first["warnings"]) == 2
    assert (second["confidence"], second["decision_level"]) == ("to_verify", 3)


@pytest.mark.asyncio
async def test_a_file_that_is_not_a_list_is_refused(app_client) -> None:
    rep = await _user("sales_edit")
    wrong_type = await _preview(app_client, rep, b"%PDF", filename="lista.pdf")
    assert wrong_type.status_code == 422
    assert wrong_type.json()["detail"] == research_file.BAD_TYPE_DETAIL
    no_person = await _preview(app_client, rep, "Firma\nPerkoz\n".encode())
    assert no_person.json()["detail"] == research_file.NO_PERSON_COLUMN_DETAIL
    too_big = await _preview(app_client, rep, b"x" * (research_file.MAX_FILE_BYTES + 1))
    assert too_big.status_code == 413


# ── Przegląd: stan firmy ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_preview_shows_the_account_card_and_missing_company(app_client) -> None:
    rep = await _user("sales_edit")
    tag = _tag()
    with_account = f"Kormoran {tag}"
    card_only = f"Zimorodek {tag}"
    unknown = f"Derkacz {tag}"
    account_id, account_company = await _account(
        [_person("Prezes", 1, "first_contact"), _person("Dyrektor", 2)],
        company_id=await _company(with_account),
        stage=FIRST_CONTACT,
    )
    card_id = await _company(card_only)
    async with AsyncSessionLocal() as db:
        db.add(SalesContact(company_id=card_id, full_name=f"Kontakt {tag}"))
        await db.commit()

    plan = await _plan(
        app_client,
        rep,
        _csv(
            f"{with_account} S.A.;Jan Fikcyjny;Manager;;;;",
            f"{card_only};Ewa Zmyślona;Manager;;;;",
            f"{unknown};Adam Wymyślony;Manager;;;;",
        ),
    )

    account = _company_of(plan, f"{with_account} S.A.")
    assert (account["state"], account["company_id"]) == ("account", account_company)
    [card] = account["cards"]
    assert card["exact"] is True
    assert card["account"] == {
        "opportunity_id": account_id,
        "title": "Konto testowe",
        "stage_name": "Pierwszy kontakt",
        "status": "open",
        "map_total": 2,
        "map_contacted": 1,
    }

    bare = _company_of(plan, card_only)
    assert (bare["state"], bare["company_id"]) == ("card", card_id)
    assert (bare["cards"][0]["account"], bare["cards"][0]["contacts"]) == (None, 1)

    missing = _company_of(plan, unknown)
    assert (missing["state"], missing["company_id"], missing["cards"]) == (
        "no_card",
        None,
        [],
    )
    assert {row["person"] for row in plan["rows"]} == {"new"}


@pytest.mark.asyncio
async def test_several_cards_of_one_brand_wait_for_a_choice(app_client) -> None:
    rep = await _user("sales_edit")
    tag = _tag()
    brand = f"Rybolow{tag}"
    plain = await _company(brand)
    group = await _company(f"{brand} Group")
    poland = await _company(f"{brand} Polska")
    twin_a = await _company(f"Blizniak{tag}")
    twin_b = await _company(f"Blizniak{tag}")
    # Inna firma, która tylko zaczyna się tak samo, nie jest kartą marki.
    await _company(f"{brand}owski Transport")
    account_id, _ = await _account([_person("Prezes", 1)], company_id=group)

    plan = await _plan(
        app_client,
        rep,
        _csv(
            f"{brand};Jan Fikcyjny;Manager;;;;",
            f"{brand} Polska;Ewa Zmyślona;Manager;;;;",
            f"Blizniak{tag};Adam Wymyślony;Manager;;;;",
        ),
    )

    # Dokładna karta jest jedna, ale konto w lejku ma inna karta tej marki.
    by_brand = _company_of(plan, brand)
    assert (by_brand["state"], by_brand["company_id"]) == ("choose", None)
    assert {card["id"] for card in by_brand["cards"]} == {plain, group, poland}
    assert [card["id"] for card in by_brand["cards"] if card["exact"]] == [plain]
    assert by_brand["cards"][0]["id"] == plain
    assert next(c for c in by_brand["cards"] if c["id"] == group)["account"][
        "opportunity_id"
    ] == (account_id)
    assert _company_of(plan, f"{brand} Polska")["state"] == "choose"
    # Dwie karty o tej samej nazwie: też wybór.
    twins = _company_of(plan, f"Blizniak{tag}")
    assert twins["state"] == "choose"
    assert {card["id"] for card in twins["cards"]} == {twin_a, twin_b}


@pytest.mark.asyncio
async def test_archived_account_and_blocked_company(app_client) -> None:
    rep = await _user("sales_edit")
    tag = _tag()
    archived_name = f"Bielik {tag}"
    blocked_name = f"Puszczyk {tag}"
    archived_opp, archived_company = await _account(
        [_person("Prezes", 1)], company_id=await _company(archived_name)
    )
    async with AsyncSessionLocal() as db:
        opp = await db.get(SalesOpportunity, archived_opp)
        opp.archived_at = func.now()
        await db.commit()
    await _company(blocked_name, status="do_not_contact")

    plan = await _plan(
        app_client,
        rep,
        _csv(
            f"{archived_name};Jan Fikcyjny;Manager;;;;",
            f"{blocked_name};Ewa Zmyślona;Manager;;;;",
        ),
    )

    archived = _company_of(plan, archived_name)
    assert (archived["state"], archived["company_id"]) == ("card", archived_company)
    assert archived["cards"][0]["archived_account"] is True
    assert _company_of(plan, blocked_name)["state"] == "blocked"

    people = [_person_in(row) for row in plan["rows"]]
    body = await _outcomes(app_client, rep, people)
    added, refused = body["outcomes"]
    # Konto w archiwum zostaje w archiwum: osoba dostaje nowe.
    assert (added["result"], added["created_account"]) == ("added", True)
    assert added["opportunity_id"] != archived_opp
    assert (refused["result"], refused["detail"]) == (
        "blocked",
        research_import.BLOCKED_DETAIL,
    )


@pytest.mark.asyncio
async def test_nexus_client_gets_neither_person_nor_account(app_client) -> None:
    rep = await _user("sales_edit")
    lead = await _user(role="delivery_lead")
    tag = _tag()
    by_name = f"Klient Dudek {tag}"
    linked_name = f"Karta Dzierzba {tag}"
    async with AsyncSessionLocal() as db:
        named = Client(name=by_name)
        linked = Client(name=f"Klient Powiazany {tag}")
        db.add_all([named, linked])
        await db.flush()
        db.add(
            DeliveryLeadClientAssignment(
                delivery_lead_user_id=lead.id, client_id=linked.id
            )
        )
        await db.commit()
        linked_id = linked.id
    linked_card = await _company(linked_name, client_id=linked_id)

    plan = await _plan(
        app_client,
        rep,
        _csv(
            # Klient bez karty w Sprzedaży: rozpoznany po samej nazwie.
            f"{by_name} Sp. z o.o.;Jan Fikcyjny;Manager;;;;",
            f"{linked_name};Ewa Zmyślona;Manager;;;;",
        ),
    )

    named_plan = _company_of(plan, f"{by_name} Sp. z o.o.")
    assert (named_plan["state"], named_plan["client"]) == (
        "client",
        {"name": by_name, "delivery_lead": None},
    )
    linked_plan = _company_of(plan, linked_name)
    assert (linked_plan["state"], linked_plan["company_id"]) == ("client", None)
    assert linked_plan["client"] == {
        "name": f"Klient Powiazany {tag}",
        "delivery_lead": lead.name,
    }

    people = [
        _person_in(plan["rows"][0]),
        # Ekran nie wysyła klienta, ale serwer sprawdza kartę przy każdym zapisie.
        _person_in(plan["rows"][1], company_id=linked_card),
    ]
    body = await _outcomes(app_client, rep, people)

    assert [o["result"] for o in body["outcomes"]] == ["client", "client"]
    assert body["outcomes"][1]["client"]["delivery_lead"] == lead.name
    assert lead.name in body["outcomes"][1]["detail"]
    assert (body["added"], body["created_accounts"]) == (0, 0)
    assert await _cards_named(f"{by_name} Sp. z o.o.") == []
    async with AsyncSessionLocal() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(SalesOpportunity)
                .where(SalesOpportunity.company_id == linked_card)
            )
        ) == 0


@pytest.mark.asyncio
async def test_own_company_is_refused(app_client) -> None:
    rep = await _user("sales_edit")
    plan = await _plan(
        app_client, rep, _csv("B2B Network S.A.;Jan Fikcyjny;Manager;;;;")
    )
    assert plan["companies"][0]["state"] == "own_company"
    body = await _outcomes(app_client, rep, [_person_in(plan["rows"][0])])
    assert body["outcomes"][0]["result"] == "own_company"

    # Karta naszej spółki wskazana wprost, pod inną nazwą firmy, też odpada.
    own_card = await _company(f"B2B Network {_tag()}")
    forged = await _outcomes(
        app_client,
        rep,
        [
            {
                "line": 2,
                "company": f"Inna Nazwa {_tag()}",
                "name": "Jan Fikcyjny",
                "company_id": own_card,
            }
        ],
    )
    assert forged["outcomes"][0]["result"] == "own_company"
    async with AsyncSessionLocal() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(SalesOpportunity)
                .where(SalesOpportunity.company_id == own_card)
            )
        ) == 0


# ── Przegląd: osoba ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_person_already_on_the_map_and_repeated_in_the_file(app_client) -> None:
    rep = await _user("sales_edit")
    tag = _tag()
    name = f"Trznadel {tag}"
    account_id, _ = await _account(
        [
            _person("Żółty Józef", 2),
            _person("Inne Nazwisko", 3, email=f"ewa.{tag}@trznadel.example"),
        ],
        company_id=await _company(name),
    )

    plan = await _plan(
        app_client,
        rep,
        _csv(
            # To samo nazwisko w innej kolejności i bez ogonków.
            f"{name};Jozef Zolty;Manager;;;;",
            # Inne nazwisko, ten sam adres.
            f"{name};Ewa Zmyślona;Manager;EWA.{tag}@Trznadel.example;;;",
            f"{name};Adam Wymyślony;Manager;;;;",
            f"{name};Wymyślony Adam;Lead;;;;",
        ),
    )

    assert [row["person"] for row in plan["rows"]] == [
        "on_map",
        "on_map",
        "new",
        "repeated",
    ]
    assert plan["rows"][0]["on_map_opportunity_id"] == account_id

    body = await _outcomes(app_client, rep, [_person_in(row) for row in plan["rows"]])
    assert [o["result"] for o in body["outcomes"]] == [
        "on_map",
        "on_map",
        "added",
        "on_map",
    ]
    assert [entry["name"] for entry in await _map(account_id)] == [
        "Żółty Józef",
        "Inne Nazwisko",
        "Adam Wymyślony",
    ]


# ── Akceptacja ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_accept_adds_the_person_with_source_and_history(app_client) -> None:
    rep = await _user("sales_edit")
    tag = _tag()
    name = f"Remiz {tag}"
    account_id, company_id = await _account(
        [_person("Prezes", 1, "first_contact")], company_id=await _company(name)
    )
    plan = await _plan(
        app_client,
        rep,
        _csv(
            f"{name};Jan Fikcyjny;Head of Data;jan.{tag}@remiz.example;"
            "linkedin.com/in/jan-fikcyjny;Pewne;"
        ),
    )

    body = await _outcomes(app_client, rep, [_person_in(plan["rows"][0])])

    [outcome] = body["outcomes"]
    assert outcome == {
        "line": 2,
        "result": "added",
        "detail": None,
        "company_id": company_id,
        "opportunity_id": account_id,
        "created_company": False,
        "created_account": False,
        "client": None,
    }
    assert (body["added"], body["created_accounts"]) == (1, 0)
    entry = (await _map(account_id))[-1]
    assert entry["name"] == "Jan Fikcyjny"
    assert entry["contact_status"] == "not_contacted"
    assert (entry["role_in_company"], entry["decision_level"]) == ("Head of Data", 2)
    assert entry["email"] == f"jan.{tag}@remiz.example"
    assert entry["linkedin_url"] == "https://linkedin.com/in/jan-fikcyjny"
    assert entry["source"] == research_import.SOURCE
    assert entry["source_label"] == SOURCE
    assert entry["source_confidence"] == "confirmed"
    assert len(entry["source_added_at"]) == 10

    [event] = await _events(account_id)
    assert (event.field, event.user_id, event.old_value) == (
        "decision_map",
        rep.id,
        None,
    )
    assert event.new_value.startswith("Jan Fikcyjny (")
    assert f"źródło: {SOURCE}" in event.new_value

    # Poprawka z okna osoby zachowuje pochodzenie wpisu.
    detail = (
        await app_client.get(
            f"/api/sales/opportunities/{account_id}", headers=_headers(rep)
        )
    ).json()
    shown = detail["atlas_motion"]["it_factory"]["decision_map"][-1]
    patched = await app_client.patch(
        f"/api/sales/opportunities/{account_id}/decision-map/{shown['key']}",
        json={"contact_status": "first_contact"},
        headers=_headers(rep),
    )
    assert patched.status_code == 200, patched.text
    after = (await _map(account_id))[-1]
    assert after["contact_status"] == "first_contact"
    assert (after["source"], after["source_label"]) == (research_import.SOURCE, SOURCE)

    # Ta sama lista drugi raz niczego nie dopisuje.
    again = await _outcomes(app_client, rep, [_person_in(plan["rows"][0])])
    assert again["outcomes"][0]["result"] == "on_map"
    assert len(await _map(account_id)) == 2


@pytest.mark.asyncio
async def test_accept_opens_an_account_for_a_card_without_one(app_client) -> None:
    rep = await _user("sales_edit")
    wip_stage = await _wip_stage_id()
    tag = _tag()
    name = f"Pliszka {tag}"
    company_id = await _company(name)
    plan = await _plan(app_client, rep, _csv(f"{name};Jan Fikcyjny;Director;;;;"))
    assert _company_of(plan, name)["state"] == "card"

    body = await _outcomes(app_client, rep, [_person_in(plan["rows"][0])])

    [outcome] = body["outcomes"]
    assert (outcome["result"], outcome["company_id"]) == ("added", company_id)
    assert (outcome["created_company"], outcome["created_account"]) == (False, True)
    async with AsyncSessionLocal() as db:
        opp = await db.get(SalesOpportunity, outcome["opportunity_id"])
        assert (opp.company_id, opp.stage_id, opp.status) == (
            company_id,
            wip_stage,
            "open",
        )
        assert (opp.title, opp.owner_user_id, opp.source) == (
            name,
            rep.id,
            research_import.SOURCE,
        )
    created, person = await _events(outcome["opportunity_id"])
    assert (created.kind, created.field, created.new_value) == (
        "created",
        "stage_id",
        str(wip_stage),
    )
    assert person.field == "decision_map"

    # Konto jest w lejku: lista kont i kolejka widzą nową osobę.
    queue = (
        await app_client.get("/api/sales/it-factories/queue", headers=_headers(rep))
    ).json()
    [queued] = [
        row
        for row in queue["people"]
        if row["opportunity"]["id"] == outcome["opportunity_id"]
    ]
    assert queued["person"]["name"] == "Jan Fikcyjny"
    assert queued["person"]["source_label"] == SOURCE


@pytest.mark.asyncio
async def test_accept_creates_one_card_with_domain_for_a_new_company(
    app_client,
) -> None:
    rep = await _user("sales_edit")
    await _wip_stage_id()
    tag = _tag()
    name = f"Świergotek {tag} Sp. z o.o."
    plan = await _plan(
        app_client,
        rep,
        _csv(
            f"{name};Jan Fikcyjny;Manager;jan@swiergotek-{tag}.example;;;",
            f"{name};Ewa Zmyślona;Team Lead;;;;https://www.swiergotek-{tag}.example/",
        ),
    )
    assert _company_of(plan, name)["state"] == "no_card"

    body = await _outcomes(app_client, rep, [_person_in(row) for row in plan["rows"]])

    first, second = body["outcomes"]
    assert (first["created_company"], first["created_account"]) == (True, True)
    # Druga osoba tej samej firmy trafia na tę samą nową kartę i konto.
    assert (second["created_company"], second["created_account"]) == (False, False)
    assert (second["company_id"], second["opportunity_id"]) == (
        first["company_id"],
        first["opportunity_id"],
    )
    assert (body["added"], body["created_companies"], body["created_accounts"]) == (
        2,
        1,
        1,
    )
    [card] = await _cards_named(name)
    assert (card.id, card.name, card.domain) == (
        first["company_id"],
        name,
        f"swiergotek-{tag}.example",
    )
    assert (card.source, card.owner_user_id) == (research_import.SOURCE, rep.id)
    assert [e["name"] for e in await _map(first["opportunity_id"])] == [
        "Jan Fikcyjny",
        "Ewa Zmyślona",
    ]

    # Ponowne wgranie listy: karta i konto już są, osoby są na mapie.
    replan = await _plan(app_client, rep, _csv(f"{name};Jan Fikcyjny;Manager;;;;"))
    assert _company_of(replan, name)["state"] == "account"
    assert replan["rows"][0]["person"] == "on_map"


@pytest.mark.asyncio
async def test_two_accepts_at_once_do_not_open_two_cards_or_accounts(
    app_client,
) -> None:
    """Dwa wiersze tej samej nowej firmy kliknięte jeden po drugim to dwa żądania naraz."""

    rep = await _user("sales_edit")
    await _wip_stage_id()
    tag = _tag()
    name = f"Zniczek {tag}"
    card_only = f"Sikora {tag}"
    card_id = await _company(card_only)

    def person(line: int, company: str, who: str) -> dict[str, Any]:
        return {"line": line, "company": company, "name": who}

    responses = await asyncio.gather(
        _accept(app_client, rep, [person(2, name, "Jan Fikcyjny")]),
        _accept(app_client, rep, [person(3, name, "Ewa Zmyślona")]),
        _accept(app_client, rep, [person(4, card_only, "Adam Wymyślony")]),
        _accept(app_client, rep, [person(5, card_only, "Olga Zmyślna")]),
    )

    outcomes = [resp.json()["outcomes"][0] for resp in responses]
    assert [o["result"] for o in outcomes] == ["added"] * 4
    [card] = await _cards_named(name)
    assert {outcomes[0]["company_id"], outcomes[1]["company_id"]} == {card.id}
    assert outcomes[0]["opportunity_id"] == outcomes[1]["opportunity_id"]
    assert outcomes[2]["opportunity_id"] == outcomes[3]["opportunity_id"]
    async with AsyncSessionLocal() as db:
        for company_id in (card.id, card_id):
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(SalesOpportunity)
                    .where(SalesOpportunity.company_id == company_id)
                )
            ) == 1
    assert {e["name"] for e in await _map(outcomes[0]["opportunity_id"])} == {
        "Jan Fikcyjny",
        "Ewa Zmyślona",
    }


@pytest.mark.asyncio
async def test_chosen_card_gets_the_person_and_no_choice_is_refused(app_client) -> None:
    rep = await _user("sales_edit")
    tag = _tag()
    name = f"Czeczotka{tag}"
    twin_a = await _company(name)
    twin_b = await _company(name)
    account_id, _ = await _account([], company_id=twin_b, stage=LOST, status="lost")
    plan = await _plan(app_client, rep, _csv(f"{name};Jan Fikcyjny;Manager;;;;"))
    row = plan["rows"][0]

    refused = await _outcomes(app_client, rep, [_person_in(row)])
    assert refused["outcomes"][0]["result"] == "choose_card"
    assert refused["outcomes"][0]["detail"] == research_import.CHOOSE_CARD_DETAIL

    missing = await _outcomes(app_client, rep, [_person_in(row, company_id=2**31 - 1)])
    assert missing["outcomes"][0]["result"] == "card_missing"

    chosen = await _outcomes(app_client, rep, [_person_in(row, company_id=twin_b)])
    [outcome] = chosen["outcomes"]
    # Zamknięte konto dalej jest kontem tej firmy w lejku: drugie nie powstaje.
    assert (outcome["result"], outcome["opportunity_id"]) == ("added", account_id)
    assert outcome["created_account"] is False
    async with AsyncSessionLocal() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(SalesOpportunity)
                .where(SalesOpportunity.company_id == twin_a)
            )
        ) == 0


@pytest.mark.asyncio
async def test_one_bad_row_does_not_undo_the_others(app_client) -> None:
    rep = await _user("sales_edit")
    tag = _tag()
    name = f"Pokrzewka {tag}"
    account_id, _ = await _account([], company_id=await _company(name))
    plan = await _plan(
        app_client,
        rep,
        _csv(
            f"{name};Jan Fikcyjny;Manager;;;;",
            f"{name};Ewa Zmyślona;Manager;;;;",
            f"{name};Adam Wymyślony;Manager;;;;",
        ),
    )
    people = [_person_in(row) for row in plan["rows"]]
    # Adres, którego mapa nie przyjmuje: ten wiersz odpada, pozostałe zostają.
    people[1]["email"] = "@"

    body = await _outcomes(app_client, rep, people)

    assert [o["result"] for o in body["outcomes"]] == ["added", "error", "added"]
    assert body["outcomes"][1]["detail"] == research_import.ERROR_DETAIL
    assert [e["name"] for e in await _map(account_id)] == [
        "Jan Fikcyjny",
        "Adam Wymyślony",
    ]


@pytest.mark.asyncio
async def test_accept_validates_source_owner_and_links(app_client) -> None:
    rep = await _user("sales_edit")
    colleague = await _user("sales_edit")
    viewer = await _user("sales_view")
    await _wip_stage_id()
    tag = _tag()
    person = {"line": 2, "company": f"Makolągwa {tag}", "name": "Jan Fikcyjny"}

    no_source = await app_client.post(
        f"{URL}/people",
        json={"source_label": "  ", "people": [person]},
        headers=_headers(rep),
    )
    assert no_source.status_code == 422
    bad_link = await _accept(
        app_client, rep, [{**person, "source_url": "javascript:alert(1)"}]
    )
    assert bad_link.status_code == 422
    unknown_field = await _accept(app_client, rep, [{**person, "contact_status": "x"}])
    assert unknown_field.status_code == 422
    # Opiekunem nowych kont nie zostaje konto bez „Sprzedaż: edycja”.
    wrong_owner = await _accept(app_client, rep, [person], owner_user_id=viewer.id)
    assert wrong_owner.status_code == 422
    assert (
        wrong_owner.json()["detail"]
        == "Opiekunem nowych kont może być aktywna osoba z uprawnieniem „Sprzedaż: edycja”."
    )
    assert await _cards_named(person["company"]) == []

    body = await _outcomes(
        app_client,
        rep,
        [{**person, "name": "Jan‮ Fikcyjny\x07"}],
        owner_user_id=colleague.id,
    )
    [outcome] = body["outcomes"]
    assert outcome["result"] == "added"
    async with AsyncSessionLocal() as db:
        opp = await db.get(SalesOpportunity, outcome["opportunity_id"])
        assert (opp.owner_user_id, opp.created_by_user_id) == (colleague.id, rep.id)
    # Znaki sterujące nie trafiają na mapę.
    assert (await _map(outcome["opportunity_id"]))[0]["name"] == "Jan Fikcyjny"


# ── „Znamy teraz” ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_preview_counts_known_people_like_the_accounts_list(app_client) -> None:
    rep = await _user("sales_edit")
    tag = _tag()
    name = f"Raniuszek Software {tag}"
    unknown = f"Mysikrolik {tag}"
    async with AsyncSessionLocal() as db:
        await _candidate(
            db,
            f"Teraz{tag}",
            experience=[
                {"company": f"{name} sp. z o.o.", "start": "2024", "end": None}
            ],
        )
        await _candidate(
            db,
            f"Kiedys{tag}",
            experience=[{"company": name, "start": "2018", "end": "2020"}],
        )
        await db.commit()
    company_id = await _company(name)
    await _account([_person("Prezes", 1)], company_id=company_id)

    plan = await _plan(
        app_client,
        rep,
        _csv(
            f"{name};Jan Fikcyjny;Manager;;;;",
            f"{unknown};Ewa Zmyślona;Manager;;;;",
        ),
    )

    assert (plan["known_failed"], plan["known_truncated"]) == (False, False)
    [card] = _company_of(plan, name)["cards"]
    assert (card["known_current"], card["known_past"]) == (1, 1)
    listed = (
        await app_client.get(
            "/api/sales/it-factories/known-people", headers=_headers(rep)
        )
    ).json()["items"]
    on_list = next(row for row in listed if row["company_id"] == company_id)
    assert (on_list["current"], on_list["past"]) == (1, 1)
    # Firma bez karty nie ma czego liczyć.
    assert _company_of(plan, unknown)["cards"] == []
