"""Zgody na wydatki i premie poza umową — ``/api/hr/approval-requests`` (0483).

Droga zgody: wydatek do progu zamyka przełożony autora, ponad próg przełożony
popiera, a decyduje zatwierdzający z Ustawień; premia poza umową idzie prosto
do zatwierdzającego i po „Zatwierdź” jest przyznaną premią w Płacach. Nikt nie
decyduje we własnej sprawie, druga decyzja dostaje 409, obcy — 404.
Router jest wpinany do ``app/main.py`` przez koordynatora, więc test stawia
własną aplikację z samym tym routerem. Dane fikcyjne (repo jest publiczne).
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.api import hr_approvals, hr_people
from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.core.security import create_access_token
from app.models.app_setting import AppSetting
from app.models.hr_approval import ApprovalRequest
from app.models.hr_payroll import HrBonus
from app.models.hr_profile import EmployeeProfile
from app.models.notification import Notification, NotificationType
from app.models.section_permission import UserActionOverride
from app.models.user import User, UserRole
from app.services.hr.approvals import mail as approval_mail
from app.services.hr_approvals_schema import RULES_SETTING
from app.services.hr_foundation_schema import HR_MODULE_KEYS, HR_MODULES_SETTING

BASE = "/api/hr/approval-requests"


def _headers(user: User) -> dict[str, str]:
    token = create_access_token(subject=user.id, role=user.role.value)
    return {"Authorization": f"Bearer {token}"}


async def _user(
    db, role: str = "employee", *, manager: User | None = None, profile: bool = True
) -> User:
    marker = uuid.uuid4().hex[:10]
    user = User(
        email=f"hr-approvals-{marker}@example.com",
        name=f"Osoba {marker}",
        role=UserRole(role),
        roles=[role],
        is_active=True,
    )
    db.add(user)
    await db.flush()
    if profile:
        db.add(
            EmployeeProfile(
                user_id=user.id, manager_user_id=manager.id if manager else None
            )
        )
        await db.flush()
    return user


async def _put_setting(key: str, value) -> None:
    async with AsyncSessionLocal() as db:
        row = await db.get(AppSetting, key)
        if row is None:
            if value is not None:
                db.add(AppSetting(key=key, value=value))
        elif value is None:
            await db.delete(row)
        else:
            row.value = value
        await db.commit()


async def _get_setting(key: str):
    async with AsyncSessionLocal() as db:
        return await db.scalar(select(AppSetting.value).where(AppSetting.key == key))


@pytest_asyncio.fixture
async def team():
    """Zatwierdzający (admin), przełożony, dwie osoby z zespołu i obcy;
    moduł „Zgody” włączony, zatwierdzający ustawiony w zasadach."""

    previous_modules = await _get_setting(HR_MODULES_SETTING)
    previous_rules = await _get_setting(RULES_SETTING)
    async with AsyncSessionLocal() as db:
        ceo = await _user(db, "admin", profile=False)
        boss = await _user(db, "recruiter")
        worker = await _user(db, manager=boss)
        colleague = await _user(db, manager=boss)
        stranger = await _user(db)
        await db.commit()
    await _put_setting(HR_MODULES_SETTING, {key: True for key in HR_MODULE_KEYS})
    await _put_setting(
        RULES_SETTING,
        {"final_approver_user_id": ceo.id, "supervisor_limits": {"trip": 1500}},
    )
    yield {
        "ceo": ceo,
        "boss": boss,
        "worker": worker,
        "colleague": colleague,
        "stranger": stranger,
    }
    await _put_setting(
        HR_MODULES_SETTING, previous_modules or {key: False for key in HR_MODULE_KEYS}
    )
    await _put_setting(RULES_SETTING, previous_rules)


@pytest_asyncio.fixture
async def client():
    app = FastAPI()
    app.include_router(hr_approvals.router, prefix=BASE)
    # `/api/hr/config` — źródło `open_modules` dla menu i ekranów.
    app.include_router(hr_people.router, prefix="/api/hr")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as c:
        yield c


def _trip(amount: str) -> dict:
    return {
        "kind": "trip",
        "title": "Delegacja Gdańsk — warsztat u klienta",
        "purpose": "Warsztat z hiring managerem, dwie rekrutacje.",
        "amount": amount,
        "payer": "reimbursement",
    }


#: Podstawa premii w umowie — kartoteka testowa ma domyślnie formę B2B (0491).
BASIS = "§ 6 ust. 2 umowy z 01.03.2025"


def _bonus(
    person: User, amount: str = "1500", *, basis: str | None = BASIS
) -> dict:
    today = business_today()
    return {
        "kind": "bonus",
        "title": "Trzy przejęte rekrutacje",
        "purpose": "Przejęła trzy rekrutacje i domknęła je w dwa tygodnie.",
        "amount": amount,
        "beneficiary_user_id": person.id,
        "payout_year": today.year,
        "payout_month": today.month,
        "contract_basis": basis,
    }


async def _set_form(user: User, employment_type: str, *, pending: bool = False) -> None:
    async with AsyncSessionLocal() as db:
        profile = await db.scalar(
            select(EmployeeProfile).where(EmployeeProfile.user_id == user.id)
        )
        profile.employment_type = employment_type
        profile.employment_type_pending = pending
        await db.commit()


async def _notifications(user: User, ntype: NotificationType) -> list[Notification]:
    async with AsyncSessionLocal() as db:
        return list(
            await db.scalars(
                select(Notification).where(
                    Notification.user_id == user.id,
                    Notification.notification_type == ntype,
                )
            )
        )


@pytest.mark.asyncio
async def test_trip_within_limit_is_closed_by_the_supervisor(client, team) -> None:
    worker, boss, ceo = team["worker"], team["boss"], team["ceo"]
    created = await client.post(BASE, json=_trip("980"), headers=_headers(worker))
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["status"] == "pending_supervisor"
    assert body["supervisor_name"] == boss.name
    assert body["needs_final"] is False
    assert len(await _notifications(boss, NotificationType.hr_approval_requested)) == 1
    # Zatwierdzający nie dostaje dzwonka, dopóki sprawa jest u przełożonego.
    assert not await _notifications(ceo, NotificationType.hr_approval_requested)

    inbox = (await client.get(BASE, headers=_headers(boss))).json()["items"]
    assert [item["id"] for item in inbox] == [body["id"]]
    assert (await client.get(f"{BASE}/count", headers=_headers(boss))).json() == {
        "inbox": 1
    }

    decided = await client.post(
        f"{BASE}/{body['id']}/decide",
        json={"action": "approve"},
        headers=_headers(boss),
    )
    assert decided.status_code == 200, decided.text
    assert decided.json()["status"] == "approved"
    assert decided.json()["decided_by_name"] == boss.name
    (decided_note,) = await _notifications(worker, NotificationType.hr_approval_decided)
    # Autor ląduje w „Moich zgodach”, nie w skrzynce decydującego.
    assert decided_note.link == f"/my-time?tab=consents&request={body['id']}"


@pytest.mark.asyncio
async def test_trip_over_limit_is_endorsed_then_decided_by_the_approver(
    client, team
) -> None:
    worker, boss, ceo = team["worker"], team["boss"], team["ceo"]
    created = (
        await client.post(BASE, json=_trip("2400"), headers=_headers(worker))
    ).json()
    assert created["needs_final"] is True

    # Przełożony popiera tak, jak jest — inna kwota to decyzja zatwierdzającego.
    other_amount = await client.post(
        f"{BASE}/{created['id']}/decide",
        json={"action": "approve", "amount": "2000"},
        headers=_headers(boss),
    )
    assert other_amount.status_code == 422
    endorsed = await client.post(
        f"{BASE}/{created['id']}/decide",
        json={"action": "approve", "note": "Ważny klient"},
        headers=_headers(boss),
    )
    assert endorsed.json()["status"] == "pending_final"
    assert endorsed.json()["endorsed_by_name"] == boss.name
    assert await _notifications(ceo, NotificationType.hr_approval_requested)

    late = await client.post(
        f"{BASE}/{created['id']}/decide",
        json={"action": "approve"},
        headers=_headers(boss),
    )
    assert late.status_code == 403

    approved = await client.post(
        f"{BASE}/{created['id']}/decide",
        json={"action": "approve", "amount": "2100"},
        headers=_headers(ceo),
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    assert approved.json()["decided_amount"] == "2100.00"

    again = await client.post(
        f"{BASE}/{created['id']}/decide",
        json={"action": "reject", "note": "nie"},
        headers=_headers(ceo),
    )
    assert again.status_code == 409


@pytest.mark.asyncio
async def test_bonus_goes_to_the_approver_and_lands_in_payroll_as_assigned(
    client, team
) -> None:
    worker, boss, ceo = team["worker"], team["boss"], team["ceo"]
    created = await client.post(BASE, json=_bonus(worker), headers=_headers(boss))
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["status"] == "pending_final"
    assert body["beneficiary_name"] == worker.name
    assert body["contract_basis"] == BASIS

    # Osoba z premii nie widzi prośby, autor nie decyduje o własnej.
    hidden = await client.get(f"{BASE}/{body['id']}", headers=_headers(worker))
    assert hidden.status_code == 404
    own = await client.post(
        f"{BASE}/{body['id']}/decide",
        json={"action": "approve"},
        headers=_headers(boss),
    )
    assert own.status_code == 403

    detail = (await client.get(f"{BASE}/{body['id']}", headers=_headers(ceo))).json()
    assert detail["can_decide"] is True
    assert detail["context"]["beneficiary_year"]["outside_contract"] == "0.00"

    approved = await client.post(
        f"{BASE}/{body['id']}/decide", json={"action": "approve"}, headers=_headers(ceo)
    )
    assert approved.status_code == 200, approved.text
    async with AsyncSessionLocal() as db:
        request = await db.get(ApprovalRequest, body["id"])
        bonus = await db.get(HrBonus, request.bonus_id)
    assert bonus.status == "assigned"
    assert bonus.recipient_user_id == worker.id
    assert bonus.assigned_by == ceo.id
    assert bonus.proposed_by == boss.id
    assert bonus.amount == Decimal("1500.00")
    assert bonus.rule_snapshot == {
        "approval_request_id": body["id"],
        "contract_basis": BASIS,
    }
    # Osoba z premii widzi stały opis z podstawą w umowie, nie treść prośby —
    # na B2B (forma domyślna kartoteki) bez „premii poza umową” (21.10.2026).
    assert bonus.description == f"Wynagrodzenie dodatkowe · podstawa: {BASIS}"
    notices = await _notifications(worker, NotificationType.hr_bonus_assigned)
    assert [n.title for n in notices] == ["Masz nowe wynagrodzenie dodatkowe"]


@pytest.mark.asyncio
async def test_bonus_amount_has_the_payroll_ceiling(client, team) -> None:
    worker, boss, ceo = team["worker"], team["boss"], team["ceo"]
    too_big = await client.post(
        BASE, json=_bonus(worker, amount="2000000"), headers=_headers(boss)
    )
    assert too_big.status_code == 422
    created = (
        await client.post(BASE, json=_bonus(worker), headers=_headers(boss))
    ).json()
    raised = await client.post(
        f"{BASE}/{created['id']}/decide",
        json={"action": "approve", "amount": "1000001"},
        headers=_headers(ceo),
    )
    assert raised.status_code == 422
    async with AsyncSessionLocal() as db:
        request = await db.get(ApprovalRequest, created["id"])
    assert request.status == "pending_final"


@pytest.mark.asyncio
async def test_bonus_only_from_supervisor_or_payroll_and_never_for_self(
    client, team
) -> None:
    worker, colleague, boss = team["worker"], team["colleague"], team["boss"]
    not_manager = await client.post(
        BASE, json=_bonus(colleague), headers=_headers(worker)
    )
    assert not_manager.status_code == 403
    for_self = await client.post(BASE, json=_bonus(boss), headers=_headers(boss))
    assert for_self.status_code == 403

    async with AsyncSessionLocal() as db:
        payroll = await _user(db, "recruiter")
        db.add(
            UserActionOverride(user_id=payroll.id, action="payroll", access="manage")
        )
        await db.commit()
    from_payroll = await client.post(
        BASE, json=_bonus(colleague), headers=_headers(payroll)
    )
    assert from_payroll.status_code == 201, from_payroll.text


@pytest.mark.asyncio
async def test_b2b_bonus_without_contract_basis_is_refused(client, team) -> None:
    worker, boss = team["worker"], team["boss"]
    await _set_form(worker, "b2b")
    people = (
        await client.get(f"{BASE}/beneficiaries", headers=_headers(boss))
    ).json()["items"]
    assert {row["user_id"]: row["needs_contract_basis"] for row in people}[
        worker.id
    ] is True

    missing = await client.post(
        BASE, json=_bonus(worker, basis=None), headers=_headers(boss)
    )
    assert missing.status_code == 422
    assert "B2B" in missing.json()["detail"]
    blank = await client.post(
        BASE, json=_bonus(worker, basis="   "), headers=_headers(boss)
    )
    assert blank.status_code == 422
    # Bez punktu ani numeru aneksu to nie jest podstawa.
    vague = await client.post(
        BASE, json=_bonus(worker, basis="zgodnie z umową"), headers=_headers(boss)
    )
    assert vague.status_code == 422
    async with AsyncSessionLocal() as db:
        assert not list(
            await db.scalars(
                select(ApprovalRequest.id).where(
                    ApprovalRequest.beneficiary_user_id == worker.id
                )
            )
        )

    created = await client.post(
        BASE,
        json=_bonus(worker, basis="  Aneks nr 3   z 15.10.2026 "),
        headers=_headers(boss),
    )
    assert created.status_code == 201, created.text
    assert created.json()["contract_basis"] == "Aneks nr 3 z 15.10.2026"

    # Poprawka nie gubi wymogu: bez podstawy wraca 422, zgoda zostaje.
    fixed = await client.put(
        f"{BASE}/{created.json()['id']}",
        json=_bonus(worker, basis=None),
        headers=_headers(boss),
    )
    assert fixed.status_code == 422
    detail = await client.get(
        f"{BASE}/{created.json()['id']}", headers=_headers(team["ceo"])
    )
    assert detail.json()["contract_basis"] == "Aneks nr 3 z 15.10.2026"


@pytest.mark.asyncio
async def test_bonus_for_pending_form_needs_contract_basis_too(client, team) -> None:
    worker, boss = team["worker"], team["boss"]
    # Kartoteka założona z konta: forma „do uzupełnienia” liczy się jak B2B.
    await _set_form(worker, "uop", pending=True)
    missing = await client.post(
        BASE, json=_bonus(worker, basis=None), headers=_headers(boss)
    )
    assert missing.status_code == 422
    created = await client.post(BASE, json=_bonus(worker), headers=_headers(boss))
    assert created.status_code == 201, created.text


@pytest.mark.asyncio
async def test_employment_and_mandate_bonus_need_no_contract_basis(
    client, team
) -> None:
    worker, colleague, boss, ceo = (
        team["worker"],
        team["colleague"],
        team["boss"],
        team["ceo"],
    )
    await _set_form(worker, "uop")
    await _set_form(colleague, "zlecenie")
    people = (
        await client.get(f"{BASE}/beneficiaries", headers=_headers(boss))
    ).json()["items"]
    needs = {row["user_id"]: row["needs_contract_basis"] for row in people}
    assert needs[worker.id] is False and needs[colleague.id] is False

    for person in (worker, colleague):
        created = await client.post(
            BASE, json=_bonus(person, basis=None), headers=_headers(boss)
        )
        assert created.status_code == 201, created.text
        assert created.json()["contract_basis"] is None

    approved = await client.post(
        f"{BASE}/{created.json()['id']}/decide",
        json={"action": "approve"},
        headers=_headers(ceo),
    )
    assert approved.status_code == 200, approved.text
    async with AsyncSessionLocal() as db:
        request = await db.get(ApprovalRequest, created.json()["id"])
        bonus = await db.get(HrBonus, request.bonus_id)
    # Ostatnia zgoda jest dla osoby na zleceniu: „wynagrodzenie dodatkowe”,
    # nie „premia poza umową” (decyzja Artura 21.10.2026).
    assert bonus.description == "Wynagrodzenie dodatkowe"
    assert bonus.rule_snapshot == {"approval_request_id": request.id}


@pytest.mark.asyncio
async def test_contract_basis_only_on_bonus(client, team) -> None:
    trip = {**_trip("500"), "contract_basis": BASIS}
    refused = await client.post(BASE, json=trip, headers=_headers(team["worker"]))
    assert refused.status_code == 422


@pytest.mark.asyncio
async def test_returned_request_is_fixed_and_sent_again_or_withdrawn(
    client, team
) -> None:
    worker, boss = team["worker"], team["boss"]
    created = (
        await client.post(BASE, json=_trip("900"), headers=_headers(worker))
    ).json()
    no_reason = await client.post(
        f"{BASE}/{created['id']}/decide",
        json={"action": "return"},
        headers=_headers(boss),
    )
    assert no_reason.status_code == 422
    returned = await client.post(
        f"{BASE}/{created['id']}/decide",
        json={"action": "return", "note": "Dopisz, ile nocy w hotelu."},
        headers=_headers(boss),
    )
    assert returned.json()["status"] == "returned"
    assert returned.json()["can_decide"] is False

    mine = (await client.get(f"{BASE}?scope=mine", headers=_headers(worker))).json()
    (item,) = [i for i in mine["items"] if i["id"] == created["id"]]
    assert (
        item["can_edit"] is True
        and item["decision_note"] == "Dopisz, ile nocy w hotelu."
    )

    fixed = {**_trip("950"), "purpose": "Warsztat, jedna noc w hotelu."}
    stranger_edit = await client.put(
        f"{BASE}/{created['id']}", json=fixed, headers=_headers(team["stranger"])
    )
    assert stranger_edit.status_code == 404
    again = await client.put(
        f"{BASE}/{created['id']}", json=fixed, headers=_headers(worker)
    )
    assert again.status_code == 200, again.text
    assert again.json()["status"] == "pending_supervisor"
    assert again.json()["decision_note"] is None

    withdrawn = await client.post(
        f"{BASE}/{created['id']}/withdraw", headers=_headers(worker)
    )
    assert withdrawn.json()["status"] == "withdrawn"
    closed = await client.post(
        f"{BASE}/{created['id']}/decide",
        json={"action": "approve"},
        headers=_headers(boss),
    )
    assert closed.status_code == 409


@pytest.mark.asyncio
async def test_same_day_changes_each_ring_the_bell_and_mail_again(
    client, team
) -> None:
    """Dopytaj → poprawka → zatwierdzenie tego samego dnia: każda zmiana daje
    nowy dzwonek (i mail), dzienny dedup ich nie połyka (audyt 22.10, F19)."""

    worker, boss = team["worker"], team["boss"]
    created = (
        await client.post(BASE, json=_trip("900"), headers=_headers(worker))
    ).json()
    returned = await client.post(
        f"{BASE}/{created['id']}/decide",
        json={"action": "return", "note": "Dopisz, ile nocy w hotelu."},
        headers=_headers(boss),
    )
    assert returned.status_code == 200, returned.text
    again = await client.put(
        f"{BASE}/{created['id']}",
        json={**_trip("950"), "purpose": "Warsztat, jedna noc w hotelu."},
        headers=_headers(worker),
    )
    assert again.status_code == 200, again.text
    decided = await client.post(
        f"{BASE}/{created['id']}/decide",
        json={"action": "approve"},
        headers=_headers(boss),
    )
    assert decided.status_code == 200, decided.text

    asked = sorted(
        await _notifications(boss, NotificationType.hr_approval_requested),
        key=lambda n: n.id,
    )
    assert len(asked) == 2
    # Dzisiejszy starszy wiersz jest odpięty od zgody — jego mail już nie wyjdzie,
    # a nowy (z nowym znacznikiem odpowiedzi) wskazuje zgodę.
    assert asked[0].related_entity_id is None
    assert asked[1].related_entity_id == created["id"]
    async with AsyncSessionLocal() as db:
        assert await approval_mail.render(db, asked[0], boss) is None
    titles = [
        n.title
        for n in await _notifications(worker, NotificationType.hr_approval_decided)
    ]
    assert any(t.startswith("Pytanie do Twojej zgody") for t in titles), titles
    assert any(t.startswith("Zgoda zatwierdzona") for t in titles), titles


@pytest.mark.asyncio
async def test_strangers_see_nothing_and_rules_are_admin_only(client, team) -> None:
    worker, stranger, ceo = team["worker"], team["stranger"], team["ceo"]
    created = (
        await client.post(BASE, json=_trip("300"), headers=_headers(worker))
    ).json()
    assert (
        await client.get(f"{BASE}/{created['id']}", headers=_headers(stranger))
    ).status_code == 404
    decide = await client.post(
        f"{BASE}/{created['id']}/decide",
        json={"action": "approve"},
        headers=_headers(stranger),
    )
    assert decide.status_code == 404

    refused = await client.put(
        f"{BASE}/rules",
        json={"supervisor_limits": {"trip": 99999}},
        headers=_headers(worker),
    )
    assert refused.status_code == 403
    saved = await client.put(
        f"{BASE}/rules",
        json={"final_approver_user_id": ceo.id, "supervisor_limits": {"gift": 300}},
        headers=_headers(ceo),
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["supervisor_limits"]["gift"] == 300
    assert saved.json()["effective_final_approver_names"] == [ceo.name]


@pytest.mark.asyncio
async def test_module_off_hides_the_routes_from_everyone_including_admin(
    client, team
) -> None:
    """Decyzja Artura 21.10.2026: wydatki i premie na razie idą mailem, więc
    wyłączone „Zgody” znikają także adminowi (bez podglądu jak w innych
    modułach). Wracają po włączeniu w Ustawienia → Kadry → Moduły."""
    await _put_setting(
        HR_MODULES_SETTING,
        {key: key != "approvals" for key in HR_MODULE_KEYS},
    )
    off = await client.get(BASE, headers=_headers(team["worker"]))
    assert off.status_code == 404
    admin = await client.get(BASE, headers=_headers(team["ceo"]))
    assert admin.status_code == 404
    config = await client.get("/api/hr/config", headers=_headers(team["ceo"]))
    assert config.status_code == 200, config.text
    assert config.json()["open_modules"]["approvals"] is False
    # Inne wyłączone moduły admin dalej widzi (przygotowanie importu).
    await _put_setting(HR_MODULES_SETTING, {key: False for key in HR_MODULE_KEYS})
    config = await client.get("/api/hr/config", headers=_headers(team["ceo"]))
    opened = config.json()["open_modules"]
    assert opened["approvals"] is False
    assert opened["leave"] is True

    await _put_setting(HR_MODULES_SETTING, {key: True for key in HR_MODULE_KEYS})
    admin = await client.get(BASE, headers=_headers(team["ceo"]))
    assert admin.status_code == 200


@pytest.mark.asyncio
async def test_preview_names_who_decides(client, team) -> None:
    worker, boss, ceo = team["worker"], team["boss"], team["ceo"]
    small = (
        await client.post(
            f"{BASE}/preview", json=_trip("500"), headers=_headers(worker)
        )
    ).json()
    assert small["supervisor_name"] == boss.name
    assert small["supervisor_decides_alone"] is True
    big = (
        await client.post(
            f"{BASE}/preview", json=_trip("5000"), headers=_headers(worker)
        )
    ).json()
    assert big["supervisor_decides_alone"] is False
    assert big["final_approver_names"] == [ceo.name]


@pytest.mark.asyncio
async def test_mail_to_the_decider_carries_amount_and_buttons(client, team) -> None:
    worker, boss, ceo = team["worker"], team["boss"], team["ceo"]
    created = (
        await client.post(BASE, json=_trip("980"), headers=_headers(worker))
    ).json()
    (notif,) = await _notifications(boss, NotificationType.hr_approval_requested)
    async with AsyncSessionLocal() as db:
        rendered = await approval_mail.render(db, notif, await db.get(User, boss.id))
        # Ktoś, kto o zgodzie nie decyduje, maila nie dostaje.
        nobody = await approval_mail.render(
            db, notif, await db.get(User, team["stranger"].id)
        )
    assert nobody is None
    subject, text_body, html_body = rendered
    assert "980 zł brutto" in subject
    assert "&decide=approve" in text_body and f"request={created['id']}" in text_body
    assert "Odrzuć albo dopytaj" in html_body

    await client.post(
        f"{BASE}/{created['id']}/decide",
        json={"action": "approve"},
        headers=_headers(boss),
    )
    async with AsyncSessionLocal() as db:
        # Zgoda już rozpatrzona — mail nie wychodzi.
        assert (
            await approval_mail.render(db, notif, await db.get(User, boss.id)) is None
        )
    assert ceo.id != boss.id
