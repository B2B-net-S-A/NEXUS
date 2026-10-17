"""Rytm kontaktu (etap 3, O7–O8, 17.10.2026) — ``/api/care/contracts/{id}/cadence``.

Zakres: zmiana rytmu z powodem, notatką i datą „do kiedy” (plan idzie za
rytmem: przyszłe rozmowy starego rytmu znikają, kamienie zostają), historia
i podgląd zmiany z obciążeniem opiekuna, kto może zmienić (opiekun kontraktu,
DL klienta, head back office, admin — inny TCM i Finanse nie), walidacja
(powód z listy, „do kiedy” w przyszłości, rytm już obowiązuje, kontrakt
zakończony) oraz „Pomiń” punkt planu z powodem i śladem.

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
from app.models.contract_care import CONTRACTS_CARE, CareCadencePeriod, CarePlanItem
from app.models.hr_ops import HrAuditEvent
from app.models.user import UserRole
from app.services.care import access as care_access
from app.services.care import plan as care_plan
from app.services.care.cadence_rules import add_months
from app.services.hr_foundation_schema import HR_DIVISIONS_SETTING
from tests.test_care_api import (
    care_off,  # noqa: F401  (fixture)
    care_on,  # noqa: F401  (fixture)
    headers,
    make_client,
    make_contract,
    make_user,
)

pytestmark = pytest.mark.asyncio


async def set_owner(contract_id: int, user_id: int) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(CONTRACTS_CARE)
            .where(CONTRACTS_CARE.c.id == contract_id)
            .values(care_owner_user_id=user_id)
        )
        await db.commit()


async def nightly_plan(*contract_ids: int) -> None:
    async with AsyncSessionLocal() as db:
        contracts = await care_access.live_contracts(db, contract_ids=contract_ids)
        await care_plan.ensure_plans(db, contracts, today=business_today())
        await db.commit()


async def open_rhythm(contract_id: int) -> list:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(CarePlanItem.due_on)
                    .where(
                        CarePlanItem.contract_id == contract_id,
                        CarePlanItem.kind == "cadence",
                        CarePlanItem.status == "open",
                        CarePlanItem.due_on >= business_today(),
                    )
                    .order_by(CarePlanItem.due_on)
                )
            ).all()
        )


async def audit_events(contract_id: int, action: str) -> list[HrAuditEvent]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(HrAuditEvent)
                    .where(
                        HrAuditEvent.entity_type == "contract",
                        HrAuditEvent.entity_id == str(contract_id),
                        HrAuditEvent.action == action,
                    )
                    .order_by(HrAuditEvent.id)
                )
            ).all()
        )


@pytest_asyncio.fixture
async def divisions_reset():
    """Przywraca ``app_settings['hr_divisions']`` po teście (head back office)."""

    async with AsyncSessionLocal() as db:
        row = await db.get(AppSetting, HR_DIVISIONS_SETTING)
        previous = dict(row.value) if row is not None else None
    yield
    await set_division_heads(previous or {"front_office": None, "back_office": None})


async def set_division_heads(value: dict) -> None:
    async with AsyncSessionLocal() as db:
        row = await db.get(AppSetting, HR_DIVISIONS_SETTING)
        if row is None:
            db.add(AppSetting(key=HR_DIVISIONS_SETTING, value=value))
        else:
            row.value = value
        await db.commit()


async def make_back_office_head():
    """TCM, który jest headem back office (wymaga fixture ``divisions_reset``)."""

    head = await make_user(UserRole.talent_community_manager)
    await set_division_heads({"front_office": None, "back_office": head.id})
    return head


@pytest.mark.usefixtures("care_on")
async def test_owner_changes_rhythm_and_the_plan_follows(app_client) -> None:
    owner = await make_user(UserRole.talent_community_manager)
    client_id = await make_client()
    # 200 dni po starcie: domyślnie co miesiąc.
    contract_id, _ = await make_contract(client_id, started_days_ago=200)
    await set_owner(contract_id, owner.id)
    await nightly_plan(contract_id)
    monthly = await open_rhythm(contract_id)
    assert len(monthly) >= 3
    today = business_today()
    url = f"/api/care/contracts/{contract_id}/cadence"

    before = await app_client.get(url, headers=headers(owner))
    assert before.status_code == 200, before.text
    body = before.json()
    assert body["current"]["level"] == "monthly"
    assert body["current"]["source"] == "default"
    assert body["can_edit"] is True
    assert [step["kind"] for step in body["history"]] == ["start", "program_end"]
    assert body["upcoming"][0]["due_on"] == monthly[0].isoformat()

    until = today + timedelta(days=60)
    saved = await app_client.post(
        url,
        headers=headers(owner),
        json={
            "level": "biweekly",
            "reason": "weak_feedback",
            "note": "Opinia słabsza w komunikacji — przez dwa miesiące częściej.",
            "until_on": until.isoformat(),
        },
    )
    assert saved.status_code == 201, saved.text
    data = saved.json()
    assert data["current"]["level"] == "biweekly"
    assert data["current"]["source"] == "period"
    assert data["current"]["until_on"] == until.isoformat()
    assert data["current"]["returns_to"] == "monthly"
    assert data["current"]["reason"] == "weak_feedback"
    change = [step for step in data["history"] if step["kind"] == "change"]
    assert change[-1]["author"]["id"] == owner.id
    back = next(step for step in data["history"] if step["kind"] == "return")
    assert back["on"] == (until + timedelta(days=1)).isoformat()
    assert back["future"] is True

    # Plan: co 2 tygodnie od dziś do „do kiedy”, potem co miesiąc od dnia powrotu.
    expected = [today + timedelta(days=14 * k) for k in range(1, 5)]
    expected.append(add_months(until + timedelta(days=1), 1))
    rhythm = await open_rhythm(contract_id)
    # Przyszłe rozmowy dawnego „co miesiąc” zniknęły.
    assert rhythm == [day for day in expected if day <= today + timedelta(days=120)]

    (event,) = await audit_events(contract_id, "care.cadence_set")
    assert event.actor_user_id == owner.id
    assert event.details["level"] == "biweekly"
    assert event.details["previous_level"] == "monthly"
    assert event.details["reason"] == "weak_feedback"
    assert event.details["until_on"] == until.isoformat()
    # Notatka zostaje w okresie rytmu, nie w śladzie.
    assert "note" not in event.details


@pytest.mark.usefixtures("care_on")
async def test_paused_rhythm_keeps_the_milestone_before_the_end(app_client) -> None:
    owner = await make_user(UserRole.talent_community_manager)
    client_id = await make_client()
    contract_id, _ = await make_contract(
        client_id, started_days_ago=200, end_in_days=100
    )
    await set_owner(contract_id, owner.id)
    await nightly_plan(contract_id)
    saved = await app_client.post(
        f"/api/care/contracts/{contract_id}/cadence",
        headers=headers(owner),
        json={"level": "paused", "reason": "person_request"},
    )
    assert saved.status_code == 201, saved.text
    assert await open_rhythm(contract_id) == []
    async with AsyncSessionLocal() as db:
        kinds = set(
            (
                await db.scalars(
                    select(CarePlanItem.kind).where(
                        CarePlanItem.contract_id == contract_id,
                        CarePlanItem.status == "open",
                    )
                )
            ).all()
        )
    assert "pre_end" in kinds
    assert saved.json()["upcoming"][0]["kind"] == "pre_end"


@pytest.mark.usefixtures("care_on", "divisions_reset")
async def test_who_can_change_the_rhythm(app_client) -> None:
    head = await make_back_office_head()
    owner = await make_user(UserRole.talent_community_manager)
    other_tcm = await make_user(UserRole.talent_community_manager)
    dl = await make_user(UserRole.delivery_lead)
    finance = await make_user(UserRole.finance)
    admin = await make_user(UserRole.admin)
    recruiter = await make_user(UserRole.recruiter)
    client_id = await make_client(dl=dl)
    contract_id, _ = await make_contract(client_id, started_days_ago=200)
    await set_owner(contract_id, owner.id)
    url = f"/api/care/contracts/{contract_id}/cadence"

    view = await app_client.get(url, headers=headers(other_tcm))
    assert view.status_code == 200
    assert view.json()["can_edit"] is False
    for user in (other_tcm, finance):
        denied = await app_client.post(
            url, headers=headers(user), json={"level": "quarterly", "reason": "stable"}
        )
        assert denied.status_code == 403, denied.text
        assert "opiekun kontraktu" in denied.json()["detail"]
    blocked = await app_client.get(url, headers=headers(recruiter))
    assert blocked.status_code == 403

    levels = iter(("quarterly", "milestones", "biweekly", "monthly"))
    for user in (owner, dl, head, admin):
        saved = await app_client.post(
            url,
            headers=headers(user),
            json={"level": next(levels), "reason": "other"},
        )
        assert saved.status_code == 201, (user.role, saved.text)
    async with AsyncSessionLocal() as db:
        authors = (
            await db.scalars(
                select(CareCadencePeriod.created_by)
                .where(CareCadencePeriod.contract_id == contract_id)
                .order_by(CareCadencePeriod.id)
            )
        ).all()
    assert authors == [owner.id, dl.id, head.id, admin.id]


@pytest.mark.usefixtures("care_on")
async def test_rhythm_change_is_validated(app_client) -> None:
    owner = await make_user(UserRole.talent_community_manager)
    client_id = await make_client()
    contract_id, _ = await make_contract(client_id, started_days_ago=200)
    ended_id, _ = await make_contract(
        client_id, started_days_ago=400, status=ContractStatus.ended
    )
    await set_owner(contract_id, owner.id)
    await set_owner(ended_id, owner.id)
    url = f"/api/care/contracts/{contract_id}/cadence"
    today = business_today()

    for body in (
        {"level": "biweekly"},
        {"level": "biweekly", "reason": "imported"},
        {"level": "weekly", "reason": "other"},
        {"level": "biweekly", "reason": "other", "note": "x" * 501},
        {"level": "biweekly", "reason": "other", "until_on": today.isoformat()},
    ):
        response = await app_client.post(url, headers=headers(owner), json=body)
        assert response.status_code == 422, (body, response.text)

    # Domyślne „co miesiąc” już obowiązuje — bez daty to nie jest zmiana.
    same = await app_client.post(
        url, headers=headers(owner), json={"level": "monthly", "reason": "stable"}
    )
    assert same.status_code == 409
    assert same.json()["detail"] == "Ten rytm już obowiązuje."

    ended = await app_client.post(
        f"/api/care/contracts/{ended_id}/cadence",
        headers=headers(owner),
        json={"level": "biweekly", "reason": "other"},
    )
    assert ended.status_code == 409


@pytest.mark.usefixtures("care_off")
async def test_module_off_hides_the_rhythm(app_client) -> None:
    owner = await make_user(UserRole.talent_community_manager)
    contract_id, _ = await make_contract(await make_client())
    response = await app_client.get(
        f"/api/care/contracts/{contract_id}/cadence", headers=headers(owner)
    )
    assert response.status_code == 404


@pytest.mark.usefixtures("care_on")
async def test_preview_counts_the_owner_next_month(app_client) -> None:
    owner = await make_user(UserRole.talent_community_manager)
    client_id = await make_client()
    contract_id, _ = await make_contract(client_id, started_days_ago=200)
    second_id, _ = await make_contract(client_id, started_days_ago=300)
    for cid in (contract_id, second_id):
        await set_owner(cid, owner.id)
    today = business_today()

    preview = await app_client.get(
        f"/api/care/contracts/{contract_id}/cadence",
        headers=headers(owner),
        params={"level": "biweekly"},
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()["preview"]
    assert body["level"] == "biweekly"
    assert body["returns_to"] is None
    assert [item["due_on"] for item in body["upcoming"]][:2] == [
        (today + timedelta(days=14)).isoformat(),
        (today + timedelta(days=28)).isoformat(),
    ]
    month = body["owner_month"]
    assert month["owner"]["id"] == owner.id
    # Dwa kontrakty co miesiąc: po jednej rozmowie; co 2 tygodnie: 2–3 w miesiącu.
    assert month["before"] == 2
    assert month["after"] in (3, 4)

    temporary = await app_client.get(
        f"/api/care/contracts/{contract_id}/cadence",
        headers=headers(owner),
        params={
            "level": "paused",
            "until_on": (today + timedelta(days=20)).isoformat(),
        },
    )
    assert temporary.json()["preview"]["returns_to"] == "monthly"
    bad = await app_client.get(
        f"/api/care/contracts/{contract_id}/cadence",
        headers=headers(owner),
        params={"level": "paused", "until_on": today.isoformat()},
    )
    assert bad.status_code == 422


@pytest.mark.usefixtures("care_on")
async def test_skip_needs_a_reason_and_leaves_a_trace(app_client) -> None:
    owner = await make_user(UserRole.talent_community_manager)
    client_id = await make_client()
    contract_id, _ = await make_contract(client_id, started_days_ago=10)
    await set_owner(contract_id, owner.id)
    overview = (
        await app_client.get(
            f"/api/care/contracts/{contract_id}", headers=headers(owner)
        )
    ).json()
    item = next(i for i in overview["plan"] if i["kind"] == "day_7")
    url = f"/api/care/plan-items/{item['id']}"

    bare = await app_client.patch(
        url, headers=headers(owner), json={"status": "skipped"}
    )
    assert bare.status_code == 422
    assert bare.json()["detail"] == "Podaj powód pominięcia."
    wrong = await app_client.patch(
        url, headers=headers(owner), json={"status": "skipped", "reason": "lazy"}
    )
    assert wrong.status_code == 422

    skipped = await app_client.patch(
        url,
        headers=headers(owner),
        json={"status": "skipped", "reason": "absence", "note": "Wraca za tydzień."},
    )
    assert skipped.status_code == 200, skipped.text
    row = next(i for i in skipped.json()["plan"] if i["id"] == item["id"])
    assert (row["status"], row["skip_reason"], row["skip_note"]) == (
        "skipped",
        "absence",
        "Wraca za tydzień.",
    )
    (event,) = await audit_events(contract_id, "care.plan_item_skipped")
    assert event.details == {
        "plan_item_id": item["id"],
        "kind": "day_7",
        "due_on": item["due_on"],
        "reason": "absence",
    }

    restored = await app_client.patch(
        url, headers=headers(owner), json={"status": "open"}
    )
    assert restored.status_code == 200
    row = next(i for i in restored.json()["plan"] if i["id"] == item["id"])
    assert (row["status"], row["skip_reason"], row["skip_note"]) == ("open", None, None)
    assert len(await audit_events(contract_id, "care.plan_item_restored")) == 1


@pytest.mark.usefixtures("care_on")
async def test_contract_tab_shows_the_rhythm(app_client) -> None:
    owner = await make_user(UserRole.talent_community_manager)
    contract_id, _ = await make_contract(await make_client(), started_days_ago=20)
    await set_owner(contract_id, owner.id)
    body = (
        await app_client.get(
            f"/api/care/contracts/{contract_id}", headers=headers(owner)
        )
    ).json()
    assert body["cadence"]["level"] == "biweekly"
    assert body["cadence"]["source"] == "program"
    assert body["cadence"]["can_edit"] is True
