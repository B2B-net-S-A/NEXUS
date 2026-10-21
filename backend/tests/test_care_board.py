"""Przebudowa opieki (22.10.2026) — trasy na bazie.

Karta konsultanta i „Co u klienta”, okno „Rozmowa” w jednej transakcji
(karta z rozmowy, sprawy, popyt do DL), tablica „Do zrobienia” (karty
rozmów i decyzji, ``PUT /board/state``), popyt rozstrzygany oknem opinii
menedżera, „Klienci” i zdrowie w „Konsultantach”. Finanse bez zdrowia (D11).

Baza testowa jest wspólna — każdy test zakłada własnych klientów i osoby.
Dane fikcyjne (repo jest publiczne).
"""

from __future__ import annotations

from datetime import timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select, update

import app.models  # noqa: F401  (rejestracja wszystkich mapperów)
from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.contract import Contract
from app.models.contract_care import RedeployQueueItem
from app.models.notification import Notification, NotificationType
from app.models.team_structure import DeliveryLeadClientAssignment
from app.models.user import UserRole
from app.services.care import access as care_access
from app.services.care import plan as care_plan
from app.services.care.demand import TECH_CARDS_LINK
from app.services.hr_foundation_schema import HR_MODULE_KEYS
from tests.test_care_api import (
    _card,
    _previous_modules,
    headers,
    make_client,
    make_contract,
    make_skill,
    make_user,
    set_modules,
)
from tests.test_care_client_people import make_area, make_contact

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def care_on():
    previous = await _previous_modules()
    await set_modules({key: True for key in HR_MODULE_KEYS})
    yield
    await set_modules(previous or {key: False for key in HR_MODULE_KEYS})


async def set_manager(contract_id: int, contact_id: int) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Contract)
            .where(Contract.id == contract_id)
            .values(client_pm_contact_id=contact_id)
        )
        await db.commit()


async def assign_lead(user_id: int, client_id: int) -> None:
    async with AsyncSessionLocal() as db:
        db.add(
            DeliveryLeadClientAssignment(
                delivery_lead_user_id=user_id, client_id=client_id, is_head=False
            )
        )
        await db.commit()


async def nightly_plan(contract_id: int) -> None:
    async with AsyncSessionLocal() as db:
        contracts = await care_access.contracts_by_id(db, [contract_id])
        await care_plan.ensure_plans(
            db, list(contracts.values()), today=business_today()
        )
        await db.commit()


async def _setup():
    lead = await make_user(UserRole.delivery_lead)
    client_id = await make_client(dl=lead)
    area_id = await make_area(client_id, "Płatności")
    manager_id = await make_contact(
        client_id, "Ewa Przykładowa", position="Kierownik zespołu", area_id=area_id
    )
    contract_id, candidate_id = await make_contract(client_id, started_days_ago=10)
    await set_manager(contract_id, manager_id)
    return lead, client_id, area_id, manager_id, contract_id, candidate_id


