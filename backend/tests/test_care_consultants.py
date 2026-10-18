"""Opieka · „Konsultanci” (etap 3, makieta M1, 17.10.2026) — ``GET /api/care/consultants``.

Zakres: rytm przy każdej osobie (program 90 dni, zmiana z powodem), następna
i ostatnia rozmowa, liczba rozmów w miesiącu z rytmów, „moi” z jednej
odpowiedzi, sygnały z podpowiedzią „podnieść rytm?” (opinia menedżera tylko
dla ról z D11 — Finanse jej nie widzą), portfel Delivery Leada, prawo zmiany
rytmu per wiersz, wyłączony moduł i rola bez sekcji Delivery.

Dane fikcyjne (repo jest publiczne).
"""

from __future__ import annotations

from datetime import timedelta

import pytest

import app.models  # noqa: F401  (rejestracja wszystkich mapperów)
from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.contract_care import (
    CareCadencePeriod,
    CareConversation,
    ClientFeedbackScore,
    ClientFeedbackSession,
    RedeployQueueItem,
)
from app.models.user import UserRole
from app.services.care import cadence
from app.services.care import plan as care_plan
from tests.test_care_api import (
    care_off,  # noqa: F401  (fixture)
    care_on,  # noqa: F401  (fixture)
    headers,
    make_client,
    make_contract,
    make_user,
)
from tests.test_care_cadence import nightly_plan, set_owner

pytestmark = pytest.mark.asyncio


async def _rows(app_client, user) -> dict[int, dict]:
    response = await app_client.get("/api/care/consultants", headers=headers(user))
    assert response.status_code == 200, response.text
    return {row["contract_id"]: row for row in response.json()["items"]}


@pytest.mark.usefixtures("care_on")
async def test_list_shows_rhythm_next_and_last_talk(app_client) -> None:
    owner = await make_user(UserRole.talent_community_manager)
    other = await make_user(UserRole.talent_community_manager)
    client_id = await make_client()
    fresh, _ = await make_contract(client_id, started_days_ago=20)
    steady, _ = await make_contract(client_id, started_days_ago=400)
    foreign_owner, _ = await make_contract(client_id, started_days_ago=50)
    for contract_id in (fresh, steady):
        await set_owner(contract_id, owner.id)
    await set_owner(foreign_owner, other.id)
    today = business_today()
    async with AsyncSessionLocal() as db:
        db.add(
            CareCadencePeriod(
                contract_id=steady,
                level="quarterly",
                starts_on=today - timedelta(days=5),
                reason="stable",
                note="Stabilnie, cztery lata u klienta.",
                created_by=owner.id,
            )
        )
        db.add(
            CareConversation(
                contract_id=steady,
                occurred_on=today - timedelta(days=5),
                channel="phone",
                satisfaction=4,
                note="Zapytać o certyfikat chmurowy.",
            )
        )
        await db.commit()
    await nightly_plan(fresh, steady, foreign_owner)

    rows = await _rows(app_client, owner)
    young, old, theirs = rows[fresh], rows[steady], rows[foreign_owner]
    assert (young["is_mine"], old["is_mine"], theirs["is_mine"]) == (True, True, False)
    assert young["cadence"]["level"] == "biweekly"
    assert young["cadence"]["source"] == "program"
    assert (
        young["cadence"]["until_on"]
        == (today - timedelta(days=20) + timedelta(days=89)).isoformat()
    )
    assert old["cadence"]["level"] == "quarterly"
    assert old["cadence"]["reason"] == "stable"
    assert old["cadence"]["note"] == "Stabilnie, cztery lata u klienta."
    assert old["cadence"]["author"]["id"] == owner.id
    assert old["last_conversation"]["note_excerpt"] == "Zapytać o certyfikat chmurowy."
    assert old["last_conversation"]["satisfaction"] == 4
    # Najbliższy otwarty: zaległy kamień „dzień 7” (rozmowa z rytmu z dnia 14 też czeka).
    assert young["next_contact"]["kind"] == "day_7"
    assert young["next_contact"]["due_on"] == (today - timedelta(days=13)).isoformat()
    assert young["next_contact"]["overdue_days"] == 13
    assert {"kind": "overdue", "days": 13} in young["signals"]
    assert young["can_change_cadence"] is True
    assert theirs["can_change_cadence"] is False

    async with AsyncSessionLocal() as db:
        periods = await care_plan.periods_by_contract(db, [steady])
    month = cadence.this_month(today)
    start = today - timedelta(days=400)
    assert old["conversations"]["this_month"] == care_plan.conversations_between(
        start, None, periods[steady], month[0], month[1]
    )
    nxt = cadence.next_month(today)
    assert young["conversations"]["next_month"] == care_plan.conversations_between(
        today - timedelta(days=20), None, [], nxt[0], nxt[1]
    )


