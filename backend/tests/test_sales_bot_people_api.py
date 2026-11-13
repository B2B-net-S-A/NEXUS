"""Mapy decydentów od bota (``people``) z bazą: raport, przegląd, zapis i start biegu.

Reguły: ``docs/claude/sprzedaz/mapy-decydentow-od-bota.md``. Nazwy i adresy
w testach są fikcyjne (repo jest publiczne).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.sales import (
    SalesBotResult,
    SalesCompany,
    SalesOpportunity,
    SalesSignalRun,
)
from app.services.sales import signals
from app.services.sales.bot_tasks import people
from app.services.sales.decision_map import decision_entries
from tests.test_sales_companies_api import _headers, _user
from tests.test_sales_factories import _account, _company, _person, _stage_ids
from tests.test_sales_signals_api import URL as RUNS
from tests.test_sales_signals_api import _run

BOT = "/api/sales/bot-people"
RESULTS = "/api/sales/bot-results"


def _tag() -> str:
    return uuid.uuid4().hex[:8]


def _bot_person(name: str, **over: Any) -> dict[str, Any]:
    return {
        "full_name": name,
        "title": "Head of Data",
        "area": "data",
        "source_url": "https://firma.example/zespol",
        "published": "2026-10-01",
        **over,
    }


async def _send(app_client, company_id: int, persons: list[dict]) -> dict:
    run_id, token = await _run([company_id], kind="people")
    resp = await app_client.post(
        f"{RUNS}/{run_id}",
        json={
            "checked_firms": 1,
            "firms": [{"company_ref": company_id, "people": persons}],
        },
        headers={"X-Run-Token": token},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _pending(app_client, user, company_id: int) -> list[dict]:
    resp = await app_client.get(f"{BOT}/pending", headers=_headers(user))
    assert resp.status_code == 200, resp.text
    return [i for i in resp.json()["items"] if i["company"]["id"] == company_id]


async def _map(opportunity_id: int) -> list[dict[str, Any]]:
    async with AsyncSessionLocal() as db:
        opp = await db.get(SalesOpportunity, opportunity_id)
        return decision_entries(opp.custom_fields)


@pytest.mark.asyncio
async def test_cognism_callback_saves_the_company_map_without_an_opportunity(
    app_client, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "SALES_COGNISM_PEOPLE_ENABLED", True)
    monkeypatch.setattr(settings, "SALES_BOT_TASKS_ENABLED", False)
    name = f"Fabryka {_tag()}"
    company_id = await _company(
        name, domain="firma.example", custom_fields={"keep": True}
    )
    mismatched_id = await _company("Inna Fabryka", domain="inna-firma.example")
    foreign_id = await _company()
    viewer = await _user("sales_view")
    editor = await _user("sales_edit")
    endpoint = f"{BOT}/companies/{company_id}/map"
    assert (await app_client.get(endpoint, headers=_headers(viewer))).status_code == 403
    run_id, token = await _run(
        [company_id, mismatched_id], kind="people", request={"source": "cognism"}
    )
    observed = datetime.now(timezone.utc).isoformat()
    first = {
        "full_name": "Jan Fikcyjny",
        "title": "Head of Data",
        "source_url": "https://app.cognism.com/search/prospects/contacts/profile-example",
        "observed_at": observed,
        "active": True,
        "dnc": False,
        "email": "jan@firma.example",
        "phone": "+48 600 100 200",
        "phone_type": "mobile",
        "verified_mobile": True,
    }
    report = {
        "firms": [
            {
                "company_ref": company_id,
                "status": "matched",
                "company_name": name,
                "company_domain": "firma.example",
                "people": [
                    first,
                    {
                        **first,
                        "full_name": "Anna Fikcyjna",
                        "source_url": "https://app.cognism.com/search/prospects/contacts/blocked-example",
                        "dnc": True,
                    },
                ],
            },
            {
                "company_ref": mismatched_id,
                "status": "matched",
                "company_name": name,
                "company_domain": "firma.example",
                "people": [first],
            },
            {"company_ref": foreign_id, "status": "not_found"},
        ],
    }
    invalid = await app_client.post(
        f"{RUNS}/{run_id}",
        json={
            "firms": [
                {**report["firms"][0], "people": [{**first, "secret": "private"}]}
            ]
        },
        headers={"X-Run-Token": token},
    )
    assert invalid.status_code == 422
    assert "private" not in invalid.text and first["full_name"] not in invalid.text
    received = await app_client.post(
        f"{RUNS}/{run_id}", json=report, headers={"X-Run-Token": token}
    )
    assert received.status_code == 200, received.text
    assert received.json()["people"] == 1
    assert received.json()["suppressed"] == 1
    assert received.json()["ambiguous"] == 1
    assert received.json()["unknown_company"] == 1
    assert "processed_company_ids" not in received.json()
    assert first["email"] not in received.text
    repeated = await app_client.post(
        f"{RUNS}/{run_id}", json=report, headers={"X-Run-Token": token}
    )
    assert repeated.status_code == 401
    response = await app_client.get(endpoint, headers=_headers(editor))
    assert response.status_code == 200, response.text
    assert response.json()["enabled"] is True
    [person] = response.json()["people"]
    assert person["source"] == "cognism"
    assert person["active"] is True and person["email"] == first["email"]
    assert person["verified_mobile"] is True and person["phone_type"] == "mobile"
    async with AsyncSessionLocal() as db:
        company = await db.get(SalesCompany, company_id)
        assert company.custom_fields["keep"] is True
        mismatched = await db.get(SalesCompany, mismatched_id)
        assert people.COGNISM_MAP_KEY not in mismatched.custom_fields
        run = await db.get(SalesSignalRun, run_id)
        assert run.report["processed_company_ids"] == [company_id]
        assert run.report["ambiguous_company_ids"] == [mismatched_id]
        assert (
            await db.scalar(
                select(func.count())
                .select_from(SalesOpportunity)
                .where(SalesOpportunity.company_id == company_id)
            )
            == 0
        )
        assert (
            await db.scalar(
                select(func.count())
                .select_from(SalesBotResult)
                .where(SalesBotResult.run_id == run_id)
            )
            == 0
        )


@pytest.mark.asyncio
async def test_cognism_verified_employer_is_scoped_to_the_run_card_and_profiles(
    app_client,
) -> None:
    tag = _tag()
    pinned = await _company(f"Karta {tag}")
    no_hint = await _company(f"Karta bez wskazówki {tag}")
    wrong_domain = await _company(f"Inna karta {tag}", domain="inna.example")
    wrong_profile = await _company(f"Karta bez zgodnej osoby {tag}")
    alternate_name = f"Etykieta dostawcy {tag}"
    hint = {
        "company_name": alternate_name,
        "company_domain": "firma.example",
        "profile_ids": ["profile-example"],
    }
    request = {
        "source": "cognism",
        "employers": [
            {**hint, "company_ref": cid}
            for cid in (pinned, wrong_domain, wrong_profile)
        ],
    }
    company_ids = [pinned, no_hint, wrong_domain, wrong_profile]
    run_id, token = await _run(company_ids, kind="people", request=request)
    person = {
        "full_name": "Jan Fikcyjny",
        "title": "Head of Data",
        "source_url": "https://app.cognism.com/search/prospects/contacts/profile-example",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "active": True,
        "email": "jan@firma.example",
    }
    outside = {
        **person,
        "full_name": "Osoba spoza wskazówki",
        "source_url": "https://app.cognism.com/search/prospects/contacts/another-profile",
    }
    reported_people = {
        pinned: [person, outside],
        no_hint: [person],
        wrong_domain: [person],
        wrong_profile: [outside],
    }
    report = {
        "firms": [
            {
                "company_ref": cid,
                "status": "matched",
                "company_name": f"{alternate_name} S.A.",
                "company_domain": "FIRMA.example",
                "people": reported_people[cid],
            }
            for cid in company_ids
        ]
    }
    response = await app_client.post(
        f"{RUNS}/{run_id}", json=report, headers={"X-Run-Token": token}
    )
    assert response.status_code == 200, response.text
    assert response.json()["people"] == 1
    assert response.json()["ambiguous"] == 2
    assert response.json()["not_processed"] == 1
    async with AsyncSessionLocal() as db:
        run = await db.get(SalesSignalRun, run_id)
        assert run.report["processed_company_ids"] == [pinned]
        assert run.report["ambiguous_company_ids"] == sorted([no_hint, wrong_domain])
        assert run.report["unprocessed_company_ids"] == [wrong_profile]
        matched = await db.get(SalesCompany, pinned)
        [entry] = matched.custom_fields[people.COGNISM_MAP_KEY]
        assert entry["source_url"] == person["source_url"]
        assert entry["email"] == person["email"]
        assert matched.domain is None
        blocked = await db.get(SalesCompany, wrong_domain)
        assert blocked.domain == "inna.example"
        assert people.COGNISM_MAP_KEY not in blocked.custom_fields


@pytest.mark.asyncio
async def test_cognism_provider_dnc_survives_company_merge(
    app_client, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "SALES_COGNISM_PEOPLE_ENABLED", True)
    editor = await _user("sales_edit")
    headers = _headers(editor)
    name = f"Fabryka {_tag()}"
    now = datetime.now(timezone.utc)
    prior = (now - timedelta(days=1)).isoformat()
    person = {
        "full_name": "Jan Fikcyjny",
        "title": "Head of Data",
        "source_url": "https://app.cognism.com/search/prospects/contacts/profile-example",
        "observed_at": prior,
        "active": True,
    }
    stored = {
        **person,
        "phone": "+48 600 100 200",
        "phone_observed_at": prior,
        "phone_type": "mobile",
    }
    fields = {people.COGNISM_MAP_KEY: [stored], "keep": True}
    target = await _company(name, domain="firma.example", custom_fields=fields)
    source = await _company(name, domain="firma.example", custom_fields=fields)
    run_id, token = await _run([target], kind="people", request={"source": "cognism"})
    received = await app_client.post(
        f"{RUNS}/{run_id}",
        json={
            "firms": [
                {
                    "company_ref": target,
                    "status": "matched",
                    "company_name": name,
                    "company_domain": "firma.example",
                    "people": [{**person, "observed_at": now.isoformat(), "dnc": True}],
                }
            ],
        },
        headers={"X-Run-Token": token},
    )
    assert received.status_code == 200, received.text
    assert received.json()["suppressed"] == 1
    target_map = f"{BOT}/companies/{target}/map"
    assert (await app_client.get(target_map, headers=headers)).json()["people"] == []

    merged = await app_client.post(
        f"/api/sales/companies/{target}/merge",
        json={"source_id": source},
        headers=headers,
    )
    assert merged.status_code == 200, merged.text
    assert (await app_client.get(target_map, headers=headers)).json()["people"] == []
    async with AsyncSessionLocal() as db:
        for company_id in (target, source):
            company = await db.get(SalesCompany, company_id)
            assert company.custom_fields["keep"] is True
            assert company.custom_fields[people.COGNISM_MAP_KEY] == []
            assert (
                "dnc"
                in company.custom_fields[people.COGNISM_SUPPRESSIONS_KEY][
                    "profile-example"
                ]
            )


@pytest.mark.asyncio
async def test_people_of_a_card_with_an_owner_land_on_the_map_at_once(
    app_client, monkeypatch
) -> None:
    """Decyzja Artura z 13.11.2026: bez przeglądu, gdy jest kto zapisać."""

    monkeypatch.setattr(settings, "SALES_BOT_TASKS_ENABLED", True)
    owner = await _user("sales_edit")
    company_id = await _company(f"Fabryka {_tag()}", owner_user_id=owner.id)
    account_id, _ = await _account([_person("Jan Fikcyjny", 1)], company_id=company_id)

    reply = await _send(
        app_client,
        company_id,
        [_bot_person("Anna Przykładowa", title="Chief Data Officer")],
    )
    assert (reply["added"], reply["waiting"]) == (1, 0)
    entry = (await _map(account_id))[-1]
    assert entry["name"] == "Anna Przykładowa"
    assert entry["source_label"] == people.ORIGIN
    assert entry["source_confidence"] == "confirmed"
    async with AsyncSessionLocal() as db:
        [row] = (
            await db.execute(
                select(SalesBotResult).where(
                    SalesBotResult.company_id == company_id,
                    SalesBotResult.kind == "people",
                )
            )
        ).scalars()
        assert (row.status, row.decided_by_user_id) == ("accepted", None)
    assert await _pending(app_client, owner, company_id) == []


@pytest.mark.asyncio
async def test_bot_people_review_and_accept_land_on_the_account_map(
    app_client, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "SALES_BOT_TASKS_ENABLED", True)
    tag = _tag()
    company_id = await _company(f"Fabryka {tag}")
    account_id, _ = await _account([_person("Jan Fikcyjny", 1)], company_id=company_id)

    reply = await _send(
        app_client,
        company_id,
        [
            _bot_person("Fikcyjny Jan"),  # już na mapie
            _bot_person(
                "Anna Przykładowa",
                title="Chief Data Officer",
                email=f"anna.{tag}@firma.example",
                email_source_url="https://firma.example/kontakt",
            ),
            _bot_person("Ewa Testowa", email=f"ewa.{tag}@firma.example"),
        ],
    )
    assert reply["status"] == "received"
    assert (reply["people"], reply["results_new"]) == (2, 1)
    assert reply["dropped"]["known"] == 1 and reply["dropped"]["contacts"] == 1

    viewer = await _user("sales_view")
    [item] = await _pending(app_client, viewer, company_id)
    assert (item["status"], item["people"], item["open"]) == ("new", 2, 2)
    generic = await app_client.get(
        RESULTS,
        params={"kind": "people", "company_id": company_id},
        headers=_headers(viewer),
    )
    assert generic.status_code == 200, generic.text
    assert [row["payload"] for row in generic.json()["items"]] == [{}]

    editor = await _user("sales_edit")
    assert (
        await app_client.get(f"{BOT}/{item['id']}/preview", headers=_headers(viewer))
    ).status_code == 403
    preview = await app_client.get(
        f"{BOT}/{item['id']}/preview", headers=_headers(editor)
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    [company] = body["preview"]["companies"]
    assert (company["state"], company["company_id"]) == ("account", company_id)
    rows = {row["line"]: row for row in body["preview"]["rows"]}
    assert rows[1]["name"] == "Anna Przykładowa" and rows[1]["decision_level"] == 1
    assert rows[1]["email"] == f"anna.{tag}@firma.example"
    assert rows[2]["email"] is None and rows[2]["warnings"] == [people.EMAIL_DROPPED]
    assert body["published"] == {"1": "2026-10-01", "2": "2026-10-01"}

    first = await app_client.post(
        f"{BOT}/{item['id']}/people",
        json={"people": [{"line": 1, "decision_level": 2, "company_id": company_id}]},
        headers=_headers(editor),
    )
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "partial"
    assert first.json()["outcomes"][0]["result"] == "added"
    entry = (await _map(account_id))[-1]
    assert (entry["name"], entry["decision_level"]) == ("Anna Przykładowa", 2)
    assert entry["source_label"] == people.ORIGIN
    assert entry["source_url"] == "https://firma.example/zespol"
    assert entry["source_published_at"] == "2026-10-01"
    assert entry["contact_status"] == "not_contacted"

    # Żądanie nie dokłada kontaktu, którego wynik nie ma: pól treści nie przyjmuje.
    sneaky = await app_client.post(
        f"{BOT}/{item['id']}/people",
        json={"people": [{"line": 2, "email": "zgadniety@firma.example"}]},
        headers=_headers(editor),
    )
    assert sneaky.status_code == 422

    second = await app_client.post(
        f"{BOT}/{item['id']}/people",
        json={"people": [{"line": 2, "company_id": company_id}]},
        headers=_headers(editor),
    )
    assert second.json()["status"] == "accepted"
    assert (await _map(account_id))[-1]["email"] is None
    assert await _pending(app_client, viewer, company_id) == []

    # Kolejny bieg z tymi samymi osobami nie tworzy nowego wyniku.
    again = await _send(app_client, company_id, [_bot_person("Anna Przykładowa")])
    assert (again["results"], again["dropped"]["known"]) == (0, 1)


@pytest.mark.asyncio
async def test_accept_from_results_list_opens_an_account_for_a_card(
    app_client, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "SALES_BOT_TASKS_ENABLED", True)
    await _stage_ids()  # lejek Fabryki IT musi istnieć, żeby założyć konto
    company_id = await _company(f"Karta {_tag()}")
    await _send(
        app_client,
        company_id,
        [_bot_person("Anna Przykładowa"), _bot_person("Ewa Testowa", title="CTO")],
    )
    editor = await _user("sales_edit")
    [item] = await _pending(app_client, editor, company_id)

    field_choice = await app_client.post(
        f"{RESULTS}/{item['id']}/accept",
        headers=_headers(editor),
        json={"fields": ["title"]},
    )
    assert field_choice.status_code == 409
    accepted = await app_client.post(
        f"{RESULTS}/{item['id']}/accept", headers=_headers(editor)
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json() == {"status": "accepted", "added": 2, "open": 0}
    async with AsyncSessionLocal() as db:
        row = await db.get(SalesBotResult, item["id"])
        assert (row.status, row.decided_by_user_id) == ("accepted", editor.id)
        [opp] = (
            await db.execute(
                select(SalesOpportunity).where(
                    SalesOpportunity.company_id == company_id
                )
            )
        ).scalars()
        names = [e["name"] for e in decision_entries(opp.custom_fields)]
    assert names == ["Anna Przykładowa", "Ewa Testowa"]
    again = await app_client.post(
        f"{RESULTS}/{item['id']}/accept", headers=_headers(editor)
    )
    assert again.status_code == 409


@pytest.mark.asyncio
async def test_rejected_people_are_not_proposed_again(app_client, monkeypatch) -> None:
    monkeypatch.setattr(settings, "SALES_BOT_TASKS_ENABLED", True)
    company_id = await _company(f"Odrzut {_tag()}")
    await _send(app_client, company_id, [_bot_person("Anna Przykładowa")])
    editor = await _user("sales_edit")
    [item] = await _pending(app_client, editor, company_id)
    rejected = await app_client.post(
        f"{RESULTS}/{item['id']}/reject", headers=_headers(editor)
    )
    assert rejected.status_code == 200
    reply = await _send(
        app_client,
        company_id,
        [_bot_person("Przykładowa Anna"), _bot_person("Ewa Testowa")],
    )
    assert (reply["people"], reply["dropped"]["known"]) == (1, 1)


def _mock_webhook(monkeypatch) -> list[dict]:
    seen: list[dict] = []
    real = signals.start_run

    async def start_run(db, kind, company_ids, **kwargs):
        def handler(request):
            seen.append({"kind": kind, "body": request.content})
            return httpx.Response(200)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await real(db, kind, company_ids, client=client, **kwargs)

    monkeypatch.setattr(signals, "start_run", start_run)
    monkeypatch.setattr(settings, "GROK_BOT_WEBHOOK_URL", "https://bot.example/hook")
    monkeypatch.setattr(settings, "GROK_BOT_WEBHOOK_KEY", "test-key")
    return seen


@pytest.mark.asyncio
async def test_start_once_per_company_per_day_and_only_with_edit(
    app_client, monkeypatch
) -> None:
    seen = _mock_webhook(monkeypatch)
    company_id = await _company(f"Start {_tag()}")
    editor = await _user("sales_edit")
    viewer = await _user("sales_view")
    url = f"{BOT}/companies/{company_id}/start"

    monkeypatch.setattr(settings, "SALES_BOT_TASKS_ENABLED", False)
    assert (await app_client.post(url, headers=_headers(editor))).status_code == 409
    monkeypatch.setattr(settings, "SALES_BOT_TASKS_ENABLED", True)
    assert (await app_client.post(url, headers=_headers(viewer))).status_code == 403

    started = await app_client.post(url, headers=_headers(editor))
    assert started.status_code == 200, started.text
    run_id = started.json()["run_id"]
    async with AsyncSessionLocal() as db:
        run = await db.get(SalesSignalRun, run_id)
        assert (run.kind, run.company_ids, run.requested_by_user_id) == (
            "people",
            [company_id],
            editor.id,
        )
    # Do bota idzie nazwa i domena firmy oraz polecenie, bez osób.
    assert seen[0]["kind"] == "people"
    assert b"Jan Fikcyjny" not in seen[0]["body"]

    twice = await app_client.post(url, headers=_headers(editor))
    assert twice.status_code == 409
    listed = (await app_client.get(f"{BOT}/pending", headers=_headers(viewer))).json()
    assert company_id in listed["running_company_ids"]

    missing = await app_client.post(
        f"{BOT}/companies/999999999/start", headers=_headers(editor)
    )
    assert missing.status_code == 404
