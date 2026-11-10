"""Sprzedaż → „Kogo znamy”: inne nazwy z CV, kolejność osób, dziennik odczytu (P8).

Nazwy firm niosą losowy tag, bo baza testowa jest wspólna dla przebiegu.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.api import integrations_companies, sales_company_people
from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.activity import Activity
from app.models.client import Client
from app.models.client_directory import ClientAlias
from app.models.contract import ContractStatus
from app.models.sales import SalesCompany, SalesCompanyAlias
from app.services import candidate_audit, candidate_data_access_alerts
from app.services.company_names import normalize_company_name
from app.services.company_people_rank import cv_is_stale, is_decision_role
from app.services.sales import company_aliases
from app.services.sales.company_aliases import CvEntry
from app.services.sales.merge import merge_companies
from tests.test_integrations_companies_db import _candidate, _contract
from tests.test_sales_companies_api import _headers, _user

URL = "/api/sales/companies"


def _tag() -> str:
    return uuid.uuid4().hex[:8]


def _job(company: str, *, role: str = "Tester", start="2024", end=None) -> dict:
    return {"company": company, "role": role, "start": start, "end": end}


async def _card(name: str, **fields) -> int:
    async with AsyncSessionLocal() as db:
        company = SalesCompany(
            name=name, normalized_name=normalize_company_name(name), **fields
        )
        db.add(company)
        await db.commit()
        return company.id


async def _person(lastname: str, *jobs: dict, added: datetime | None = None) -> int:
    async with AsyncSessionLocal() as db:
        person = await _candidate(db, lastname, experience=list(jobs))
        if added is not None:
            person.source_created_at = added
        await db.commit()
        return person.id


async def _people(app_client, company_id: int, user, **params) -> dict:
    resp = await app_client.get(
        f"{URL}/{company_id}/people", headers=_headers(user), params=params
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _decide(app_client, company_id: int, user, name: str, status: str):
    return await app_client.post(
        f"{URL}/{company_id}/people/aliases",
        headers=_headers(user),
        json={"name": name, "status": status},
    )


# ── Reguły bez bazy ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "title",
    ["IT Manager", "Head of Data", "Dyrektor IT", "CTO", "Team Lead", "Menedżer"],
)
def test_decision_roles(title: str) -> None:
    assert is_decision_role(title) is True


@pytest.mark.parametrize(
    "title",
    [
        "Project Manager",
        "Test Manager",
        "Product Owner",
        "Account Manager",
        "Kierownik placówki",
        "Junior Manager",
        "Stażysta u kierownika",
        "Praktykant, Team Lead",
        "Intern Lead",
        "Programista",
        "Leadership Coach",
        "",
        None,
    ],
)
def test_not_decision_roles(title: str | None) -> None:
    assert is_decision_role(title) is False


def test_internal_is_not_an_intern() -> None:
    assert is_decision_role("Internal Audit Manager") is True


def test_cv_is_stale_only_past_three_full_years() -> None:
    today = date(2026, 11, 9)
    assert cv_is_stale(date(2023, 11, 8), today) is True
    assert cv_is_stale(date(2023, 11, 9), today) is False
    assert cv_is_stale(None, today) is False
    # 29 lutego: rok wstecz nie ma takiego dnia, a reguła nie może się wywrócić.
    assert cv_is_stale(date(2021, 2, 27), date(2024, 2, 29)) is True


@pytest.mark.parametrize(
    "raw",
    [
        "Freelance",
        "Self-employed",
        "Własna działalność gospodarcza",
        "Samozatrudnienie",
        "NDA",
        "Bank (NDA)",
        "Poufne",
        "Uniwersytet Warszawski",
        "Warsaw University of Technology",
        "Politechnika Gdańska",
        "Szkoła Podstawowa nr 1",
        "Software Development Academy",
    ],
)
def test_names_that_are_not_employers(raw: str) -> None:
    assert company_aliases.is_non_employer(normalize_company_name(raw)) is True


@pytest.mark.parametrize("raw", ["mBank", "Citibank N.A.", "Bank Pekao", "NDAX"])
def test_real_employers_are_not_dropped(raw: str) -> None:
    assert company_aliases.is_non_employer(normalize_company_name(raw)) is False


@pytest.mark.parametrize(
    "raw", ["B2B Network", "B2BNetwork S.A.", "B2B Net S.A.", "B2B Network - projekty"]
)
def test_own_company_names(raw: str) -> None:
    assert company_aliases.is_own_company(normalize_company_name(raw)) is True


def test_a_similar_name_is_not_the_own_company() -> None:
    assert company_aliases.is_own_company("b2b networking") is False


def test_brand_is_first_distinctive_token_or_the_whole_name() -> None:
    assert company_aliases.brand_of("nordea bank abp") == "nordea"
    assert company_aliases.brand_of("bank pekao") == "bank pekao"
    assert company_aliases.brand_of("pko bank polski") == "pko bank polski"
    assert company_aliases.brand_of("credit agricole") == "credit agricole"
    assert company_aliases.brand_of("narodowy bank polski") == "narodowy"
    assert company_aliases.brand_of("mbank spolka akcyjna") == "mbank"


def _entry(cid: int, company: str, start="2024", end=None) -> CvEntry:
    return CvEntry(candidate_id=cid, company=company, start=start, end=end)


def test_variants_merge_spellings_and_count_people_once() -> None:
    collected = company_aliases.collect(
        [
            _entry(1, "Omega Hipoteczny S.A."),
            _entry(1, "OMEGA HIPOTECZNY", start="2020", end="2021"),
            _entry(2, "Omega Hipoteczny", start=None, end=None),
            _entry(3, "Omegaland"),  # inny wyraz, inna firma
            _entry(4, "Freelance Omega"),
        ],
        seeds={"omega"},
        skip=set(),
    )
    variant = collected.variants["omega hipoteczny"]
    assert variant.people == {1, 2}
    assert variant.current == {1}
    assert "omegaland" not in collected.variants
    assert "freelance omega" not in collected.variants


def test_decided_and_known_names_are_not_proposed_again() -> None:
    collected = company_aliases.collect(
        [_entry(1, "Omega Hipoteczny"), _entry(2, "Omega Leasing")],
        seeds={"omega"},
        skip={"omega leasing"},
    )
    assert set(collected.variants) == {"omega hipoteczny"}


@pytest.mark.parametrize(
    ("seed", "other"),
    [
        ("credit agricole", "Credit Suisse Poland"),
        ("ministerstwo finansow", "Ministerstwo Obrony Narodowej"),
        ("narodowy bank polski", "Narodowy Fundusz Zdrowia"),
        ("krajowa izba rozliczeniowa", "Krajowa Administracja Skarbowa"),
        ("deutsche bank polska", "Deutsche Telekom"),
    ],
)
def test_shared_first_word_is_not_the_same_firm(seed: str, other: str) -> None:
    collected = company_aliases.collect([_entry(1, other)], seeds={seed}, skip=set())
    assert collected.variants == {}


@pytest.mark.parametrize(
    ("seed", "variant"),
    [
        ("credit agricole", "Credit Agricole Bank Polska"),
        ("nordea bank abp", "Nordea Bank Polska"),
        ("nordea bank abp", "Nordea"),
        ("narodowy bank polski", "Narodowy Bank"),
        ("mbank", "mBank Hipoteczny"),
        ("ministerstwo finansow", "Ministerstwo Finansów Departament Podatków"),
    ],
)
def test_real_variants_of_the_card_stay(seed: str, variant: str) -> None:
    collected = company_aliases.collect([_entry(1, variant)], seeds={seed}, skip=set())
    assert list(collected.variants) == [normalize_company_name(variant)]


@pytest.mark.parametrize(
    "raw",
    [
        "Omega, Alfa, Beta",
        "Omega Bank\n12. Alfa Bank\n13. Beta",
        "Omega Polska / Alfa",
    ],
)
def test_list_of_employers_is_not_a_name_variant(raw: str) -> None:
    collected = company_aliases.collect([_entry(1, raw)], seeds={"omega"}, skip=set())
    assert collected.variants == {}


def test_a_generic_one_word_card_proposes_nothing() -> None:
    collected = company_aliases.collect(
        [_entry(1, "Bank Pekao")], seeds={"bank"}, skip=set()
    )
    assert collected.variants == {}


def test_bridge_needs_exactly_two_parts_and_three_people() -> None:
    entries = [
        _entry(1, "Omega (Stara Nazwa S.A.)"),
        _entry(2, "Stara Nazwa SA (Omega)"),
        _entry(3, "Omega / Stara Nazwa"),
        _entry(4, "Omega / Rzadka"),
        _entry(5, "Rzadka (Omega)"),
        _entry(6, "Omega / Jednorazowa"),
        _entry(7, "Omega, Inna, Jeszcze Inna"),
    ]
    bridges = company_aliases.collect(entries, seeds={"omega"}, skip=set()).bridges
    assert company_aliases.supported_bridges(bridges) == ["stara nazwa"]


def test_intermediary_with_other_clients_is_not_a_bridge() -> None:
    entries = [
        _entry(1, "Agencja / Omega"),
        _entry(2, "Omega (Agencja)"),
        _entry(3, "Agencja - Omega"),
        _entry(4, "Agencja / Roche"),
        _entry(5, "Agencja / Pfa"),
        _entry(6, "Agencja / Nykredit"),
        _entry(7, "Agencja / Deltek"),
    ]
    assert (
        company_aliases.names_mostly_bridged(
            entries, ["agencja"], anchors=company_aliases.anchors_of({"omega"})
        )
        == []
    )


def test_old_name_stays_a_bridge_despite_a_few_other_partners() -> None:
    entries = [
        _entry(1, "Stara Nazwa (Omega)"),
        _entry(2, "Omega / Stara Nazwa"),
        _entry(3, "Stara Nazwa SA - Omega"),
        _entry(4, "Stara Nazwa / Dawny Produkt"),
        _entry(5, "Stara Nazwa"),  # bez drugiej części: nic nie mówi o pośrednictwie
    ]
    assert company_aliases.names_mostly_bridged(
        entries, ["stara nazwa"], anchors=company_aliases.anchors_of({"omega"})
    ) == ["stara nazwa"]


def test_rank_gives_top_three_and_a_summary_of_the_rest() -> None:
    collected = company_aliases.collect(
        [
            *[_entry(i, "Omega A") for i in range(1, 6)],
            *[_entry(i, "Omega B") for i in range(1, 5)],
            *[_entry(i, "Omega C") for i in range(1, 4)],
            *[_entry(i, "Omega D") for i in range(1, 3)],
            _entry(1, "Omega E"),
        ],
        seeds={"omega"},
        skip=set(),
    )
    top, rest = company_aliases.rank(collected.variants)
    assert [v.people_count for v in top] == [5, 4, 3]
    assert (rest.count, rest.fewest, rest.most) == (2, 1, 2)


# ── API: nazwy z CV ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_aliases_are_read_beyond_the_ten_name_limit(app_client) -> None:
    editor = await _user("sales_edit")
    tag = _tag()
    company_id = await _card(f"Limit {tag}")
    ids = []
    async with AsyncSessionLocal() as db:
        for index in range(12):
            alias = f"Dawna {index}x {tag}"
            db.add(
                SalesCompanyAlias(
                    company_id=company_id,
                    alias=alias,
                    normalized_alias=normalize_company_name(alias),
                    status="joined",
                )
            )
            person = await _candidate(
                db, f"Osoba{index}{tag}", experience=[_job(alias)]
            )
            ids.append(person.id)
        await db.commit()
    body = await _people(app_client, company_id, editor)
    assert {p["candidate_id"] for p in body["people"]} == set(ids)
    assert body["counts"]["current"] == 12


@pytest.mark.asyncio
async def test_join_recounts_and_undo_restores(app_client) -> None:
    editor = await _user("sales_edit")
    tag = _tag()
    company_id = await _card(f"Omega{tag}")
    await _person(f"Pierwszy{tag}", _job(f"Omega{tag}"))
    second = await _person(f"Drugi{tag}", _job(f"Omega{tag} Hipoteczny"))

    assert (await _people(app_client, company_id, editor))["counts"]["current"] == 1
    resp = await _decide(
        app_client, company_id, editor, f"Omega{tag} Hipoteczny", "joined"
    )
    assert resp.status_code == 200, resp.text
    alias_id = resp.json()["id"]

    joined = await _people(app_client, company_id, editor)
    assert joined["counts"]["current"] == 2
    assert second in {p["candidate_id"] for p in joined["people"]}

    undo = await app_client.delete(
        f"{URL}/{company_id}/people/aliases/{alias_id}", headers=_headers(editor)
    )
    assert undo.status_code == 204, undo.text
    assert (await _people(app_client, company_id, editor))["counts"]["current"] == 1


@pytest.mark.asyncio
async def test_rejected_name_is_not_counted_and_not_proposed(app_client) -> None:
    editor = await _user("sales_edit")
    tag = _tag()
    company_id = await _card(f"Omega{tag}")
    await _person(f"Trzeci{tag}", _job(f"Omega{tag} Budowa"))
    aliases_url = f"{URL}/{company_id}/people/aliases"

    before = await app_client.get(aliases_url, headers=_headers(editor))
    assert before.status_code == 200, before.text
    assert [v["key"] for v in before.json()["suggestions"]] == [
        normalize_company_name(f"Omega{tag} Budowa")
    ]

    resp = await _decide(
        app_client, company_id, editor, f"Omega{tag} Budowa", "rejected"
    )
    assert resp.status_code == 200, resp.text
    after = (await app_client.get(aliases_url, headers=_headers(editor))).json()
    assert after["suggestions"] == []
    assert [d["status"] for d in after["decisions"]] == ["rejected"]
    assert (await _people(app_client, company_id, editor))["counts"]["current"] == 0


@pytest.mark.asyncio
async def test_second_decision_overwrites_the_first(app_client) -> None:
    editor = await _user("sales_edit")
    tag = _tag()
    company_id = await _card(f"Omega{tag}")
    name = f"Omega{tag} Dwa"
    first = await _decide(app_client, company_id, editor, name, "rejected")
    second = await _decide(app_client, company_id, editor, name, "joined")
    assert first.json()["id"] == second.json()["id"]
    assert second.json()["status"] == "joined"


@pytest.mark.asyncio
async def test_suggestions_top_three_own_cards_and_exclusions(app_client) -> None:
    viewer = await _user("sales_view")
    tag = _tag()
    company_id = await _card(f"Omega{tag}")
    own_card = await _card(f"Omega{tag} Leasing")
    for index, (suffix, people) in enumerate(
        (("Alfa", 3), ("Beta", 2), ("Gamma", 2), ("Delta", 1))
    ):
        for number in range(people):
            await _person(f"P{index}{number}{tag}", _job(f"Omega{tag} {suffix}"))
    await _person(f"Karta{tag}", _job(f"Omega{tag} Leasing"))
    await _person(f"Nda{tag}", _job(f"Omega{tag} NDA"))
    await _person(f"Szkola{tag}", _job(f"Omega{tag} Akademia"))

    resp = await app_client.get(
        f"{URL}/{company_id}/people/aliases", headers=_headers(viewer)
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [v["people"] for v in body["suggestions"]] == [3, 2, 2]
    assert body["suggestions"][0]["name"] == f"Omega{tag} Alfa"
    assert body["suggestions"][0]["current"] == 3
    assert (body["other_count"], body["other_min"], body["other_max"]) == (1, 1, 1)
    assert body["own_cards"] == [
        {"id": own_card, "name": f"Omega{tag} Leasing", "current": 1}
    ]
    keys = {v["key"] for v in body["suggestions"]}
    assert not any("nda" in key.split() or "akademia" in key for key in keys)


@pytest.mark.asyncio
async def test_bridged_name_comes_with_its_own_people(app_client) -> None:
    viewer = await _user("sales_view")
    tag = _tag()
    company_id = await _card(f"Omega{tag}")
    old = f"Stara{tag} Nazwa"
    await _person(f"Most1{tag}", _job(f"Omega{tag} ({old} S.A.)"))
    await _person(f"Most2{tag}", _job(f"{old} SA (Omega{tag})"))
    await _person(f"Most3{tag}", _job(f"Omega{tag} / {old}"))
    for number in range(3):
        await _person(f"Dawny{number}{tag}", _job(old, start="2010", end="2012"))

    body = (
        await app_client.get(
            f"{URL}/{company_id}/people/aliases", headers=_headers(viewer)
        )
    ).json()
    bridged = next(
        v for v in body["suggestions"] if v["key"] == normalize_company_name(old)
    )
    assert bridged["people"] == 3
    assert bridged["current"] == 0


@pytest.mark.asyncio
async def test_intermediary_is_not_suggested_as_another_name(app_client) -> None:
    viewer = await _user("sales_view")
    tag = _tag()
    company_id = await _card(f"Omega{tag}")
    agency = f"Agencja{tag}"
    for number in range(3):
        await _person(f"Przez{number}{tag}", _job(f"{agency} / Omega{tag}"))
    for number in range(4):
        await _person(f"Gdzie{number}{tag}", _job(f"{agency} / Klient{number}{tag}"))
    await _person(f"Sama{tag}", _job(agency))

    body = (
        await app_client.get(
            f"{URL}/{company_id}/people/aliases", headers=_headers(viewer)
        )
    ).json()
    assert normalize_company_name(agency) not in {v["key"] for v in body["suggestions"]}


@pytest.mark.asyncio
async def test_saving_needs_sales_edit(app_client) -> None:
    viewer = await _user("sales_view")
    recruiter = await _user()
    company_id = await _card(f"Omega{_tag()}")
    denied = await _decide(app_client, company_id, viewer, "Omega Nowa", "joined")
    assert denied.status_code == 403
    undo = await app_client.delete(
        f"{URL}/{company_id}/people/aliases/1", headers=_headers(viewer)
    )
    assert undo.status_code == 403
    read = await app_client.get(
        f"{URL}/{company_id}/people/aliases", headers=_headers(recruiter)
    )
    assert read.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name", ["Freelance", "NDA", "Uniwersytet Warszawski", "B2B Network", "IT"]
)
async def test_join_refuses_names_that_are_not_a_company_alias(
    app_client, name: str
) -> None:
    editor = await _user("sales_edit")
    company_id = await _card(f"Omega{_tag()}")
    resp = await _decide(app_client, company_id, editor, name, "joined")
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_join_refuses_the_cards_own_name(app_client) -> None:
    editor = await _user("sales_edit")
    name = f"Omega{_tag()}"
    company_id = await _card(name)
    resp = await _decide(app_client, company_id, editor, f"{name} S.A.", "joined")
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_join_refuses_a_name_with_its_own_card(app_client) -> None:
    editor = await _user("sales_edit")
    tag = _tag()
    company_id = await _card(f"Omega{tag}")
    await _card(f"Omega{tag} Leasing")
    resp = await _decide(
        app_client, company_id, editor, f"Omega{tag} Leasing", "joined"
    )
    assert resp.status_code == 409, resp.text
    # „Nie ta firma” przy nazwie z własną kartą nikomu nie szkodzi.
    ok = await _decide(
        app_client, company_id, editor, f"Omega{tag} Leasing", "rejected"
    )
    assert ok.status_code == 200, ok.text


@pytest.mark.asyncio
async def test_alias_of_another_company_cannot_be_undone_here(app_client) -> None:
    editor = await _user("sales_edit")
    tag = _tag()
    company_id = await _card(f"Omega{tag}")
    other_id = await _card(f"Sigma{tag}")
    alias = (
        await _decide(app_client, company_id, editor, f"Omega{tag} Dom", "joined")
    ).json()
    resp = await app_client.delete(
        f"{URL}/{other_id}/people/aliases/{alias['id']}", headers=_headers(editor)
    )
    assert resp.status_code == 404
    missing = await _decide(app_client, 999_999_999, editor, "Omega Dom", "joined")
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_merge_moves_decisions_and_keeps_the_targets_own(app_client) -> None:
    tag = _tag()
    target_id = await _card(f"Cel{tag}")
    source_id = await _card(f"Zrodlo{tag}")
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        db.add_all(
            [
                SalesCompanyAlias(
                    company_id=target_id,
                    alias="Wspolna",
                    normalized_alias=f"wspolna {tag}",
                    status="rejected",
                ),
                SalesCompanyAlias(
                    company_id=source_id,
                    alias="Wspolna",
                    normalized_alias=f"wspolna {tag}",
                    status="joined",
                ),
                SalesCompanyAlias(
                    company_id=source_id,
                    alias="Tylko",
                    normalized_alias=f"tylko {tag}",
                    status="joined",
                ),
            ]
        )
        await db.commit()
    async with AsyncSessionLocal() as db:
        target = await db.get(SalesCompany, target_id)
        source = await db.get(SalesCompany, source_id)
        await merge_companies(db, target=target, source=source, now=now)
        await db.commit()
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(
                    SalesCompanyAlias.company_id,
                    SalesCompanyAlias.normalized_alias,
                    SalesCompanyAlias.status,
                ).where(SalesCompanyAlias.company_id.in_((target_id, source_id)))
            )
        ).all()
    assert sorted(tuple(row) for row in rows) == sorted(
        [
            (target_id, f"wspolna {tag}", "rejected"),
            (target_id, f"tylko {tag}", "joined"),
            # Nazwa wchłoniętej karty dochodzi jako dołączona.
            (target_id, normalize_company_name(f"Zrodlo{tag}"), "joined"),
        ]
    )


async def _merge(target_id: int, source_id: int, **kwargs) -> None:
    async with AsyncSessionLocal() as db:
        target = await db.get(SalesCompany, target_id)
        source = await db.get(SalesCompany, source_id)
        await merge_companies(
            db, target=target, source=source, now=datetime.now(timezone.utc), **kwargs
        )
        await db.commit()


async def _decisions(company_id: int) -> list[tuple[str, str]]:
    async with AsyncSessionLocal() as db:
        rows = await company_aliases.decisions(db, company_id)
        return [(row.alias, row.status) for row in rows]


@pytest.mark.asyncio
async def test_merge_on_the_screen_keeps_people_of_the_absorbed_name(
    app_client,
) -> None:
    editor = await _user("sales_edit")
    tag = _tag()
    target_id = await _card(f"Omega{tag}")
    source_id = await _card(f"Omega{tag} Group")
    await _person(f"Cel{tag}", _job(f"Omega{tag}"))
    for number in range(2):
        await _person(f"Zrodlo{number}{tag}", _job(f"Omega{tag} Group"))
    before = [
        (await _people(app_client, company_id, editor))["counts"]["current"]
        for company_id in (target_id, source_id)
    ]

    merged = await app_client.post(
        f"{URL}/{target_id}/merge",
        headers=_headers(editor),
        json={"source_id": source_id},
    )

    assert merged.status_code == 200, merged.text
    assert before == [1, 2]
    after = await _people(app_client, target_id, editor)
    assert after["counts"]["current"] == sum(before)
    async with AsyncSessionLocal() as db:
        alias = (
            await db.execute(
                select(SalesCompanyAlias).where(
                    SalesCompanyAlias.company_id == target_id
                )
            )
        ).scalar_one()
    assert (alias.alias, alias.normalized_alias, alias.status) == (
        f"Omega{tag} Group",
        normalize_company_name(f"Omega{tag} Group"),
        "joined",
    )
    # Dopisek da się cofnąć na karcie i widać, kto scalił.
    assert alias.created_by_user_id == editor.id


@pytest.mark.asyncio
async def test_merge_joins_the_legal_name_and_skips_names_the_target_has(
    app_client,
) -> None:
    tag = _tag()
    target_id = await _card(f"Cel{tag}", legal_name=f"Cel{tag} Dawna")
    # Nazwa źródła to nazwa prawna docelowej, a karta tej samej nazwy niczego nie wnosi.
    source_id = await _card(f"Cel{tag} Dawna S.A.", legal_name=f"Prawna{tag} Holding")
    twin_id = await _card(f"CEL{tag} Sp. z o.o.")

    await _merge(target_id, source_id)
    await _merge(target_id, twin_id)

    assert await _decisions(target_id) == [(f"Prawna{tag} Holding", "joined")]
    assert await _decisions(source_id) == []


@pytest.mark.asyncio
async def test_merge_leaves_the_targets_decision_about_the_absorbed_name(
    app_client,
) -> None:
    editor = await _user("sales_edit")
    tag = _tag()
    target_id = await _card(f"Cel{tag}")
    source_id = await _card(f"Zrodlo{tag}")
    await _person(f"Obca{tag}", _job(f"Zrodlo{tag}"))
    async with AsyncSessionLocal() as db:
        db.add(
            SalesCompanyAlias(
                company_id=target_id,
                alias=f"Zrodlo{tag}",
                normalized_alias=normalize_company_name(f"Zrodlo{tag}"),
                status="rejected",
            )
        )
        await db.commit()

    await _merge(target_id, source_id)

    assert await _decisions(target_id) == [(f"Zrodlo{tag}", "rejected")]
    assert (await _people(app_client, target_id, editor))["counts"]["current"] == 0


@pytest.mark.asyncio
async def test_merge_does_not_join_a_name_that_cannot_be_an_alias(app_client) -> None:
    tag = _tag()
    target_id = await _card(f"Cel{tag}")
    # Nazwa prawna źródła uzupełnia pustą nazwę prawną docelowej, więc panel już ją zna.
    source_id = await _card(f"Freelance {tag}", legal_name=f"Prawna{tag} Holding")

    await _merge(target_id, source_id)

    assert await _decisions(target_id) == []
    async with AsyncSessionLocal() as db:
        target = await db.get(SalesCompany, target_id)
    assert target.legal_name == f"Prawna{tag} Holding"


# ── Kolejność osób ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_decision_roles_first_then_freshest_and_dates_in_api(app_client) -> None:
    viewer = await _user("sales_view")
    tag = _tag()
    name = f"Kolejnosc {tag}"
    company_id = await _card(name)
    now = datetime.now(timezone.utc)
    older = await _person(
        f"Aaa{tag}", _job(name, role="Programista"), added=now - timedelta(days=500)
    )
    fresher = await _person(
        f"Zzz{tag}", _job(name, role="Programista"), added=now - timedelta(days=5)
    )
    boss = await _person(
        f"Mmm{tag}", _job(name, role="IT Manager"), added=now - timedelta(days=4000)
    )
    junior = await _person(
        f"Bbb{tag}", _job(name, role="Junior Manager"), added=now - timedelta(days=900)
    )

    body = await _people(app_client, company_id, viewer)
    assert [p["candidate_id"] for p in body["people"]] == [
        boss,
        fresher,
        older,
        junior,
    ]
    first = body["people"][0]
    assert first["decision_role"] is True
    assert first["cv_stale"] is True
    assert body["people"][1]["decision_role"] is False
    assert body["people"][1]["cv_stale"] is False
    assert body["people"][1]["added_at"] == str(business_today() - timedelta(days=5))


@pytest.mark.asyncio
async def test_order_is_decided_before_the_list_is_cut(app_client) -> None:
    viewer = await _user("sales_view")
    tag = _tag()
    name = f"Limit Listy {tag}"
    company_id = await _card(name)
    await _person(f"Aaa{tag}", _job(name, role="Programista"))
    boss = await _person(f"Zzz{tag}", _job(name, role="Head of IT"))
    body = await _people(app_client, company_id, viewer, limit=1)
    assert [p["candidate_id"] for p in body["people"]] == [boss]
    assert body["counts"]["current"] == 2
    assert body["truncated"] is True


# ── Dziennik odczytu ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reading_the_list_is_logged_with_ids_only(app_client) -> None:
    viewer = await _user("sales_view")
    tag = _tag()
    name = f"Dziennik {tag}"
    company_id = await _card(name)
    person_id = await _person(f"Czytany{tag}", _job(name))

    body = await _people(app_client, company_id, viewer)
    assert body["read_logged"] is True

    async with AsyncSessionLocal() as db:
        rows = (
            (
                await db.execute(
                    select(Activity).where(
                        Activity.action == candidate_audit.SALES_COMPANY_PEOPLE_READ,
                        Activity.user_id == viewer.id,
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 1
    assert rows[0].entity_type == "candidate"
    assert rows[0].details == {
        "sales_company_id": company_id,
        "candidate_ids": [person_id],
        "count": 1,
    }
    assert tag not in str(rows[0].details)


def test_a_list_read_does_not_raise_the_mass_download_alarm() -> None:
    # Decyzja 07.11.2026 (#3118): przeglądanie nie wywołuje alarmu.
    action = candidate_audit.SALES_COMPANY_PEOPLE_READ
    assert action not in candidate_data_access_alerts.FILE_ACTIONS


@pytest.mark.asyncio
async def test_empty_list_writes_nothing_and_does_not_claim_it(app_client) -> None:
    viewer = await _user("sales_view")
    company_id = await _card(f"Pusta {_tag()}")
    body = await _people(app_client, company_id, viewer)
    assert body["people"] == []
    assert body["read_logged"] is False
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(Activity.id).where(
                    Activity.action == candidate_audit.SALES_COMPANY_PEOPLE_READ,
                    Activity.user_id == viewer.id,
                )
            )
        ).all()
    assert rows == []


@pytest.mark.asyncio
async def test_failed_log_keeps_the_list_and_does_not_claim_it(
    app_client, monkeypatch
) -> None:
    viewer = await _user("sales_view")
    tag = _tag()
    name = f"Awaria {tag}"
    company_id = await _card(name)
    await _person(f"Osoba{tag}", _job(name))

    def boom(*args, **kwargs) -> None:
        raise RuntimeError("dziennik niedostępny")

    monkeypatch.setattr(
        sales_company_people.candidate_audit, "record_candidate_audit", boom
    )
    body = await _people(app_client, company_id, viewer)
    assert len(body["people"]) == 1
    assert body["read_logged"] is False


@pytest.mark.asyncio
async def test_group_counts_are_not_a_read_of_people(app_client) -> None:
    viewer = await _user("sales_view")
    tag = _tag()
    parent_id = await _card(f"Matka {tag}")
    await _card(f"Corka {tag}", parent_company_id=parent_id)
    await _person(f"Osoba{tag}", _job(f"Corka {tag}"))
    resp = await app_client.get(
        f"{URL}/{parent_id}/people/group", headers=_headers(viewer)
    )
    assert resp.status_code == 200, resp.text
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(Activity.id).where(
                    Activity.action == candidate_audit.SALES_COMPANY_PEOPLE_READ,
                    Activity.user_id == viewer.id,
                )
            )
        ).all()
    assert rows == []


# ── Klient po nazwie i aliasie ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_client_found_by_its_alias_without_client_id(app_client) -> None:
    viewer = await _user("sales_view")
    tag = _tag()
    name = f"Kartoteka {tag}"
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Klient Formalny {tag}")
        db.add(client)
        await db.flush()
        db.add(
            ClientAlias(
                client_id=client.id,
                alias=name,
                normalized_alias=name.lower(),
                source_system="test",
                source_key=tag,
            )
        )
        placed = await _candidate(db, f"Umieszczony{tag}")
        db.add(_contract(placed.id, client.id, ContractStatus.active))
        await db.commit()
        client_id, placed_id = client.id, placed.id
    company_id = await _card(name)

    body = await _people(app_client, company_id, viewer)
    assert body["matched_client"]["id"] == client_id
    assert body["counts"]["via_us"] == 1
    assert body["people"][0]["candidate_id"] == placed_id


@pytest.mark.asyncio
async def test_client_found_through_a_joined_cv_name(app_client) -> None:
    editor = await _user("sales_edit")
    tag = _tag()
    old = f"Klient Dawny {tag}"
    async with AsyncSessionLocal() as db:
        client = Client(name=old)
        db.add(client)
        await db.commit()
        client_id = client.id
    company_id = await _card(f"Kartoteka Nowa {tag}")

    assert (await _people(app_client, company_id, editor))["matched_client"] is None
    resp = await _decide(app_client, company_id, editor, old, "joined")
    assert resp.status_code == 200, resp.text
    assert (await _people(app_client, company_id, editor))["matched_client"]["id"] == (
        client_id
    )


@pytest.mark.asyncio
async def test_explicit_link_beats_the_name_match(app_client) -> None:
    viewer = await _user("sales_view")
    tag = _tag()
    name = f"Podwojna {tag}"
    async with AsyncSessionLocal() as db:
        same_name = Client(name=name)
        linked = Client(name=f"Prawdziwy Klient {tag}")
        db.add_all([same_name, linked])
        await db.commit()
        linked_id = linked.id
    company_id = await _card(name, client_id=linked_id)
    body = await _people(app_client, company_id, viewer)
    assert body["matched_client"]["id"] == linked_id


# ── Własna firma ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_own_company_card_shows_no_people_and_logs_nothing(app_client) -> None:
    viewer = await _user("sales_view")
    tag = _tag()
    company_id = await _card("B2B Network S.A.")
    await _person(f"Nasz{tag}", _job("B2B Network"))

    body = await _people(app_client, company_id, viewer)
    assert body["own_company"] is True
    assert body["people"] == []
    assert sum(body["counts"].values()) == 0
    assert body["read_logged"] is False
    aliases = (
        await app_client.get(
            f"{URL}/{company_id}/people/aliases", headers=_headers(viewer)
        )
    ).json()
    assert aliases["suggestions"] == []


@pytest.mark.asyncio
async def test_own_company_is_left_out_of_the_group(app_client) -> None:
    viewer = await _user("sales_view")
    tag = _tag()
    parent_id = await _card(f"Grupa {tag}")
    await _card("B2B Net", parent_company_id=parent_id)
    await _card(f"Spolka {tag}", parent_company_id=parent_id)
    group = (
        await app_client.get(
            f"{URL}/{parent_id}/people/group", headers=_headers(viewer)
        )
    ).json()
    assert [g["company"]["name"] for g in group] == [f"Spolka {tag}"]


# ── API dla CRM bez zmian ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_prefilter_uses_one_like_any_for_all_names() -> None:
    clause = integrations_companies._company_prefilter(["Alfa", "Beta", "Gamma"])
    sql = str(clause.compile())
    assert sql.count("LIKE ANY") == 2  # LinkedIn i wpisy CV, po jednym na wszystkie
    assert " OR lower(" in sql or "OR EXISTS" in sql
    assert sql.count("jsonb_array_elements") == 1
