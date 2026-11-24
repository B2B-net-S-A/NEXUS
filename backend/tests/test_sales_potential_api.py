"""Ocena potencjału z bazą: baza wiedzy, zamówienie oceny, raport bota, ocena modelu.

Nazwy firm i klientów są fikcyjne: repo i logi Actions są publiczne.
"""

from __future__ import annotations

import json
import uuid
from datetime import timedelta
from typing import Any

import pytest

from app.api import integrations_sales_signals
from app.core.scheduling import business_today
from app.core.database import AsyncSessionLocal
from app.models.client import Client
from app.services.sales import potential
from tests.test_sales_bot_company_api import bot_on  # noqa: F401 — fikstura
from tests.test_sales_companies_api import _headers, _user
from tests.test_sales_signals_api import URL, _company, _order

COMPANIES = "/api/sales/companies"
KNOWLEDGE = "/api/sales/potential-knowledge"


def _table() -> str:
    recent = (business_today() - timedelta(days=30)).strftime("%d.%m.%Y")
    old = (business_today() - timedelta(days=700)).strftime("%d.%m.%Y")
    return (
        "| Klient | Sektor | Zakres | Data listu |\n|---|---|---|---|\n"
        f"| Fikcyjny Bank Omega | bankowość | body leasing IT | {recent} |\n"
        f"| Fikcyjna Fabryka Sigma | produkcja | testy | {old} |"
    )


async def _knowledge(app_client, editor) -> dict[str, Any]:
    parsed = await app_client.post(
        f"{KNOWLEDGE}/parse-table", json={"text": _table()}, headers=_headers(editor)
    )
    assert parsed.status_code == 200, parsed.text
    saved = await app_client.put(
        KNOWLEDGE,
        json={
            "offer": "Body leasing, pentesty, Elevate.",
            "references": [
                {k: v for k, v in ref.items() if k not in {"fresh", "nexus_active"}}
                for ref in parsed.json()["references"]
            ],
        },
        headers=_headers(editor),
    )
    assert saved.status_code == 200, saved.text
    return saved.json()


@pytest.mark.asyncio
async def test_knowledge_is_read_by_view_and_written_by_edit(app_client) -> None:
    viewer = await _user("sales_view")
    editor = await _user("sales_edit")
    refused = await app_client.put(
        KNOWLEDGE, json={"offer": "x", "references": []}, headers=_headers(viewer)
    )
    assert refused.status_code == 403
    body = await _knowledge(app_client, editor)
    refs = body["references"]
    assert [r["client"] for r in refs] == [
        "Fikcyjny Bank Omega",
        "Fikcyjna Fabryka Sigma",
    ]
    assert [r["fresh"] for r in refs] == [True, False]
    assert all(len(r["id"]) == 8 for r in refs)
    assert body["history"][0]["summary"].startswith("opis oferty")
    read = await app_client.get(KNOWLEDGE, headers=_headers(viewer))
    assert read.status_code == 200
    assert read.json()["can_edit"] is False
    assert [r["id"] for r in read.json()["references"]] == [r["id"] for r in refs]


@pytest.mark.asyncio
async def test_potential_round_trip_from_button_to_assessment(
    app_client,
    bot_on,  # noqa: F811
    monkeypatch,
) -> None:
    editor = await _user("sales_edit")
    knowledge = await _knowledge(app_client, editor)
    bank_ref = knowledge["references"][0]["id"]
    company = await _company(f"Fikcyjny Zakład {uuid.uuid4().hex[:8]}")

    started = await app_client.post(
        f"{COMPANIES}/{company}/potential", headers=_headers(editor)
    )
    assert started.status_code == 200, started.text
    assert started.json()["run"]["status"] == "started"
    [webhook] = bot_on
    # Webhook v2: zlecenie (firmy z trybem, polecenie) bot pobiera GET-em.
    order = await _order(app_client, webhook)
    assert [firm["mode"] for firm in order["firms"]] == ["potential"]
    assert "potential" in order["task"]
    again = await app_client.post(
        f"{COMPANIES}/{company}/potential", headers=_headers(editor)
    )
    assert again.status_code == 409

    # Raport bota; ocenę w tle podmieniamy na wywołanie wprost.
    spawned: list[Any] = []
    monkeypatch.setattr(
        integrations_sales_signals,
        "spawn",
        lambda coro, label: spawned.append(label) or coro.close(),
    )
    run_id = started.json()["run"]["id"]
    token = webhook["token"]
    report = {
        "checked_firms": 1,
        "potential": [
            {
                "company_ref": company,
                "pkd": "21.20.Z",
                "employees": "250-999",
                "events": [
                    {
                        "date": "2026-03",
                        "text": "Rozbudowa zakładu",
                        "url": "https://example.com/r",
                        "line": "qa",
                    }
                ],
            }
        ],
    }
    received = await app_client.post(
        f"{URL}/{run_id}", json=report, headers={"X-Run-Token": token}
    )
    assert received.status_code == 200, received.text
    assert received.json()["potential"] == 1
    assert spawned == ["sales_potential_assess"]

    pending = await app_client.get(
        f"{COMPANIES}/{company}/potential", headers=_headers(editor)
    )
    assert pending.json()["result"]["state"] == "pending"

    answer = {
        "verdict": "ŚREDNI",
        "summary": "Zakład w rozbudowie.",
        "land": {"title": "Diagnoza KSC", "why": "Termin."},
        "expand": [],
        "fit": [
            {
                "line": "security",
                "score": 4,
                "need": "",
                "service": "Diagnoza",
                "horizon": "teraz",
            }
        ],
        "references": [
            {"nr": bank_ref, "why": "Regulowany."},
            {"nr": "zmyslona", "why": "x"},
        ],
        "questions": [{"group": "Bezpieczeństwo", "text": "Kto prowadzi KSC?"}],
        "verify": [],
        "risks": [],
        "opening": "Dzień dobry.",
    }
    from app.services import llm_providers

    monkeypatch.setattr(llm_providers, "api_key_configured", lambda _m: True)
    monkeypatch.setattr(potential, "_call_model", lambda _p, _r: json.dumps(answer))
    assert await potential.assess_run(run_id) == 1

    ready = (
        await app_client.get(
            f"{COMPANIES}/{company}/potential", headers=_headers(editor)
        )
    ).json()["result"]
    assert ready["state"] == "ready"
    assert ready["ksc"]["entity"] == "kluczowy"
    assert [r["reference"]["client"] for r in ready["references"]] == [
        "Fikcyjny Bank Omega"
    ]
    assert ready["research"]["events"][0]["text"] == "Rozbudowa zakładu"


@pytest.mark.asyncio
async def test_potential_refuses_nexus_client_and_empty_knowledge(
    app_client,
    bot_on,  # noqa: F811
) -> None:
    editor = await _user("sales_edit")
    name = f"Fikcyjny Klient {uuid.uuid4().hex[:8]}"
    async with AsyncSessionLocal() as db:
        client = Client(name=name)
        db.add(client)
        await db.commit()
        client_id = client.id
    company = await _company(name, client_id=client_id)
    await _knowledge(app_client, editor)
    refused = await app_client.post(
        f"{COMPANIES}/{company}/potential", headers=_headers(editor)
    )
    assert refused.status_code == 409
    assert "klient NEXUSA" in refused.json()["detail"]
    assert bot_on == []
