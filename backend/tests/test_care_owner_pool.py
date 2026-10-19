"""Opieka · pula opiekunów i „Przypisz wg obłożenia” (decyzja Artura 18.10.2026).

Zakres: pula = bezpośredni podwładni przełożonego z kartoteki (pracujący,
aktywne konta) minus wykluczeni; automat daje kontrakt osobie z najmniejszą
liczbą podopiecznych (remis — kolejność po nazwisku), pomija osobę bez
dostępu do opieki; zapis bierze pary z podglądu, pomija kontrakt, który
dostał opiekuna, i odmawia, gdy opiekun wypadł z puli; wykluczonego nie da
się wybrać ręcznie; osoba z puli (Finanse) prowadzi opiekę; nowy kontrakt
dostaje opiekuna z haka startu; ustawienie zmienia tylko head back office
i admin.

Dane fikcyjne (repo jest publiczne).
"""

from __future__ import annotations

import dataclasses
from datetime import timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select

import app.models  # noqa: F401  (rejestracja wszystkich mapperów)
from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.app_setting import AppSetting
from app.models.contract import Contract
from app.models.hr_profile import EmployeeProfile
from app.models.notification import Notification, NotificationType
from app.models.user import User, UserRole
from app.services.care import access as care_access
from app.services.care import auto_assign
from app.services.care.owner_pool import POOL_SETTING
from app.services.hr import contract_hooks
from tests.test_care_api import (
    care_off,  # noqa: F401  (fixture)
    care_on,  # noqa: F401  (fixture)
    headers,
    make_client,
    make_contract,
    make_user,
)
from tests.test_care_assignment import _explicit_owner
from tests.test_care_cadence import (
    audit_events,
    divisions_reset,  # noqa: F401  (fixture)
    make_back_office_head,
    set_owner,
)

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def pool_reset():
    async with AsyncSessionLocal() as db:
        row = await db.get(AppSetting, POOL_SETTING)
        previous = dict(row.value) if row is not None else None
    yield
    async with AsyncSessionLocal() as db:
        row = await db.get(AppSetting, POOL_SETTING)
        if previous is None and row is not None:
            await db.delete(row)
        elif row is not None:
            row.value = previous
        await db.commit()


async def report_to(manager: User, *users: User, status: str = "active") -> None:
    async with AsyncSessionLocal() as db:
        for user in users:
            db.add(
                EmployeeProfile(
                    user_id=user.id,
                    manager_user_id=manager.id,
                    employment_status=status,
                )
            )
        await db.commit()


async def rename(user: User, name: str) -> None:
    async with AsyncSessionLocal() as db:
        row = await db.get(User, user.id)
        row.name = name
        await db.commit()
    user.name = name


