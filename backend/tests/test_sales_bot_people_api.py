"""Mapy decydentów od bota (``people``) z bazą: raport, przegląd, zapis i start biegu.

Reguły: ``docs/claude/sprzedaz/mapy-decydentow-od-bota.md``. Nazwy i adresy
w testach są fikcyjne (repo jest publiczne).
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.sales import SalesBotResult, SalesOpportunity, SalesSignalRun
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
