"""Sprzedaż → lejek Fabryki IT mierzony kontaktem (``/api/sales/it-factories``).

Liczniki map, podpowiedź rozjazdu etapu, kolejka do pierwszego kontaktu
i liczniki „Znamy teraz” / „Kiedyś” liczone jednym skanem dla całej listy.
Dane są fikcyjne, a nazwy niosą losowy tag: baza testowa jest wspólna.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.client import Client
from app.models.sales import (
    SalesCompany,
    SalesCompanyAlias,
    SalesContact,
    SalesOpportunity,
    SalesPipeline,
    SalesPipelineStage,
)
from app.models.team_structure import DeliveryLeadClientAssignment
from app.services.company_names import normalize_company_name
from app.services.sales import factories
from app.services.sales.decision_map import IT_FACTORIES_PIPELINE_KEY
from tests.test_integrations_companies_db import _candidate, _seed_company
from tests.test_sales_companies_api import _headers, _user

URL = "/api/sales/it-factories"
MAP_DONE = "itf-decision-map-done"
FIRST_CONTACT = factories.FIRST_CONTACT_STAGE_KEY
LOST = "itf-lost"

_STAGES = {
    MAP_DONE: ("Mapa decyzyjna gotowa", 2, "open"),
    FIRST_CONTACT: ("Pierwszy kontakt", 4, "open"),
    LOST: ("Przegrane", 9, "lost"),
}


def _person(name: str, level: Optional[int], status: str = "not_contacted", **extra):
    return {
        "name": name,
        "decision_level": level,
        "contact_status": status,
        **extra,
    }


async def _stage_ids() -> tuple[int, dict[str, int]]:
    """Lejek Fabryki IT z etapami jak po imporcie z Atlasa (klucze i kolejność)."""

    async with AsyncSessionLocal() as db:
        pipeline = await db.scalar(
            select(SalesPipeline).where(SalesPipeline.key == IT_FACTORIES_PIPELINE_KEY)
        )
        if pipeline is None:
            pipeline = SalesPipeline(key=IT_FACTORIES_PIPELINE_KEY, name="Fabryki IT")
            db.add(pipeline)
            await db.flush()
        existing = {
            stage.key: stage.id
            for stage in (
                await db.execute(
                    select(SalesPipelineStage).where(
                        SalesPipelineStage.pipeline_id == pipeline.id
                    )
                )
            ).scalars()
        }
        for key, (name, position, outcome) in _STAGES.items():
            if key not in existing:
                stage = SalesPipelineStage(
                    pipeline_id=pipeline.id,
                    key=key,
                    name=name,
                    position=position,
                    probability=10,
                    outcome=outcome,
                )
                db.add(stage)
                await db.flush()
                existing[key] = stage.id
        await db.commit()
        return pipeline.id, existing


async def _company(name: Optional[str] = None, **fields: Any) -> int:
    name = name or f"Fabryka {uuid.uuid4().hex[:8]}"
    async with AsyncSessionLocal() as db:
        company = SalesCompany(
            name=name, normalized_name=normalize_company_name(name), **fields
        )
        db.add(company)
        await db.commit()
        return company.id


async def _account(
    people: list[dict[str, Any]],
    *,
    owner_id: Optional[int] = None,
    stage: str = MAP_DONE,
    company_id: Optional[int] = None,
    status: str = "open",
) -> tuple[int, int]:
    """Konto w lejku z mapą decyzyjną; zwraca id szansy i firmy."""

    pipeline_id, stages = await _stage_ids()
    company_id = company_id or await _company()
    async with AsyncSessionLocal() as db:
        opp = SalesOpportunity(
            company_id=company_id,
            pipeline_id=pipeline_id,
            stage_id=stages[stage],
            title="Konto testowe",
            status=status,
            owner_user_id=owner_id,
            custom_fields={"atlas": {"it_factory": {"decision_map": people}}},
        )
        db.add(opp)
        await db.commit()
        return opp.id, company_id


async def _accounts(app_client, user) -> dict[int, dict[str, Any]]:
    resp = await app_client.get(f"{URL}/accounts", headers=_headers(user))
    assert resp.status_code == 200, resp.text
    return {row["opportunity_id"]: row for row in resp.json()["items"]}


async def _known(app_client, user) -> dict[int, dict[str, Any]]:
    resp = await app_client.get(f"{URL}/known-people", headers=_headers(user))
    assert resp.status_code == 200, resp.text
    return {row["company_id"]: row for row in resp.json()["items"]}


# ── Liczniki mapy (bez bazy) ──────────────────────────────────────────────


def test_contacted_means_any_status_past_no_contact() -> None:
    people = [
        _person("W toku", 1, "in_progress"),
        _person("Pierwszy kontakt", 2, "first_contact"),
        _person("Stały dialog", 3, "regular_dialog"),
        _person("Bez kontaktu", 2, "not_contacted"),
        # Wpis z Atlasa bez statusu to też osoba, do której nikt nie dotarł.
        {"name": "Bez statusu", "decision_level": 1},
        # Wpis bez nazwiska nie jest osobą na mapie.
        {"name": "  ", "decision_level": 1, "contact_status": "first_contact"},
    ]
    counts = factories.map_counts(people)
    assert (counts.total, counts.contacted) == (5, 3)
    assert (counts.top_total, counts.top_contacted) == (4, 2)
    assert counts.waiting == 2


def test_waiting_skips_objection_lower_levels_and_blocked_company() -> None:
    people = [
        _person("Sprzeciw", 1, do_not_contact=True),
        _person("Kierownik", 3),
        _person("Tester", 4),
        _person("Bez poziomu", None),
        _person("Dyrektor", 2),
    ]
    assert factories.map_counts(people).waiting == 1
    blocked = factories.map_counts(people, company_blocked=True)
    assert (blocked.waiting, blocked.total) == (0, 5)


def test_map_counts_survive_unvalidated_values_from_import() -> None:
    """Mapa z importu nie przeszła walidacji API: dziwny typ to brak wartości, nie błąd."""

    people = [
        {"name": "Lista", "decision_level": [1], "contact_status": ["first_contact"]},
        {"name": "Napis", "decision_level": "2", "contact_status": None},
        {"name": "Prawda", "decision_level": True},
        _person("Dyrektor", 2),
    ]
    counts = factories.map_counts(people)
    assert (counts.total, counts.contacted, counts.top_total) == (4, 0, 1)
    rows = [
        factories.QueuePerson(1, "Konto", 1, "Firma", None, person) for person in people
    ]
    assert [row.person["name"] for row in sorted(rows, key=factories._queue_order)] == [
        "Dyrektor",
        "Lista",
        "Napis",
        "Prawda",
    ]


@pytest.mark.parametrize(
    ("position", "outcome", "first_contact", "expected"),
    [
        (4, "open", 4, True),
        (6, "open", 4, True),
        (2, "open", 4, False),
        (9, "lost", 4, False),
        (8, "won", 4, False),
        # Lejek bez etapu „Pierwszy kontakt” nie ma czego podpowiadać.
        (4, "open", None, False),
    ],
)
def test_stage_claims_contact_from_first_contact_on(
    position: int, outcome: str, first_contact: Optional[int], expected: bool
) -> None:
    assert factories.stage_claims_contact(position, outcome, first_contact) is expected


# ── Lista kont ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_accounts_need_sales_view(app_client) -> None:
    outsider = await _user()
    for path in ("accounts", "queue", "known-people"):
        resp = await app_client.get(f"{URL}/{path}", headers=_headers(outsider))
        assert resp.status_code == 403, path
        assert resp.json()["detail"]["code"] == "permission_denied"


@pytest.mark.asyncio
async def test_accounts_count_map_and_flag_stage_without_contact(app_client) -> None:
    viewer = await _user("sales_view")
    untouched = [_person("Prezes", 1), _person("Dyrektor", 2), _person("Tester", 4)]
    stage_ahead, _ = await _account(untouched, stage=FIRST_CONTACT)
    research, _ = await _account(untouched, stage=MAP_DONE)
    talking, _ = await _account(
        [_person("Prezes", 1, "first_contact"), _person("Dyrektor", 2)],
        stage=FIRST_CONTACT,
    )
    empty_map, _ = await _account([], stage=FIRST_CONTACT)

    rows = await _accounts(app_client, viewer)

    ahead = rows[stage_ahead]
    assert (ahead["map_contacted"], ahead["map_total"]) == (0, 3)
    assert (ahead["top_contacted"], ahead["top_total"], ahead["waiting"]) == (0, 2, 2)
    assert ahead["stage_mismatch"] is True
    # Etap researchu nie mówi o kontakcie, więc nie ma czego podpowiadać.
    assert rows[research]["stage_mismatch"] is False
    assert rows[talking]["stage_mismatch"] is False
    assert (rows[talking]["map_contacted"], rows[talking]["waiting"]) == (1, 1)
    # Pusta mapa na etapie kontaktu też jest rozjazdem.
    assert rows[empty_map]["stage_mismatch"] is True
    assert rows[empty_map]["client"] is None


@pytest.mark.asyncio
async def test_stage_mismatch_never_blocks_the_move(app_client) -> None:
    rep = await _user("sales_edit")
    _, stages = await _stage_ids()
    opp_id, _ = await _account([_person("Prezes", 1)], owner_id=rep.id)

    moved = await app_client.post(
        f"/api/sales/opportunities/{opp_id}/move",
        json={"stage_id": stages[FIRST_CONTACT]},
        headers=_headers(rep),
    )

    assert moved.status_code == 200, moved.text
    assert moved.json()["stage"]["key"] == FIRST_CONTACT
    assert (await _accounts(app_client, rep))[opp_id]["stage_mismatch"] is True


@pytest.mark.asyncio
async def test_account_of_a_nexus_client_points_to_its_delivery_lead(
    app_client,
) -> None:
    viewer = await _user("sales_view")
    lead = await _user(role="delivery_lead")
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Klient Bocian {tag}")
        orphan = Client(name=f"Klient Czapla {tag}")
        db.add_all([client, orphan])
        await db.flush()
        db.add(
            DeliveryLeadClientAssignment(
                delivery_lead_user_id=lead.id, client_id=client.id
            )
        )
        await db.commit()
        client_id, orphan_name = client.id, orphan.name
    # Powiązanie ręczne i zgodność samej nazwy prowadzą do tego samego oznaczenia.
    linked, _ = await _account(
        [_person("Prezes", 1)], company_id=await _company(client_id=client_id)
    )
    by_name, _ = await _account(
        [_person("Prezes", 1)], company_id=await _company(f"{orphan_name} S.A.")
    )

    rows = await _accounts(app_client, viewer)

    assert rows[linked]["client"] == {
        "name": f"Klient Bocian {tag}",
        "delivery_lead": lead.name,
    }
    assert rows[by_name]["client"] == {"name": orphan_name, "delivery_lead": None}


# ── Kolejka ───────────────────────────────────────────────────────────────


def _names(rows: list[dict[str, Any]]) -> list[str]:
    return [row["person"]["name"] for row in rows]


@pytest.mark.asyncio
async def test_queue_is_levels_one_and_two_from_own_open_accounts(app_client) -> None:
    rep = await _user("sales_edit")
    other = await _user("sales_edit")
    opp_id, company_id = await _account(
        [
            _person("Dyrektor Czeka", 2),
            _person("Prezes Czeka", 1),
            _person("Prezes Po Kontakcie", 1, "first_contact"),
            _person("Dyrektor W Toku", 2, "in_progress"),
            _person("Kierownik", 3),
            _person("Tester", 4),
            _person("Bez Poziomu", None),
            _person("Prezes Ze Sprzeciwem", 1, do_not_contact=True),
        ],
        owner_id=rep.id,
    )
    await _account([_person("Cudzy Prezes", 1)], owner_id=other.id)
    await _account([_person("Bez Opiekuna", 1)])
    await _account(
        [_person("Z Przegranej", 1)], owner_id=rep.id, stage=LOST, status="lost"
    )
    blocked_company = await _company(status="do_not_contact")
    await _account(
        [_person("Z Firmy Ze Sprzeciwem", 1)],
        owner_id=rep.id,
        company_id=blocked_company,
    )

    resp = await app_client.get(f"{URL}/queue", headers=_headers(rep))

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["owner"] == {"id": rep.id, "name": rep.name}
    # W firmie poziom 1 przed 2; osoby po kontakcie i ze sprzeciwem nie czekają.
    assert _names(body["people"]) == ["Prezes Czeka", "Dyrektor Czeka"]
    # Niższe poziomy wracają osobno (ekran je zwija), nic nie znika.
    assert _names(body["lower_levels"]) == ["Kierownik", "Tester", "Bez Poziomu"]
    first = body["people"][0]
    assert first["opportunity"] == {"id": opp_id, "title": "Konto testowe"}
    assert first["company"]["id"] == company_id
    # Wpis ma klucz z karty szansy: okno poprawki osoby działa na nim bez zmian.
    detail = (
        await app_client.get(
            f"/api/sales/opportunities/{opp_id}", headers=_headers(rep)
        )
    ).json()
    card_keys = {
        person["name"]: person["key"]
        for person in detail["atlas_motion"]["it_factory"]["decision_map"]
    }
    assert first["person"]["key"] == card_keys["Prezes Czeka"]


@pytest.mark.asyncio
async def test_queue_order_and_contact_objection_from_contact_card(app_client) -> None:
    rep = await _user("sales_edit")
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Klient Dudek {tag}")
        db.add(client)
        await db.commit()
        client_id = client.id
    client_company = await _company(f"Aaa Klient {tag}", client_id=client_id)
    late = await _company(f"Zzz Firma {tag}")
    early = await _company(f"Bbb Firma {tag}")
    async with AsyncSessionLocal() as db:
        db.add_all(
            [
                SalesContact(
                    company_id=early,
                    full_name="Sprzeciw Z Kontaktu",
                    do_not_contact_at=datetime(2026, 11, 1, tzinfo=timezone.utc),
                ),
                SalesContact(
                    company_id=early, full_name="Numer Z Kontaktu", phone="600 100 200"
                ),
            ]
        )
        await db.commit()
    await _account(
        [_person("Klientowski", 1)], owner_id=rep.id, company_id=client_company
    )
    await _account([_person("Zenon", 1)], owner_id=rep.id, company_id=late)
    await _account(
        [
            _person("Bez Kanału", 2),
            _person("Numer Z Kontaktu", 2),
            _person("Z Mailem", 2, email="mail@example.com"),
            _person("Sprzeciw Z Kontaktu", 1),
            _person("Prezes", 1),
        ],
        owner_id=rep.id,
        company_id=early,
    )

    body = (await app_client.get(f"{URL}/queue", headers=_headers(rep))).json()

    # Firmy alfabetycznie, klient NEXUSA na końcu; w firmie poziom, potem osoby
    # z kanałem kontaktu (także z karty kontaktu), potem nazwisko.
    assert _names(body["people"]) == [
        "Prezes",
        "Numer Z Kontaktu",
        "Z Mailem",
        "Bez Kanału",
        "Zenon",
        "Klientowski",
    ]
    assert body["people"][-1]["client"]["name"] == f"Klient Dudek {tag}"
    assert body["people"][1]["person"]["from_contact"] == ["phone"]


@pytest.mark.asyncio
async def test_someone_elses_queue_needs_sales_edit(app_client) -> None:
    owner = await _user("sales_edit")
    colleague = await _user("sales_edit")
    viewer = await _user("sales_view")
    await _account([_person("Prezes", 1)], owner_id=owner.id)
    theirs = f"{URL}/queue?owner_id={owner.id}"

    denied = await app_client.get(theirs, headers=_headers(viewer))
    assert denied.status_code == 403
    assert denied.json()["detail"]["permission"] == "sales_edit"

    allowed = await app_client.get(theirs, headers=_headers(colleague))
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["owner"]["id"] == owner.id
    assert _names(allowed.json()["people"]) == ["Prezes"]

    # Własna kolejka konta z samym podglądem działa i jest pusta.
    own = await app_client.get(f"{URL}/queue", headers=_headers(viewer))
    assert own.status_code == 200
    assert (own.json()["people"], own.json()["lower_levels"]) == ([], [])
    same = await app_client.get(
        f"{URL}/queue?owner_id={viewer.id}", headers=_headers(viewer)
    )
    assert same.status_code == 200

    missing = await app_client.get(
        f"{URL}/queue?owner_id=2147483000", headers=_headers(colleague)
    )
    assert missing.status_code == 404


# ── „Znamy teraz” i „Kiedyś” ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_known_people_counts_match_the_company_panel(app_client) -> None:
    viewer = await _user("sales_view")
    world = await _seed_company()
    company_id = await _company(world["company"])
    await _account([_person("Prezes", 1)], company_id=company_id)

    known = (await _known(app_client, viewer))[company_id]
    panel = (
        await app_client.get(
            f"/api/sales/companies/{company_id}/people", headers=_headers(viewer)
        )
    ).json()

    # Ta sama firma, te same kubełki: umowy „przez nas”, CV i flagi klienta.
    assert {key: known[key] for key in panel["counts"]} == panel["counts"]
    assert (known["via_us"], known["current"], known["past"]) == (2, 2, 2)


@pytest.mark.asyncio
async def test_known_people_find_names_with_quotes_and_diacritics_like_the_panel(
    app_client,
) -> None:
    """Prefiltr listy czyta nazwy z zapisu JSON: cudzysłów i ogonki nie mogą gubić osób."""

    viewer = await _user("sales_view")
    tag = uuid.uuid4().hex[:8]
    quoted = f'Czapla "Tech" {tag}'
    accented = f"Żuraw Łódź {tag}"
    async with AsyncSessionLocal() as db:
        await _candidate(
            db,
            f"Cudzyslow{tag}",
            experience=[
                {"company": f"{quoted} sp. z o.o.", "start": "2023", "end": None}
            ],
        )
        await _candidate(
            db,
            f"Ogonki{tag}",
            experience=[{"company": accented.upper(), "start": "2019", "end": "2021"}],
        )
        # LinkedIn bez wpisu w CV też jest „teraz”.
        linkedin = await _candidate(db, f"Linkedin{tag}")
        linkedin.linkedin_current_company = accented
        await db.commit()
    quoted_id = await _company(quoted)
    accented_id = await _company(accented)
    for cid in (quoted_id, accented_id):
        await _account([_person("Prezes", 1)], company_id=cid)

    known = await _known(app_client, viewer)

    for cid in (quoted_id, accented_id):
        panel = (
            await app_client.get(
                f"/api/sales/companies/{cid}/people", headers=_headers(viewer)
            )
        ).json()
        assert {key: known[cid][key] for key in panel["counts"]} == panel["counts"]
    assert known[quoted_id]["current"] == 1
    assert known[accented_id]["current"] == 1


@pytest.mark.asyncio
async def test_known_people_use_joined_names_and_zero_without_match(app_client) -> None:
    viewer = await _user("sales_view")
    tag = uuid.uuid4().hex[:8]
    name = f"Rybitwa Software {tag}"
    old_name = f"Mewa Systems {tag}"
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
        await _candidate(
            db,
            f"StaraNazwa{tag}",
            experience=[{"company": old_name, "start": "2015", "end": "2017"}],
        )
        # Sama marka w dłuższej nazwie to inna firma: dopasowanie jest dokładne.
        await _candidate(
            db,
            f"Inna{tag}",
            experience=[
                {"company": f"{name} Consulting", "start": "2021", "end": None}
            ],
        )
        await db.commit()
    company_id = await _company(name)
    unknown_company = await _company(f"Perkoz Nieznany {tag}")
    own_company = await _company(f"B2B Network {tag}")
    short_name = await _company("Xy")
    for cid in (company_id, unknown_company, own_company, short_name):
        await _account([_person("Prezes", 1)], company_id=cid)

    before = await _known(app_client, viewer)
    assert (before[company_id]["current"], before[company_id]["past"]) == (1, 1)
    # Brak dopasowania, nasza firma i za krótka nazwa to zera, nie błąd.
    for cid in (unknown_company, own_company, short_name):
        assert before[cid] == {
            "company_id": cid,
            "current": 0,
            "past": 0,
            "via_us": 0,
            "unknown": 0,
        }

    async with AsyncSessionLocal() as db:
        db.add(
            SalesCompanyAlias(
                company_id=company_id,
                alias=old_name,
                normalized_alias=normalize_company_name(old_name),
                status="joined",
            )
        )
        await db.commit()

    after = (await _known(app_client, viewer))[company_id]
    assert (after["current"], after["past"]) == (1, 2)