async def configure(app_client, head: User, manager: User, *excluded: User) -> dict:
    response = await app_client.put(
        "/api/care/assignment/pool",
        headers=headers(head),
        json={
            "manager_user_id": manager.id,
            "excluded_user_ids": [u.id for u in excluded],
            "auto_new_contracts": True,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


async def pool_team():
    """Head back office z pulą: dwie osoby z Finansów, TCM, księgowa, HoR."""

    head = await make_back_office_head()
    manager = await make_user(UserRole.admin)
    first = await make_user(UserRole.finance)
    second = await make_user(UserRole.finance)
    tcm = await make_user(UserRole.talent_community_manager)
    accountant = await make_user(UserRole.finance)
    hor = await make_user(UserRole.head_of_recruitment)
    leaving = await make_user(UserRole.finance)
    await rename(first, "Aaa Pula Pierwsza")
    await rename(second, "Bbb Pula Druga")
    await rename(tcm, "Ccc Pula Trzecia")
    await report_to(manager, first, second, tcm, accountant, hor)
    await report_to(manager, leaving, status="offboarding")
    return head, manager, first, second, tcm, accountant, hor, leaving


@pytest.mark.usefixtures("care_on", "divisions_reset", "pool_reset")
async def test_pool_is_computed_from_structure_and_skips_excluded_and_no_access(
    app_client,
) -> None:
    head, manager, first, second, tcm, accountant, hor, leaving = await pool_team()
    body = await configure(app_client, head, manager, accountant)

    pool = {row["id"]: row for row in body["pool"]}
    assert set(pool) == {first.id, second.id, tcm.id, accountant.id, hor.id}
    assert leaving.id not in pool  # kończy pracę — nowych podopiecznych nie dostaje
    assert pool[accountant.id]["excluded"] is True
    assert pool[accountant.id]["eligible"] is False
    assert pool[hor.id]["sees_care"] is False and pool[hor.id]["note"]
    assert all(pool[u.id]["eligible"] for u in (first, second, tcm))
    assert body["config"]["manager"]["id"] == manager.id
    assert body["config"]["excluded_user_ids"] == [accountant.id]
    assert {"id": manager.id, "name": manager.name} in body["manager_choices"]

    overview = await app_client.get("/api/care/assignment", headers=headers(head))
    assert overview.status_code == 200, overview.text
    choices = {row["id"] for row in overview.json()["owner_choices"]}
    assert {first.id, second.id, tcm.id} <= choices
    assert accountant.id not in choices
    assert hor.id not in choices  # nie widzi Opieki — dzwonek prowadziłby na 403
    cards = {card["id"] for card in overview.json()["owners"]}
    assert {first.id, second.id} <= cards

    client_id = await make_client()
    contract_id, _ = await make_contract(client_id)
    no_access = await app_client.put(
        f"/api/care/contracts/{contract_id}/owner",
        headers=headers(head),
        json={"user_id": hor.id},
    )
    assert no_access.status_code == 422
    default = await app_client.put(
        f"/api/care/clients/{client_id}/default-owner",
        headers=headers(head),
        json={"user_id": accountant.id},
    )
    assert default.status_code == 422


@pytest.mark.usefixtures("care_on", "divisions_reset", "pool_reset")
async def test_least_loaded_gets_the_contract_ties_by_name(app_client) -> None:
    head, manager, first, second, tcm, accountant, *_ = await pool_team()
    await configure(app_client, head, manager, accountant)
    client_id = await make_client()
    busy = [(await make_contract(client_id))[0] for _ in range(2)]
    for contract_id in busy:
        await set_owner(contract_id, first.id)
    targets = [(await make_contract(client_id))[0] for _ in range(4)]

    async with AsyncSessionLocal() as db:
        contracts = await care_access.live_contracts(db, contract_ids=targets)
        result = await auto_assign.plan_for(db, contracts)
    got = [pick.owner.id for pick in result.picks]
    # 2/0/0 → druga i trzecia po kolei, potem remis 2/1/1 → znów po nazwisku.
    assert got == [second.id, tcm.id, second.id, tcm.id]
    assert result.load_before[first.id] == 2
    assert {u.id: result.load_after[u.id] for u in (first, second, tcm)} == {
        first.id: 2,
        second.id: 2,
        tcm.id: 2,
    }


@pytest.mark.usefixtures("care_on", "divisions_reset", "pool_reset")
async def test_apply_writes_the_previewed_pairs_and_skips_taken_contracts(
    app_client,
) -> None:
    head, manager, first, second, tcm, accountant, *_ = await pool_team()
    await configure(app_client, head, manager, accountant)
    client_id = await make_client()
    fresh, _ = await make_contract(client_id)
    taken, _ = await make_contract(client_id)

    preview = await app_client.get("/api/care/assignment/auto", headers=headers(head))
    assert preview.status_code == 200, preview.text
    items = {row["contract_id"]: row for row in preview.json()["items"]}
    assert fresh in items and taken in items
    assert items[fresh]["owner"]["id"] in {first.id, second.id, tcm.id}

    await set_owner(taken, tcm.id)  # ktoś zdążył ręcznie
    response = await app_client.post(
        "/api/care/assignment/auto",
        headers=headers(head),
        json={
            "items": [
                {"contract_id": fresh, "owner_user_id": first.id},
                {"contract_id": taken, "owner_user_id": second.id},
            ]
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["changed"] == 1 and response.json()["skipped"] == 1
    assert await _explicit_owner(fresh) == first.id
    assert await _explicit_owner(taken) == tcm.id
    events = await audit_events(fresh, "care.owner_set")
    assert events[-1].details["reason"] == "auto_load"

    refused = await app_client.post(
        "/api/care/assignment/auto",
        headers=headers(head),
        json={"items": [{"contract_id": taken, "owner_user_id": accountant.id}]},
    )
    assert refused.status_code == 409, refused.text


@pytest.mark.usefixtures("care_on", "divisions_reset", "pool_reset")
async def test_excluded_person_cannot_be_chosen_by_hand(app_client) -> None:
    head, manager, first, _, _, accountant, *_ = await pool_team()
    await configure(app_client, head, manager, accountant)
    client_id = await make_client()
    contract_id, _ = await make_contract(client_id)

    bulk = await app_client.post(
        "/api/care/assignment",
        headers=headers(head),
        json={
            "contract_ids": [contract_id],
            "owner_user_id": accountant.id,
            "reason": "balance_load",
        },
    )
    assert bulk.status_code == 422
    assert "nie przypisujemy" in bulk.json()["detail"]
    single = await app_client.put(
        f"/api/care/contracts/{contract_id}/owner",
        headers=headers(head),
        json={"user_id": accountant.id},
    )
    assert single.status_code == 422
    ok = await app_client.post(
        "/api/care/assignment",
        headers=headers(head),
        json={
            "contract_ids": [contract_id],
            "owner_user_id": first.id,
            "reason": "balance_load",
        },
    )
    assert ok.status_code == 200, ok.text


@pytest.mark.usefixtures("care_on", "divisions_reset", "pool_reset")
async def test_pool_member_from_finance_writes_care_and_outsider_does_not(
    app_client,
) -> None:
    head, manager, first, *_ = await pool_team()
    await configure(app_client, head, manager)
    outsider = await make_user(UserRole.finance)
    client_id = await make_client()
    contract_id, _ = await make_contract(client_id)
    body = {"occurred_on": business_today().isoformat(), "note": "Rozmowa testowa."}

    denied = await app_client.post(
        f"/api/care/contracts/{contract_id}/conversations",
        headers=headers(outsider),
        json=body,
    )
    assert denied.status_code == 403
    allowed = await app_client.post(
        f"/api/care/contracts/{contract_id}/conversations",
        headers=headers(first),
        json=body,
    )
    assert allowed.status_code == 201, allowed.text
    assert allowed.json()["can_edit"] is True
    # D11: opinię klienta zapisuje tylko krąg, który ją czyta (DL, TCM, HoR,
    # admin) — osoba z puli z Finansów prowadzi opiekę, ale opinii nie.
    feedback = await app_client.post(
        f"/api/care/clients/{client_id}/feedback",
        headers=headers(first),
        json={"contact_id": 1, "held_on": business_today().isoformat()},
    )
    assert feedback.status_code == 403, feedback.text


@pytest.mark.usefixtures("care_on", "divisions_reset", "pool_reset")
async def test_only_head_and_admin_change_the_pool(app_client) -> None:
    head, manager, *_ = await pool_team()
    tcm = await make_user(UserRole.talent_community_manager)
    payload = {"manager_user_id": manager.id, "excluded_user_ids": []}
    denied = await app_client.put(
        "/api/care/assignment/pool", headers=headers(tcm), json=payload
    )
    assert denied.status_code == 403
    preview = await app_client.get("/api/care/assignment/auto", headers=headers(tcm))
    assert preview.status_code == 403
    bad = await app_client.put(
        "/api/care/assignment/pool",
        headers=headers(head),
        json={"manager_user_id": 987654321, "excluded_user_ids": []},
    )
    assert bad.status_code == 422


@pytest.mark.usefixtures("care_off", "divisions_reset", "pool_reset")
async def test_new_contract_gets_an_owner_from_the_start_hook_silently_in_shadow(
    app_client,
) -> None:
    head, manager, first, second, tcm, accountant, *_ = await pool_team()
    async with AsyncSessionLocal() as db:
        value = {
            "manager_user_id": manager.id,
            "excluded_user_ids": [accountant.id],
            "auto_new_contracts": True,
        }
        row = await db.get(AppSetting, POOL_SETTING)
        if row is None:
            db.add(AppSetting(key=POOL_SETTING, value=value))
        else:
            row.value = value
        await db.commit()
    client_id = await make_client()
    contract_id, _ = await make_contract(client_id, started_days_ago=0)

    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        outcome = await contract_hooks.contract_started(db, contract)
        await db.commit()
    assert outcome["care"] == "ok"
    assert await _explicit_owner(contract_id) in {first.id, second.id, tcm.id}
    async with AsyncSessionLocal() as db:
        sent = await db.scalar(
            select(Notification.id).where(
                Notification.related_entity_id == contract_id,
                Notification.notification_type == NotificationType.care_contact_due,
            )
        )
    assert sent is None  # moduł wyłączony = tryb cienia, bez dzwonka


@pytest.mark.usefixtures("care_off", "divisions_reset", "pool_reset")
async def test_without_saved_pool_the_start_hook_assigns_nobody(app_client) -> None:
    """Bez zapisu puli automat nie rusza — nawet gdy head back office ma ludzi."""

    head, manager, first, *_ = await pool_team()
    from tests.test_care_cadence import set_division_heads  # noqa: PLC0415

    await set_division_heads({"front_office": None, "back_office": manager.id})
    async with AsyncSessionLocal() as db:
        row = await db.get(AppSetting, POOL_SETTING)
        if row is not None:
            await db.delete(row)
            await db.commit()
    client_id = await make_client()
    contract_id, _ = await make_contract(client_id, started_days_ago=0)
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        outcome = await contract_hooks.contract_started(db, contract)
        await db.commit()
    assert outcome["care"] == "ok"
    assert await _explicit_owner(contract_id) is None
    preview = await app_client.get(
        "/api/care/assignment/auto", headers=headers(manager)
    )
    assert preview.status_code == 200, preview.text
    config = preview.json()["config"]
    assert config["saved"] is False and config["auto_new_contracts"] is False
    assert config["manager"]["id"] == manager.id and config["manager_from_division"]


async def test_daily_sweep_takes_only_fresh_contracts(monkeypatch) -> None:
    today = business_today()
    fresh = care_access.CareContract(
        id=1,
        client_id=1,
        client_name="Firma",
        candidate_id=None,
        candidate_name=None,
        job_id=None,
        job_title=None,
        job_delivery_lead_id=None,
        status="active",
        start_date=today - timedelta(days=3),
        contract_end_date=None,
        order_end_date=None,
        explicit_owner_id=None,
        client_default_owner_id=None,
    )
    old = dataclasses.replace(fresh, id=2, start_date=today - timedelta(days=200))
    seen: list[list[int]] = []

    async def targets(db, **_):
        return [fresh, old], [fresh, old]

    async def assign_new(db, ids, *, today):
        seen.append(list(ids))
        return len(ids)

    monkeypatch.setattr(auto_assign, "targets_without_owner", targets)
    monkeypatch.setattr(auto_assign, "assign_new", assign_new)
    assert await auto_assign.sweep(None, today=today) == 1
    assert seen == [[1]]


async def test_pool_member_with_view_only_delivery_is_not_a_writer(
    monkeypatch,
) -> None:
    # Bramka CareWriter wymaga zapisu w sekcji Delivery; flagi can_edit nie
    # mogą obiecać zapisu osobie z puli, która ma tylko podgląd.
    from types import SimpleNamespace

    from app.services import section_permissions
    from app.services.care import access, owner_pool

    async def fake_writers(db):
        return frozenset({7})

    granted = {"value": section_permissions.SectionAccess.read}
    monkeypatch.setattr(owner_pool, "writer_ids", fake_writers)
    monkeypatch.setattr(
        section_permissions,
        "section_access_for_user",
        lambda user, section: granted["value"],
    )
    member = SimpleNamespace(id=7, has_any_role=lambda *roles: False)

    assert await access.is_care_writer(None, member) is False
    granted["value"] = section_permissions.SectionAccess.write
    assert await access.is_care_writer(None, member) is True


def test_recruitment_lead_outside_portfolio_is_not_the_owner() -> None:
    # Rekrutacje widać w całej firmie: DL rekrutacji u cudzego klienta nie
    # zostaje opiekunem z łańcucha (dzwonek prowadziłby na 403).
    from app.services.care import access

    contract = access.CareContract(
        id=1,
        client_id=5,
        client_name="Klient",
        candidate_id=1,
        candidate_name="Osoba",
        job_id=1,
        job_title=None,
        job_delivery_lead_id=7,
        status="active",
        start_date=None,
        contract_end_date=None,
        order_end_date=None,
        explicit_owner_id=None,
        client_default_owner_id=None,
    )
    assert access._named_owner(contract, {7}, {7: frozenset({9})}) is None
    assert access._named_owner(contract, {7}, {7: frozenset({5})}) == (
        access.OwnerChoice(7, "delivery_lead")
    )
    assert access._named_owner(contract, {7}, {7: None}) == (
        access.OwnerChoice(7, "delivery_lead")
    )