async def test_card_shape_and_finance_without_health(app_client, care_on) -> None:
    lead, client_id, area_id, manager_id, contract_id, candidate_id = await _setup()
    skill_id, skill_name = await make_skill("Java")
    saved = await app_client.post(
        f"/api/care/contracts/{contract_id}/tech-cards",
        json=_card(skill_ids=[skill_id], client_area_id=area_id, team_size="8"),
        headers=headers(lead),
    )
    assert saved.status_code == 201, saved.text

    resp = await app_client.get(
        f"/api/care/contracts/{contract_id}/card", headers=headers(lead)
    )
    assert resp.status_code == 200, resp.text
    card = resp.json()
    assert card["contract_id"] == contract_id
    assert card["candidate_id"] == candidate_id
    assert card["client_id"] == client_id
    assert card["owner"]["user_id"] == lead.id
    assert card["cadence"]["level"] == "biweekly"
    assert card["health"]["level"] in {"ok", "watch", "risk"}
    assert card["can_see_feedback"] is True and card["can_edit"] is True
    project = card["known_project"]
    assert project["source"]["kind"] == "tech_card"
    assert project["area"] == {"id": area_id, "name": "Płatności"}
    assert project["manager"]["contact_id"] == manager_id
    assert [t["skill_id"] for t in project["technologies"]] == [skill_id]
    assert project["team_size"] == "8"
    assert isinstance(card["cases"], list)
    assert card["next_step"]["kind"] in {
        "conversation",
        "feedback",
        "front_office",
        "raise_cadence",
        None,
    }
    assert {"last_contact", "satisfaction", "manager_feedback", "order_end"} <= set(
        card["kpis"]
    )
    # Bez stawek — zmyślone kwoty kontraktu nie wychodzą.
    assert "130" not in resp.text and "100.000" not in resp.text

    state = await app_client.get(
        f"/api/care/contracts/{contract_id}/client-state", headers=headers(lead)
    )
    assert state.status_code == 200, state.text
    body = state.json()
    assert body["source"]["kind"] == "tech_card"
    assert "source" not in body["state"]
    assert body["state"]["manager"]["contact_id"] == manager_id
    keys = [q["key"] for q in body["questions"]]
    # Menedżer bez „podlega pod” to luka mapy, o którą pytamy w rozmowie.
    assert f"reports_to:{manager_id}" in keys
    assert len(keys) <= 4

    finance = await make_user(UserRole.finance)
    seen = await app_client.get(
        f"/api/care/contracts/{contract_id}/card", headers=headers(finance)
    )
    assert seen.status_code == 200, seen.text
    assert seen.json()["health"] is None
    assert seen.json()["kpis"]["manager_feedback"] is None
    assert seen.json()["can_see_feedback"] is False


async def test_conversation_window_saves_card_case_and_demand(
    app_client, care_on
) -> None:
    lead, client_id, area_id, manager_id, contract_id, _cand = await _setup()
    admin = await make_user(UserRole.admin)
    skill_id, _ = await make_skill("Kotlin")
    today = business_today()
    body = {
        "occurred_on": today.isoformat(),
        "channel": "phone",
        "satisfaction": 4,
        "client_hiring": True,
        "client_state": {
            "confirmed": True,
            "changes": {
                "skill_ids": [skill_id],
                "area_id": area_id,
                "hiring_roles": ["Java Developer"],
                "hiring_source": "widzial",
                "project_end_month": (today + timedelta(days=400)).strftime("%Y-%m"),
            },
        },
        "cases": [{"title": "Nowy laptop dla konsultanta", "area": "administration"}],
    }
    resp = await app_client.post(
        f"/api/care/contracts/{contract_id}/conversations",
        json=body,
        headers=headers(admin),
    )
    assert resp.status_code == 201, resp.text
    saved = resp.json()
    assert saved["conversation_id"]
    assert saved["tech_card_id"]
    assert len(saved["case_ids"]) == 1
    assert saved["demand_notified"] == 1
    # Stary kształt odpowiedzi (zakładka „Opieka”) zostaje.
    assert saved["contract"]["id"] == contract_id

    async with AsyncSessionLocal() as db:
        linked = await db.scalar(
            select(TECH_CARDS_LINK.c.care_conversation_id).where(
                TECH_CARDS_LINK.c.id == saved["tech_card_id"]
            )
        )
        bell = await db.scalar(
            select(Notification).where(
                Notification.user_id == lead.id,
                Notification.notification_type == NotificationType.care_demand_signal,
                Notification.related_entity_id == client_id,
            )
        )
    assert linked == saved["conversation_id"]
    key = f"demand:{client_id}:{area_id}:{saved['conversation_id']}"
    assert bell is not None and bell.link == f"/care?card={key}"

    card = await app_client.get(
        f"/api/care/contracts/{contract_id}/card", headers=headers(lead)
    )
    assert card.json()["known_project"]["source"]["kind"] == "conversation"
    assert card.json()["known_project"]["hiring"]["roles"] == ["Java Developer"]

    # Druga rozmowa w 7 dniach — ten sam DL, klient i dział: bez drugiego dzwonka.
    again = await app_client.post(
        f"/api/care/contracts/{contract_id}/conversations",
        json={**body, "cases": []},
        headers=headers(admin),
    )
    assert again.status_code == 201, again.text
    assert again.json()["demand_notified"] == 0

    board = await app_client.get("/api/care/board?scope=all", headers=headers(lead))
    assert board.status_code == 200, board.text
    demand_cards = [
        c
        for c in board.json()["cards"]
        if c["kind"] == "demand" and c["client_id"] == client_id
    ]
    # Ten sam klient, dział i role w 30 dniach = jedna karta (najnowsza rozmowa).
    assert len(demand_cards) == 1
    newest = demand_cards[0]
    assert (
        newest["key"]
        == f"demand:{client_id}:{area_id}:{again.json()['conversation_id']}"
    )
    assert newest["demand"]["roles"] == ["Java Developer"]
    assert len(newest["sources"]) == 2

    # TCM bez portfela nie rozstrzyga popytu.
    tcm = await make_user(UserRole.talent_community_manager)
    denied = await app_client.post(
        f"/api/care/clients/{client_id}/feedback",
        json={
            "held_on": today.isoformat(),
            "demand": {"key": newest["key"], "outcome": "stale"},
        },
        headers=headers(tcm),
    )
    assert denied.status_code == 403, denied.text

    resolved = await app_client.post(
        f"/api/care/clients/{client_id}/feedback",
        json={
            "contact_id": manager_id,
            "held_on": today.isoformat(),
            "demand": {
                "key": newest["key"],
                "outcome": "confirmed",
                "role": "Java Developer",
                "skill_ids": [skill_id],
            },
        },
        headers=headers(lead),
    )
    assert resolved.status_code == 201, resolved.text
    assert resolved.json()["jobs_new_url"] == (
        f"/jobs/new?client={client_id}&hm={manager_id}&skills={skill_id}"
        "&title=Java%20Developer"
    )
    assert len(resolved.json()["demand_keys"]) == 2
    after = await app_client.get("/api/care/board?scope=all", headers=headers(lead))
    assert not [
        c
        for c in after.json()["cards"]
        if c["kind"] == "demand" and c["client_id"] == client_id
    ]