@pytest.mark.usefixtures("care_on")
async def test_signals_suggest_more_contact_and_hide_feedback_outside_d11(
    app_client,
) -> None:
    owner = await make_user(UserRole.talent_community_manager)
    finance = await make_user(UserRole.finance)
    client_id = await make_client()
    weak, _ = await make_contract(client_id, started_days_ago=200)
    ending, _ = await make_contract(client_id, started_days_ago=200, end_in_days=30)
    wants, _ = await make_contract(client_id, started_days_ago=200)
    paused, _ = await make_contract(client_id, started_days_ago=200, end_in_days=20)
    for contract_id in (weak, ending, wants, paused):
        await set_owner(contract_id, owner.id)
    today = business_today()
    async with AsyncSessionLocal() as db:
        session = ClientFeedbackSession(
            client_id=client_id, held_on=today - timedelta(days=2), channel="phone"
        )
        db.add(session)
        await db.flush()
        db.add(
            ClientFeedbackScore(
                session_id=session.id,
                contract_id=weak,
                quality=3,
                communication=2,
                autonomy=3,
            )
        )
        db.add(
            RedeployQueueItem(
                contract_id=wants, reason="wants_change", status="open", source="manual"
            )
        )
        db.add(
            CareCadencePeriod(
                contract_id=paused,
                level="paused",
                starts_on=today - timedelta(days=3),
                reason="person_request",
            )
        )
        await db.commit()

    rows = await _rows(app_client, owner)
    assert rows[weak]["signals"] == [
        {
            "kind": "weak_feedback",
            "average": 2.7,
            "on": (today - timedelta(days=2)).isoformat(),
        }
    ]
    assert rows[weak]["suggested_level"] == "biweekly"
    assert rows[ending]["signals"][0] == {
        "kind": "order_end",
        "days": 30,
        "on": (today + timedelta(days=30)).isoformat(),
    }
    assert rows[ending]["suggested_level"] == "biweekly"
    assert {"kind": "wants_change"} in rows[wants]["signals"]
    # Wstrzymany zostaje wstrzymany — sygnał widać, podpowiedzi rytmu nie ma.
    assert rows[paused]["signals"][0]["kind"] == "order_end"
    assert rows[paused]["suggested_level"] is None

    seen_by_finance = await _rows(app_client, finance)
    assert seen_by_finance[weak]["signals"] == []
    assert seen_by_finance[ending]["signals"][0]["kind"] == "order_end"
    assert seen_by_finance[weak]["can_change_cadence"] is False
    response = await app_client.get("/api/care/consultants", headers=headers(finance))
    assert response.json()["feedback_visible"] is False


@pytest.mark.usefixtures("care_on")
async def test_delivery_lead_sees_own_portfolio_and_changes_its_rhythm(
    app_client,
) -> None:
    dl = await make_user(UserRole.delivery_lead)
    own_client = await make_client(dl=dl)
    foreign_client = await make_client(dl=await make_user(UserRole.delivery_lead))
    own, _ = await make_contract(own_client, started_days_ago=100)
    foreign, _ = await make_contract(foreign_client, started_days_ago=100)
    rows = await _rows(app_client, dl)
    assert own in rows and foreign not in rows
    assert rows[own]["can_change_cadence"] is True
    # DL klienta jest opiekunem z łańcucha, gdy nikt inny go nie wskazał.
    assert rows[own]["is_mine"] is True


@pytest.mark.usefixtures("care_off")
async def test_list_is_closed_when_module_off_or_without_delivery(app_client) -> None:
    tcm = await make_user(UserRole.talent_community_manager)
    off = await app_client.get("/api/care/consultants", headers=headers(tcm))
    assert off.status_code == 404


@pytest.mark.usefixtures("care_on")
async def test_recruiter_without_delivery_section_is_refused(app_client) -> None:
    recruiter = await make_user(UserRole.recruiter)
    response = await app_client.get("/api/care/consultants", headers=headers(recruiter))
    assert response.status_code == 403


@pytest.mark.usefixtures("care_on")
async def test_project_end_from_redeploy_queue_is_a_signal(app_client) -> None:
    """„Koniec projektu” z „Do przepięcia” stoi w kolumnie „Sygnał” jak w starej liście."""

    owner = await make_user(UserRole.talent_community_manager)
    client_id = await make_client()
    ending, _ = await make_contract(client_id, started_days_ago=200)
    closed, _ = await make_contract(client_id, started_days_ago=200)
    for contract_id in (ending, closed):
        await set_owner(contract_id, owner.id)
    project_end = business_today() + timedelta(days=40)
    async with AsyncSessionLocal() as db:
        db.add(
            RedeployQueueItem(
                contract_id=ending,
                reason="project_end",
                status="open",
                source="conversation",
                due_on=project_end,
            )
        )
        # Zamknięty wpis („przepięty”) nie jest już sygnałem.
        db.add(
            RedeployQueueItem(
                contract_id=closed,
                reason="project_end",
                status="done",
                source="conversation",
                due_on=project_end,
            )
        )
        await db.commit()

    rows = await _rows(app_client, owner)
    assert rows[ending]["signals"] == [
        {"kind": "project_end", "on": project_end.isoformat()}
    ]
    # Sygnał informuje; rytmu nie podpowiada (O9 go nie wymienia).
    assert rows[ending]["suggested_level"] is None
    assert rows[closed]["signals"] == []
