"""Opieka · „Ten tydzień” (D15, etap 2, 17.10.2026) — ``GET /api/care/week``.

Zakres: punkt planu zaległy i w tym tygodniu w jednej kolejce, follow-up
z ostatniej rozmowy, kontrakt bez kontaktu w tym tygodniu poza listą, cudzy
klient Delivery Leada niewidoczny, prośba o opinię jedna na menedżera ze
wszystkimi jego konsultantami i menedżer z drzewa przy rozmowie, Finanse bez
próśb o opinię (D11), 403 dla roli bez sekcji Delivery. Reguła powodów i granice
tygodnia jako czyste funkcje.

Dane fikcyjne (repo jest publiczne).
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import func, select

import app.models  # noqa: F401  (rejestracja wszystkich mapperów)
from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.contract_care import CareConversation, CarePlanItem
from app.models.user import UserRole
from app.services.care import access as care_access
from app.services.care import plan as care_plan
from app.services.care.week import contact_reasons, default_day, week_bounds
from app.services.hr_foundation_schema import HR_MODULE_KEYS
from tests.test_care_api import (
    _previous_modules,
    headers,
    make_client,
    make_contract,
    make_user,
    set_modules,
)
from tests.test_care_client_people import make_area, make_consultant, make_contact

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def care_on():
    previous = await _previous_modules()
    await set_modules({key: True for key in HR_MODULE_KEYS})
    yield
    await set_modules(previous or {key: False for key in HR_MODULE_KEYS})


def _week() -> tuple[date, date, date]:
    today = business_today()
    monday, friday = week_bounds(default_day(today))
    return today, monday, friday


async def nightly_plan(*contract_ids: int) -> None:
    """Plan dopisuje dzienny przebieg (``reminders.run_once``) — tu zbiorczo."""

    async with AsyncSessionLocal() as db:
        contracts = await care_access.contracts_by_id(db, contract_ids)
        await care_plan.ensure_plans(
            db, list(contracts.values()), today=business_today()
        )
        await db.commit()


async def plan_rows(contract_id: int) -> int:
    async with AsyncSessionLocal() as db:
        return int(
            await db.scalar(
                select(func.count())
                .select_from(CarePlanItem)
                .where(CarePlanItem.contract_id == contract_id)
            )
        )


async def add_conversation(
    contract_id: int, occurred_on: date, follow_up_on: date | None
) -> None:
    async with AsyncSessionLocal() as db:
        db.add(
            CareConversation(
                contract_id=contract_id,
                occurred_on=occurred_on,
                channel="phone",
                note="Rozmowa testowa — umówiony kolejny kontakt.",
                follow_up_on=follow_up_on,
            )
        )
        await db.commit()


# ── Reguły bez bazy ─────────────────────────────────────────────────────────


async def test_week_bounds_and_weekend_shows_next_week() -> None:
    assert week_bounds(date(2026, 10, 15)) == (date(2026, 10, 12), date(2026, 10, 16))
    assert default_day(date(2026, 10, 15)) == date(2026, 10, 15)
    # Sobota i niedziela: „Ten tydzień” to tydzień, który się zaczyna.
    assert default_day(date(2026, 10, 17)) == date(2026, 10, 19)
    assert default_day(date(2026, 10, 18)) == date(2026, 10, 19)


def _item(item_id: int, kind: str, due_on: date) -> CarePlanItem:
    return CarePlanItem(
        id=item_id, contract_id=1, kind=kind, seq=0, due_on=due_on, status="open"
    )


async def test_reasons_overdue_this_week_and_follow_up() -> None:
    today = date(2026, 10, 14)  # środa
    friday = date(2026, 10, 16)
    items = [
        _item(1, "day_30", today - timedelta(days=4)),
        _item(2, "quarterly", friday),
        _item(3, "day_90", friday + timedelta(days=3)),
    ]
    latest = CareConversation(
        contract_id=1, occurred_on=today - timedelta(days=13), follow_up_on=today
    )
    reasons = contact_reasons(items, latest, today=today, friday=friday)
    assert [(r.kind, r.due_on) for r in reasons] == [
        ("day_30", today - timedelta(days=4)),
        ("follow_up", today),
        ("quarterly", friday),
    ]
    assert reasons[0].payload(today)["overdue"] is True
    assert reasons[1].payload(today)["label"] == "Umówiony kontakt"
    # Follow-up sprzed okna (rozmowy z importu) nie wraca, przyszły tydzień też nie.
    stale = CareConversation(
        contract_id=1,
        occurred_on=today - timedelta(days=400),
        follow_up_on=today - timedelta(days=31),
    )
    later = CareConversation(
        contract_id=1, occurred_on=today, follow_up_on=friday + timedelta(days=1)
    )
    assert contact_reasons([], stale, today=today, friday=friday) == []
    assert contact_reasons([], later, today=today, friday=friday) == []


# ── API ─────────────────────────────────────────────────────────────────────


async def test_week_queue_overdue_this_week_follow_up_and_scope(
    app_client, care_on
) -> None:
    today, monday, friday = _week()
    dl = await make_user(UserRole.delivery_lead)
    client_id = await make_client(dl=dl)
    # Klient innego Delivery Leada — poza portfelem czytającego.
    foreign_client = await make_client(dl=await make_user(UserRole.delivery_lead))
    # Zaległy „Dzień 30” (start 40 dni temu: dzień 7 jest sprzed okna planu).
    overdue, _ = await make_contract(client_id, started_days_ago=40)
    # „Dzień 7” wypada w piątek tego tygodnia.
    this_week, _ = await make_contract(
        client_id, started_days_ago=(today - (friday - timedelta(days=7))).days
    )
    # Start dziś: najbliższy punkt planu za 7 dni — poza tym tygodniem.
    quiet, _ = await make_contract(client_id, started_days_ago=0)
    follow_up, _ = await make_contract(client_id, started_days_ago=0)
    await add_conversation(follow_up, today, friday)
    foreign, _ = await make_contract(foreign_client, started_days_ago=40)
    await nightly_plan(overdue, this_week, quiet, follow_up, foreign)

    response = await app_client.get(
        "/api/care/week", params={"scope": "mine"}, headers=headers(dl)
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["week"]["from"] == monday.isoformat()
    assert body["week"]["to"] == friday.isoformat()
    assert body["week"]["is_current"] is True
    rows = {row["contract_id"]: row for row in body["contacts"]}
    assert set(rows) == {overdue, this_week, follow_up}
    assert quiet not in rows and foreign not in rows

    late = rows[overdue]
    assert [r["kind"] for r in late["reasons"]] == ["day_30"]
    assert late["overdue"] is True and late["overdue_days"] == 10
    assert late["owner"]["id"] == dl.id
    assert late["plan_item_id"] is not None
    assert rows[this_week]["reasons"][0]["kind"] == "day_7"
    assert rows[this_week]["due_on"] == friday.isoformat()
    assert rows[this_week]["overdue"] is False
    assert [r["kind"] for r in rows[follow_up]["reasons"]] == ["follow_up"]
    assert rows[follow_up]["last_conversation"]["note_excerpt"].startswith(
        "Rozmowa testowa"
    )
    # Kolejność: zaległe najpierw.
    assert body["contacts"][0]["contract_id"] == overdue
    assert body["counts"]["contacts"] == 3
    assert body["counts"]["overdue"] == 1
    assert body["can_edit"] is True

    # „Wszyscy w moim zakresie” u Delivery Leada = jego portfel, bez cudzego klienta.
    everyone = await app_client.get(
        "/api/care/week", params={"scope": "all"}, headers=headers(dl)
    )
    assert everyone.status_code == 200, everyone.text
    ids = {row["contract_id"] for row in everyone.json()["contacts"]}
    assert {overdue, this_week, follow_up} <= ids
    assert foreign not in ids

    # Następny tydzień: zaległy dalej jest, „Dzień 7” z tego piątku też (zaległy
    # dopiero wtedy, ale termin ≤ piątek następnego tygodnia).
    later = await app_client.get(
        "/api/care/week",
        params={"scope": "mine", "from": (monday + timedelta(days=7)).isoformat()},
        headers=headers(dl),
    )
    assert later.status_code == 200, later.text
    assert later.json()["week"]["is_current"] is False
    assert {row["contract_id"] for row in later.json()["contacts"]} >= {
        overdue,
        this_week,
    }


async def test_feedback_request_one_per_manager_and_manager_at_contact(
    app_client, care_on
) -> None:
    dl = await make_user(UserRole.delivery_lead)
    client_id = await make_client(dl=dl)
    area = await make_area(client_id, "Płatności")
    manager = await make_contact(
        client_id, "Katarzyna Przykładowa", position="Head of QA", area_id=area
    )
    first = await make_consultant(
        client_id, manager_id=manager, order_end_in_days=20, first_name="Adam"
    )
    second = await make_consultant(
        client_id, manager_id=manager, order_end_in_days=25, first_name="Ewa"
    )
    await nightly_plan(first, second)

    response = await app_client.get("/api/care/week", headers=headers(dl))
    assert response.status_code == 200, response.text
    body = response.json()
    mine = [item for item in body["feedback"] if item["client_id"] == client_id]
    assert len(mine) == 1
    request = mine[0]
    assert request["contact_id"] == manager
    assert request["reasons"] == ["pre_end"]
    assert request["overdue"] is True
    assert request["area"] == {"id": area, "name": "Płatności"}
    assert [c["contract_id"] for c in request["consultants"]] == [first, second]
    assert "owner_ids" not in request
    assert body["feedback_visible"] is True

    # Ci sami konsultanci w kolejce rozmów — z menedżerem z drzewa.
    rows = {row["contract_id"]: row for row in body["contacts"]}
    assert rows[first]["manager"] == {
        "id": manager,
        "name": "Katarzyna Przykładowa",
        "position": "Head of QA",
        "area": {"id": area, "name": "Płatności"},
    }
    # Koniec za 20 dni → można przekazać do front office.
    assert rows[first]["front_office"]["reasons"] == ["project_end"]
    assert rows[first]["front_office"]["handed_off_on"] is None


async def test_finance_reads_week_without_feedback(app_client, care_on) -> None:
    finance = await make_user(UserRole.finance)
    client_id = await make_client()
    manager = await make_contact(client_id, "Piotr Wzorcowy")
    await make_consultant(client_id, manager_id=manager, order_end_in_days=10)

    response = await app_client.get(
        "/api/care/week", params={"scope": "all"}, headers=headers(finance)
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["feedback"] == [] and body["feedback_visible"] is False
    assert body["can_edit"] is False


async def test_week_refused_without_delivery_section(app_client, care_on) -> None:
    recruiter = await make_user(UserRole.recruiter)
    response = await app_client.get("/api/care/week", headers=headers(recruiter))
    assert response.status_code == 403
    bad = await app_client.get(
        "/api/care/week",
        params={"from": "jutro"},
        headers=headers(await make_user(UserRole.admin)),
    )
    assert bad.status_code == 422


async def test_week_and_list_reads_do_not_write_the_plan(app_client, care_on) -> None:
    """Audyt wydajności 17.10: odczyt list opieki nie dopisuje planu (2·C zapisów)."""

    dl = await make_user(UserRole.delivery_lead)
    tcm = await make_user(UserRole.talent_community_manager)
    client_id = await make_client(dl=dl)
    contract_id, _ = await make_contract(client_id, started_days_ago=40)

    for url in ("/api/care/week", "/api/care/my-consultants"):
        response = await app_client.get(url, headers=headers(dl))
        assert response.status_code == 200, response.text
    assert await plan_rows(contract_id) == 0

    # Zmiana opiekuna klienta dopisuje plan od razu (zbiorczo), bez nocy.
    changed = await app_client.put(
        f"/api/care/clients/{client_id}/default-owner",
        headers=headers(tcm),
        json={"user_id": tcm.id},
    )
    assert changed.status_code == 200, changed.text
    assert await plan_rows(contract_id) > 0
    week = await app_client.get("/api/care/week", headers=headers(tcm))
    assert contract_id in {row["contract_id"] for row in week.json()["contacts"]}


async def test_week_counts_contracts_and_owners_once(
    app_client, care_on, monkeypatch
) -> None:
    """Prośby o opinię biorą kontrakty i opiekunów policzonych dla kolejki."""

    dl = await make_user(UserRole.delivery_lead)
    client_id = await make_client(dl=dl)
    manager = await make_contact(client_id, "Joanna Przykładowa")
    await make_consultant(client_id, manager_id=manager, order_end_in_days=15)
    calls = {"live": 0, "owners": 0}
    live, owners = care_access.live_contracts, care_access.effective_owners

    async def counted_live(*args, **kwargs):
        calls["live"] += 1
        return await live(*args, **kwargs)

    async def counted_owners(*args, **kwargs):
        calls["owners"] += 1
        return await owners(*args, **kwargs)

    monkeypatch.setattr(care_access, "live_contracts", counted_live)
    monkeypatch.setattr(care_access, "effective_owners", counted_owners)

    response = await app_client.get("/api/care/week", headers=headers(dl))
    assert response.status_code == 200, response.text
    assert [i["contact_id"] for i in response.json()["feedback"]] == [manager]
    assert calls == {"live": 1, "owners": 1}