async def test_conversation_window_refuses_card_without_technology(
    app_client, care_on
) -> None:
    lead, _client_id, area_id, _m, contract_id, _c = await _setup()
    resp = await app_client.post(
        f"/api/care/contracts/{contract_id}/conversations",
        json={
            "occurred_on": business_today().isoformat(),
            "client_state": {"confirmed": True, "changes": {"area_id": area_id}},
        },
        headers=headers(lead),
    )
    assert resp.status_code == 422, resp.text
    # Cała transakcja cofnięta — rozmowy nie ma.
    tab = await app_client.get(
        f"/api/care/contracts/{contract_id}", headers=headers(lead)
    )
    assert tab.json()["conversations"] == []


async def test_board_contact_card_moves_between_columns(app_client, care_on) -> None:
    lead, client_id, _a, _m, contract_id, _c = await _setup()
    await nightly_plan(contract_id)

    board = await app_client.get("/api/care/board?scope=mine", headers=headers(lead))
    assert board.status_code == 200, board.text
    cards = [c for c in board.json()["cards"] if c.get("contract_id") == contract_id]
    contact = next(c for c in cards if c["kind"] == "contact")
    assert contact["key"].startswith("contact:plan:")
    assert contact["column"] == "new"
    assert contact["overdue_days"] == 3  # dzień 7 przy starcie 10 dni temu
    assert contact["owner_user_id"] == lead.id
    assert contact["health"]["level"] == "watch"
    assert board.json()["week_end"] >= board.json()["today"]

    no_time = await app_client.put(
        "/api/care/board/state",
        json={"key": contact["key"], "column": "in_progress"},
        headers=headers(lead),
    )
    assert no_time.status_code == 422, no_time.text
    scheduled = await app_client.put(
        "/api/care/board/state",
        json={
            "key": contact["key"],
            "column": "in_progress",
            "scheduled_at": "2030-01-02T10:00:00+01:00",
            "note": "umówiona po urlopie",
        },
        headers=headers(lead),
    )
    assert scheduled.status_code == 200, scheduled.text
    again = await app_client.get("/api/care/board?scope=mine", headers=headers(lead))
    moved = next(c for c in again.json()["cards"] if c["key"] == contact["key"])
    assert moved["column"] == "in_progress"
    assert moved["scheduled_at"].startswith("2030-01-02")
    assert moved["state_note"] == "umówiona po urlopie"

    past = await app_client.put(
        "/api/care/board/state",
        json={
            "key": contact["key"],
            "column": "waiting",
            "retry_on": business_today().isoformat(),
        },
        headers=headers(lead),
    )
    assert past.status_code == 422, past.text
    back = await app_client.put(
        "/api/care/board/state",
        json={"key": contact["key"], "column": "new"},
        headers=headers(lead),
    )
    assert back.status_code == 200, back.text
    final = await app_client.get("/api/care/board?scope=mine", headers=headers(lead))
    assert (
        next(c for c in final.json()["cards"] if c["key"] == contact["key"])["column"]
        == "new"
    )

    stranger = await make_user(UserRole.delivery_lead)
    await make_client(dl=stranger)
    foreign = await app_client.put(
        "/api/care/board/state",
        json={"key": contact["key"], "column": "new"},
        headers=headers(stranger),
    )
    assert foreign.status_code == 403, foreign.text
    unknown = await app_client.put(
        "/api/care/board/state",
        json={"key": "contact:plan:999999999", "column": "new"},
        headers=headers(lead),
    )
    assert unknown.status_code == 404, unknown.text


