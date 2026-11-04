"""Opieka · „Przydział” (etap 3, O10, makieta M3, 17.10.2026) — ``/api/care/assignment``.

Zakres: obciążenie opiekunów z rytmów (rozmowy w następnym miesiącu, osoby po
poziomach), „bez opiekuna” z podpowiedzią, próg jako ostrzeżenie (zapis
tylko head back office i admin, walidacja), zmiana wielu kontraktów naraz
z powodem i śladem ``care.owner_set`` (poprzedni opiekun), odmowy (DL, TCM,
opiekun spoza portfela, zakończony kontrakt) oraz oś konsultanta ze zmianą
rytmu i opiekuna.

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
from app.models.app_setting import AppSetting
from app.models.contract import ContractStatus
from app.models.contract_care import CLIENTS_CARE, CONTRACTS_CARE, CareConversation
from app.models.hr_ops import HrAuditEvent
from app.models.user import UserRole
from app.services.care import cadence
from app.services.care import plan as care_plan
from app.services.care.assignment import LOAD_THRESHOLD_SETTING
from tests.test_care_api import (
    care_on,  # noqa: F401  (fixture)
    headers,
    make_client,
    make_contract,
    make_user,
)
from tests.test_care_cadence import (
    audit_events,
    divisions_reset,  # noqa: F401  (fixture)
    make_back_office_head,
    set_division_heads,
    set_owner,
)

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def threshold_reset():
    async with AsyncSessionLocal() as db:
        row = await db.get(AppSetting, LOAD_THRESHOLD_SETTING)
        previous = dict(row.value) if row is not None else None
    yield
    async with AsyncSessionLocal() as db:
        row = await db.get(AppSetting, LOAD_THRESHOLD_SETTING)
        if previous is None and row is not None:
            await db.delete(row)
        elif row is not None:
            row.value = previous
        await db.commit()


async def _explicit_owner(contract_id: int):
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(CONTRACTS_CARE.c.care_owner_user_id).where(
                CONTRACTS_CARE.c.id == contract_id
            )
        )


@pytest.mark.usefixtures("care_on", "divisions_reset")
async def test_overview_counts_load_from_rhythms_and_flags_the_threshold(
    app_client, threshold_reset
) -> None:
    head = await make_back_office_head()
    steady = await make_user(UserRole.talent_community_manager)
    busy = await make_user(UserRole.talent_community_manager)
    idle = await make_user(UserRole.talent_community_manager)
    client_id = await make_client()
    orphan_client = await make_client()
    defaults_client = await make_client()
    monthly = [
        (await make_contract(client_id, started_days_ago=200))[0] for _ in range(2)
    ]
    for contract_id in monthly:
        await set_owner(contract_id, steady.id)
    young, _ = await make_contract(client_id, started_days_ago=10)
    await set_owner(young, busy.id)
    orphan, _ = await make_contract(orphan_client, started_days_ago=30)
    by_default, _ = await make_contract(defaults_client, started_days_ago=30)
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(CLIENTS_CARE)
            .where(CLIENTS_CARE.c.id == defaults_client)
            .values(default_care_owner_user_id=busy.id)
        )
        await db.commit()

    saved = await app_client.put(
        "/api/care/assignment/threshold",
        headers=headers(head),
        json={"monthly_conversations": 2},
    )
    assert saved.status_code == 200, saved.text
    response = await app_client.get("/api/care/assignment", headers=headers(head))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["can_assign"] is True and body["can_edit_threshold"] is True
    assert body["threshold"] == {"monthly_conversations": 2}
    cards = {card["id"]: card for card in body["owners"]}
    assert cards[steady.id]["consultants"] == 2
    assert cards[steady.id]["conversations"] == 2
    assert cards[steady.id]["by_level"] == {"monthly": 2}
    assert cards[steady.id]["over_threshold"] is False
    month = cadence.next_month(business_today())
    young_talks = care_plan.conversations_between(
        business_today() - timedelta(days=10), None, [], month[0], month[1]
    )
    by_default_talks = care_plan.conversations_between(
        business_today() - timedelta(days=30), None, [], month[0], month[1]
    )
    assert cards[busy.id]["consultants"] == 2
    assert cards[busy.id]["conversations"] == young_talks + by_default_talks
    assert cards[busy.id]["over_threshold"] is True
    # TCM bez konsultantów też jest na liście — do niego można przypisać.
    assert cards[idle.id]["consultants"] == 0
    assert body["counts"]["without_owner"] >= 1

    rows = {row["contract_id"]: row for row in body["items"]}
    assert rows[orphan]["owner"] is None
    assert rows[orphan]["hint"] == "no_default"
    assert rows[by_default]["hint"] == "client"
    assert rows[by_default]["owner"]["id"] == busy.id
    assert rows[monthly[0]]["hint"] == "contract"
    assert rows[monthly[0]]["cadence_level"] == "monthly"
    assert {c["id"] for c in body["clients"]} >= {client_id, orphan_client}


@pytest.mark.usefixtures("care_on", "divisions_reset")
async def test_overview_counts_done_of_planned_this_month(app_client) -> None:
    """„Zrobione w miesiącu” (P6): rozmowy z bieżącego miesiąca z planu rytmów."""

    head = await make_back_office_head()
    owner = await make_user(UserRole.talent_community_manager)
    idle = await make_user(UserRole.talent_community_manager)
    client_id = await make_client()
    contract_id, _ = await make_contract(client_id, started_days_ago=200)
    await set_owner(contract_id, owner.id)
    today = business_today()
    current = cadence.this_month(today)
    async with AsyncSessionLocal() as db:
        db.add(
            CareConversation(
                contract_id=contract_id,
                occurred_on=current[0],
                channel="phone",
                satisfaction=4,
            )
        )
        # Rozmowa z poprzedniego miesiąca się nie liczy.
        db.add(
            CareConversation(
                contract_id=contract_id,
                occurred_on=current[0] - timedelta(days=1),
                channel="phone",
            )
        )
        await db.commit()

    response = await app_client.get("/api/care/assignment", headers=headers(head))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["this_month"]["from"] == current[0].isoformat()
    cards = {card["id"]: card for card in body["owners"]}
    assert cards[owner.id]["done_this_month"] == 1
    assert cards[owner.id]["planned_this_month"] == care_plan.conversations_between(
        today - timedelta(days=200), None, [], current[0], current[1]
    )
    assert cards[owner.id]["is_tcm"] is True
    assert cards[idle.id]["done_this_month"] == 0
    assert cards[idle.id]["planned_this_month"] == 0


@pytest.mark.usefixtures("care_on", "divisions_reset")
async def test_threshold_is_validated_and_only_for_head_and_admin(
    app_client, threshold_reset
) -> None:
    head = await make_back_office_head()
    tcm = await make_user(UserRole.talent_community_manager)
    url = "/api/care/assignment/threshold"
    denied = await app_client.put(
        url, headers=headers(tcm), json={"monthly_conversations": 10}
    )
    assert denied.status_code == 403
    assert "head back office" in denied.json()["detail"]
    for value in (0, 1001):
        bad = await app_client.put(
            url,
            headers=headers(head),
            json={"monthly_conversations": value},
        )
        assert bad.status_code == 422
    cleared = await app_client.put(
        url, headers=headers(head), json={"monthly_conversations": None}
    )
    assert cleared.json() == {"monthly_conversations": None}
    view = await app_client.get("/api/care/assignment", headers=headers(tcm))
    assert view.status_code == 200
    assert view.json()["can_assign"] is False


@pytest.mark.usefixtures("care_on", "divisions_reset")
async def test_head_assigns_many_with_reason_and_trace(app_client) -> None:
    head = await make_back_office_head()
    dl = await make_user(UserRole.delivery_lead)
    target = await make_user(UserRole.talent_community_manager)
    client_id = await make_client(dl=dl)
    first, _ = await make_contract(client_id, started_days_ago=30)
    second, _ = await make_contract(client_id, started_days_ago=30)
    previous = await make_user(UserRole.talent_community_manager)
    await set_owner(second, previous.id)

    response = await app_client.post(
        "/api/care/assignment",
        headers=headers(head),
        json={
            "contract_ids": [first, second],
            "owner_user_id": target.id,
            "reason": "balance_load",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["changed"] == 2
    assert await _explicit_owner(first) == target.id
    assert await _explicit_owner(second) == target.id
    (event,) = await audit_events(first, "care.owner_set")
    assert event.details == {
        "previous": None,
        "previous_effective": dl.id,
        "owner": target.id,
        "reason": "balance_load",
        "bulk": True,
    }
    (event,) = await audit_events(second, "care.owner_set")
    assert event.details["previous"] == previous.id

    again = await app_client.post(
        "/api/care/assignment",
        headers=headers(head),
        json={
            "contract_ids": [first, second],
            "owner_user_id": target.id,
            "reason": "balance_load",
        },
    )
    assert again.json()["changed"] == 0 and again.json()["unchanged"] == 2
    assert len(await audit_events(first, "care.owner_set")) == 1

    timeline = await app_client.get(
        f"/api/care/contracts/{first}/timeline", headers=headers(target)
    )
    owner_event = next(e for e in timeline.json()["events"] if e["kind"] == "owner")
    assert owner_event["title"] == f"Opiekun: {target.name}"
    assert owner_event["detail"].startswith("wyrównanie obciążenia")


@pytest.mark.usefixtures("care_on")
async def test_bulk_assign_is_refused_outside_head_and_admin(app_client) -> None:
    dl = await make_user(UserRole.delivery_lead)
    tcm = await make_user(UserRole.talent_community_manager)
    admin = await make_user(UserRole.admin)
    client_id = await make_client(dl=dl)
    contract_id, _ = await make_contract(client_id)
    body = {
        "contract_ids": [contract_id],
        "owner_user_id": tcm.id,
        "reason": "new_consultants",
    }
    for user in (dl, tcm):
        denied = await app_client.post(
            "/api/care/assignment", headers=headers(user), json=body
        )
        assert denied.status_code == 403, denied.text
    allowed = await app_client.post(
        "/api/care/assignment", headers=headers(admin), json=body
    )
    assert allowed.status_code == 200, allowed.text


@pytest.mark.usefixtures("care_on", "divisions_reset")
async def test_bulk_assign_validates_owner_and_selection(app_client) -> None:
    head = await make_back_office_head()
    recruiter = await make_user(UserRole.recruiter)
    outsider_dl = await make_user(UserRole.delivery_lead)
    tcm = await make_user(UserRole.talent_community_manager)
    client_id = await make_client(dl=await make_user(UserRole.delivery_lead))
    live, _ = await make_contract(client_id)
    ended, _ = await make_contract(
        client_id, started_days_ago=400, status=ContractStatus.ended
    )
    url = "/api/care/assignment"

    def body(**overrides):
        return {
            "contract_ids": [live],
            "owner_user_id": tcm.id,
            "reason": "other",
            **overrides,
        }

    for payload, detail in (
        (body(owner_user_id=recruiter.id), "Opiekunem może być"),
        (body(owner_user_id=outsider_dl.id), "nie ma w portfelu klientów"),
        (body(contract_ids=[live, ended]), "odśwież listę"),
    ):
        response = await app_client.post(url, headers=headers(head), json=payload)
        assert response.status_code == 422, response.text
        assert detail in response.json()["detail"]
    for payload in (
        body(contract_ids=[]),
        body(contract_ids=list(range(1, 502))),
        body(reason="because"),
    ):
        response = await app_client.post(url, headers=headers(head), json=payload)
        assert response.status_code == 422
    assert await _explicit_owner(live) is None


@pytest.mark.usefixtures("care_on")
async def test_timeline_shows_rhythm_changes_and_return(app_client) -> None:
    owner = await make_user(UserRole.talent_community_manager)
    contract_id, _ = await make_contract(await make_client(), started_days_ago=200)
    await set_owner(contract_id, owner.id)
    until = business_today() + timedelta(days=30)
    saved = await app_client.post(
        f"/api/care/contracts/{contract_id}/cadence",
        headers=headers(owner),
        json={
            "level": "biweekly",
            "reason": "wants_change",
            "until_on": until.isoformat(),
        },
    )
    assert saved.status_code == 201, saved.text
    timeline = await app_client.get(
        f"/api/care/contracts/{contract_id}/timeline", headers=headers(owner)
    )
    events = timeline.json()["events"]
    change = next(e for e in events if e["kind"] == "cadence")
    assert change["title"] == "Rytm: co 2 tygodnie"
    assert change["detail"].startswith("chce zmiany projektu")
    assert owner.name in change["detail"]
    back = next(e for e in events if e["kind"] == "cadence_return")
    assert back["title"] == "Rytm wraca: co miesiąc"
    assert back["on"] == (until + timedelta(days=1)).isoformat()
    assert back["future"] is True


@pytest.mark.usefixtures("care_on", "divisions_reset")
async def test_back_office_head_without_delivery_reads_changes_and_assigns(
    app_client, threshold_reset
) -> None:
    """O8 i O10: head back office to dowolne konto — także bez sekcji Delivery.

    Czyta „Konsultantów” i „Przydział” u wszystkich klientów, zmienia rytm
    i przydziela opiekunów; takie samo konto bez funkcji head back office dostaje 403.
    """

    head = await make_user(UserRole.user)
    plain = await make_user(UserRole.user)
    await set_division_heads({"front_office": None, "back_office": head.id})
    dl = await make_user(UserRole.delivery_lead)
    target = await make_user(UserRole.talent_community_manager)
    contract_id, _ = await make_contract(await make_client(dl=dl), started_days_ago=200)
    cadence_url = f"/api/care/contracts/{contract_id}/cadence"
    assign_body = {
        "contract_ids": [contract_id],
        "owner_user_id": target.id,
        "reason": "balance_load",
    }

    listing = await app_client.get("/api/care/consultants", headers=headers(head))
    assert listing.status_code == 200, listing.text
    row = next(r for r in listing.json()["items"] if r["contract_id"] == contract_id)
    assert row["can_change_cadence"] is True
    view = await app_client.get(cadence_url, headers=headers(head))
    assert view.status_code == 200, view.text
    assert view.json()["can_edit"] is True
    saved = await app_client.post(
        cadence_url,
        headers=headers(head),
        json={"level": "quarterly", "reason": "stable"},
    )
    assert saved.status_code == 201, saved.text
    overview = await app_client.get("/api/care/assignment", headers=headers(head))
    assert overview.status_code == 200, overview.text
    assert overview.json()["can_assign"] is True
    assert contract_id in {r["contract_id"] for r in overview.json()["items"]}
    assigned = await app_client.post(
        "/api/care/assignment", headers=headers(head), json=assign_body
    )
    assert assigned.status_code == 200, assigned.text
    assert assigned.json()["changed"] == 1
    threshold = await app_client.put(
        "/api/care/assignment/threshold",
        headers=headers(head),
        json={"monthly_conversations": 40},
    )
    assert threshold.status_code == 200, threshold.text

    for method, url, body in (
        ("GET", "/api/care/consultants", None),
        ("GET", cadence_url, None),
        ("POST", cadence_url, {"level": "monthly", "reason": "stable"}),
        ("GET", "/api/care/assignment", None),
        ("POST", "/api/care/assignment", assign_body),
        ("PUT", "/api/care/assignment/threshold", {"monthly_conversations": 5}),
    ):
        denied = await app_client.request(
            method, url, headers=headers(plain), json=body
        )
        assert denied.status_code == 403, (method, url, denied.text)


@pytest.mark.usefixtures("care_on", "divisions_reset")
async def test_back_office_head_sees_every_client_not_only_a_portfolio(
    app_client,
) -> None:
    """Head back office z rolą Delivery Leada: zakres wszystkich klientów."""

    head = await make_user(UserRole.delivery_lead)
    await set_division_heads({"front_office": None, "back_office": head.id})
    target = await make_user(UserRole.talent_community_manager)
    foreign, _ = await make_contract(
        await make_client(dl=await make_user(UserRole.delivery_lead)),
        started_days_ago=200,
    )

    listing = await app_client.get("/api/care/consultants", headers=headers(head))
    assert foreign in {r["contract_id"] for r in listing.json()["items"]}
    view = await app_client.get(
        f"/api/care/contracts/{foreign}/cadence", headers=headers(head)
    )
    assert view.status_code == 200, view.text
    overview = await app_client.get("/api/care/assignment", headers=headers(head))
    assert foreign in {r["contract_id"] for r in overview.json()["items"]}
    assigned = await app_client.post(
        "/api/care/assignment",
        headers=headers(head),
        json={
            "contract_ids": [foreign],
            "owner_user_id": target.id,
            "reason": "client_change",
        },
    )
    assert assigned.status_code == 200, assigned.text
    assert await _explicit_owner(foreign) == target.id


@pytest.mark.usefixtures("care_on")
async def test_timeline_names_the_work_handover_as_owner_change_reason(
    app_client,
) -> None:
    """Przekazanie pracy przy odejściu opiekuna (``hr.handover``) ma etykietę."""

    leaver = await make_user(UserRole.talent_community_manager)
    receiver = await make_user(UserRole.talent_community_manager)
    contract_id, _ = await make_contract(await make_client(), started_days_ago=60)
    await set_owner(contract_id, receiver.id)
    async with AsyncSessionLocal() as db:
        # Ten sam ślad, który zapisuje ``handover._transfer_care``.
        db.add(
            HrAuditEvent(
                actor_user_id=None,
                subject_user_id=receiver.id,
                entity_type="contract",
                entity_id=str(contract_id),
                action="care.owner_set",
                details={
                    "previous": leaver.id,
                    "owner": receiver.id,
                    "reason": "handover",
                    "source": "hr_work_handover",
                },
            )
        )
        await db.commit()

    timeline = await app_client.get(
        f"/api/care/contracts/{contract_id}/timeline", headers=headers(receiver)
    )
    assert timeline.status_code == 200, timeline.text
    event = next(e for e in timeline.json()["events"] if e["kind"] == "owner")
    assert event["title"] == f"Opiekun: {receiver.name}"
    assert event["detail"] == "przekazanie pracy przy odejściu opiekuna"