async def test_decision_card_in_progress_moves_redeploy_entry(
    app_client, care_on
) -> None:
    lead, _client_id, _a, _m, contract_id, _c = await _setup()
    created = await app_client.post(
        f"/api/care/contracts/{contract_id}/redeploy",
        json={"reason": "wants_change"},
        headers=headers(lead),
    )
    assert created.status_code == 201, created.text
    item_id = created.json()["id"]
    board = await app_client.get("/api/care/board?scope=all", headers=headers(lead))
    decision = next(
        c for c in board.json()["cards"] if c["key"] == f"decision:{item_id}"
    )
    assert decision["column"] == "new"
    moved = await app_client.put(
        "/api/care/board/state",
        json={"key": f"decision:{item_id}", "column": "in_progress"},
        headers=headers(lead),
    )
    assert moved.status_code == 200, moved.text
    async with AsyncSessionLocal() as db:
        item = await db.get(RedeployQueueItem, item_id)
    assert item.status == "in_progress"


async def test_clients_portfolio_and_consultants_health(app_client, care_on) -> None:
    lead, client_id, _a, manager_id, contract_id, _c = await _setup()
    second, _ = await make_contract(client_id, started_days_ago=200, end_in_days=20)
    resp = await app_client.get("/api/care/clients?scope=mine", headers=headers(lead))
    assert resp.status_code == 200, resp.text
    row = next(r for r in resp.json()["rows"] if r["client_id"] == client_id)
    assert row["consultants"] == 2
    assert row["managers_known"] == 1
    assert row["structure_open"] == 1
    assert sum(row["health"].values()) == 2
    assert [e["contract_id"] for e in row["ending_60"]] == [second]
    assert row["demand"]["hiring_signal"] is False
    assert {"last_source_on", "gaps"} <= set(row["map"])

    finance = await make_user(UserRole.finance)
    hidden = await app_client.get(
        "/api/care/clients?scope=all", headers=headers(finance)
    )
    assert hidden.status_code == 200, hidden.text
    finance_row = next(r for r in hidden.json()["rows"] if r["client_id"] == client_id)
    assert finance_row["health"] is None

    listing = await app_client.get("/api/care/consultants", headers=headers(lead))
    assert listing.status_code == 200, listing.text
    item = next(i for i in listing.json()["items"] if i["contract_id"] == contract_id)
    assert item["health"]["label"] in {"Dobrze", "Uwaga", "Ryzyko"}
    assert item["redeploy_active"] is False


async def test_automation_and_switched_off_care_do_not_open_the_board(
    app_client, care_on
) -> None:
    automation = await make_user(UserRole.automation)
    resp = await app_client.get("/api/care/board", headers=headers(automation))
    assert resp.status_code == 403, resp.text
