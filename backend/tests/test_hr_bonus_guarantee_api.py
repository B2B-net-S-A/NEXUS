"""Gwarancja premii DL (05.11.2026): dług, potrącenie, zamknięcie, API.

Konsultant, który nie przepracuje 12 miesięcy od startu kontraktu, odbiera
DL-owi całą premię za placement. Dług zakłada hak końca kontraktu albo Płace
ręcznie; potrąca się sam z kolejnych premii (najwyżej do ich sumy), a
zamknięcie miesiąca zamraża potrącenie. Reguły bez bazy:
``test_hr_bonus_guarantee_rules.py``. Dane fikcyjne (repo jest publiczne).
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

import app.models  # noqa: F401  (rejestracja wszystkich mapperów)
from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today, local_now
from app.core.security import create_access_token
from app.models.app_setting import AppSetting
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus, RateUnit
from app.models.hr_payroll import (
    HrBonus,
    HrBonusClawback,
    HrBonusClawbackOffset,
    PayrollLine,
    PayrollPeriod,
)
from app.models.hr_profile import EmployeeProfile
from app.models.section_permission import UserActionOverride
from app.models.user import User, UserRole
from app.services.hr import bonus_guarantee, placement_bonuses
from app.services.hr.payroll_periods import add_months
from app.services.hr_foundation_schema import HR_MODULE_KEYS, HR_MODULES_SETTING
from tests.hr_settlements_seed import delete_settlement_rows


def _headers(user: User) -> dict[str, str]:
    token = create_access_token(subject=user.id, role=user.role.value)
    return {"Authorization": f"Bearer {token}"}


async def _set_setting(key: str, value) -> None:
    async with AsyncSessionLocal() as db:
        row = await db.get(AppSetting, key)
        if value is None:
            if row is not None:
                await db.delete(row)
        elif row is None:
            db.add(AppSetting(key=key, value=value))
        else:
            row.value = value
        await db.commit()


async def _wipe() -> None:
    async with AsyncSessionLocal() as db:
        await delete_settlement_rows(db)
        await db.execute(delete(HrBonusClawback))
        await db.execute(delete(PayrollLine))
        await db.execute(delete(PayrollPeriod))
        await db.execute(delete(HrBonus))
        await db.commit()


@pytest_asyncio.fixture
async def payroll_on():
    async with AsyncSessionLocal() as db:
        previous = await db.scalar(
            select(AppSetting.value).where(AppSetting.key == HR_MODULES_SETTING)
        )
    await _set_setting(HR_MODULES_SETTING, {key: True for key in HR_MODULE_KEYS})
    await _wipe()
    yield
    await _wipe()
    await _set_setting(
        HR_MODULES_SETTING, previous or {key: False for key in HR_MODULE_KEYS}
    )


async def _user(db, role: str, *, payroll: bool = False) -> User:
    marker = uuid.uuid4().hex[:10]
    user = User(
        email=f"guarantee-{marker}@example.com",
        name=f"Osoba Przykładowa {marker}",
        role=UserRole(role),
        roles=[role],
        is_active=True,
    )
    db.add(user)
    await db.flush()
    db.add(EmployeeProfile(user_id=user.id, employment_type="b2b"))
    if payroll:
        db.add(UserActionOverride(user_id=user.id, action="payroll", access="manage"))
    await db.flush()
    return user


async def _team() -> tuple[User, User, User]:
    """Płace, Delivery Lead i administrator (ponowne otwarcie miesiąca)."""

    async with AsyncSessionLocal() as db:
        payroll = await _user(db, "recruiter", payroll=True)
        dl = await _user(db, "delivery_lead")
        admin = await _user(db, "admin")
        await db.commit()
    return payroll, dl, admin


async def _contract(*, started_days_ago: int, ended_days_ago=None) -> int:
    tag = uuid.uuid4().hex[:8]
    today = business_today()
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Firma Przykładowa {tag}")
        candidate = Candidate(
            name="Jan", lastname=f"Przykładowy-{tag}", email=f"cand-{tag}@example.com"
        )
        db.add_all([client, candidate])
        await db.flush()
        contract = Contract(
            candidate_id=candidate.id,
            client_id=client.id,
            status=ContractStatus.active
            if ended_days_ago is None
            else ContractStatus.ended,
            start_date=today - timedelta(days=started_days_ago),
            end_date=None
            if ended_days_ago is None
            else today - timedelta(days=ended_days_ago),
            rate_client=Decimal("150"),
            rate_candidate=Decimal("104"),
            rate_unit=RateUnit.hourly,
            currency="PLN",
            rate_client_currency="PLN",
            rate_candidate_currency="PLN",
        )
        db.add(contract)
        await db.commit()
        return contract.id


async def _bonus(
    recipient: User,
    amount: str,
    months_ago: int,
    *,
    contract_id=None,
    category: str = "delivery_lead",
    assigned_by: User,
) -> int:
    today = business_today()
    year, month = add_months(today.year, today.month, -months_ago)
    async with AsyncSessionLocal() as db:
        bonus = HrBonus(
            recipient_user_id=recipient.id,
            amount=Decimal(amount),
            currency="PLN",
            category=category,
            period_year=year,
            period_month=month,
            status="assigned",
            source="manual",
            contract_id=contract_id,
            description="Premia DL — placement: Jan P. (Firma Przykładowa)",
            assigned_by=assigned_by.id,
            assigned_at=local_now(),
        )
        db.add(bonus)
        await db.commit()
        return bonus.id


def _month(months_ago: int) -> tuple[int, int]:
    today = business_today()
    return add_months(today.year, today.month, -months_ago)


async def _hook(contract_id: int, event: str) -> dict:
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        if event == "ended":
            result = await placement_bonuses.on_contract_ended(db, contract)
        else:
            result = await placement_bonuses.on_contract_end_undone(db, contract)
        await db.commit()
        return result


async def _clawbacks(bonus_id: int) -> list[HrBonusClawback]:
    async with AsyncSessionLocal() as db:
        return list(
            await db.scalars(
                select(HrBonusClawback)
                .where(HrBonusClawback.bonus_id == bonus_id)
                .order_by(HrBonusClawback.id)
            )
        )


async def _line(app_client, payroll: User, user: User, months_ago: int) -> dict:
    year, month = _month(months_ago)
    response = await app_client.get(
        f"/api/hr/payroll/months/{year}/{month}", headers=_headers(payroll)
    )
    assert response.status_code == 200, response.text
    person = next(p for p in response.json()["people"] if p["user_id"] == user.id)
    (line,) = person["lines"]
    return line


async def _close(app_client, payroll: User, months_ago: int) -> None:
    year, month = _month(months_ago)
    closed = await app_client.post(
        f"/api/hr/payroll/months/{year}/{month}/close",
        json={"acknowledge_warnings": True},
        headers=_headers(payroll),
    )
    assert closed.status_code == 200, closed.text


@pytest.mark.asyncio
async def test_debt_bigger_than_next_bonus_carries_over_and_freezes_on_close(
    app_client, payroll_on
) -> None:
    payroll, dl, admin = await _team()
    contract_id = await _contract(started_days_ago=120, ended_days_ago=10)
    paid = await _bonus(dl, "1512.00", 4, contract_id=contract_id, assigned_by=payroll)
    await _close(app_client, payroll, 4)

    result = await _hook(contract_id, "ended")
    assert result["guarantee_created"] == 1
    (debt,) = await _clawbacks(paid)
    assert (debt.origin, debt.status, debt.amount) == (
        "automatic",
        "open",
        Decimal("1512.00"),
    )
    assert debt.guarantee_until == debt.contract_start.replace(
        year=debt.contract_start.year + 1
    ) - timedelta(days=1)

    await _bonus(dl, "1000.00", 3, assigned_by=payroll)
    await _bonus(dl, "800.00", 2, assigned_by=payroll)
    first = await _line(app_client, payroll, dl, 3)
    assert (first["bonus_total"], first["clawback_total"]) == ("0.00", "1000.00")
    # Wcześniejszy otwarty miesiąc zjada swoją część — tu zostaje reszta 512.
    second = await _line(app_client, payroll, dl, 2)
    assert (second["bonus_total"], second["clawback_total"]) == ("288.00", "512.00")

    await _close(app_client, payroll, 3)
    async with AsyncSessionLocal() as db:
        frozen = await db.scalar(
            select(PayrollLine.clawback_total)
            .where(PayrollLine.user_id == dl.id)
            .join(PayrollPeriod, PayrollPeriod.id == PayrollLine.period_id)
            .where(PayrollPeriod.month == _month(3)[1])
        )
        offsets = list(await db.scalars(select(HrBonusClawbackOffset.amount)))
    assert frozen == Decimal("1000.00") and offsets == [Decimal("1000.00")]
    again = await _line(app_client, payroll, dl, 2)
    assert again["clawback_total"] == "512.00"

    await _close(app_client, payroll, 2)
    (debt,) = await _clawbacks(paid)
    assert debt.status == "settled"

    # Ponowne otwarcie zdejmuje potrącenie miesiąca — dług znów otwarty.
    year, month = _month(2)
    reopened = await app_client.post(
        f"/api/hr/payroll/months/{year}/{month}/reopen",
        json={"reason": "Korekta potrącenia"},
        headers=_headers(admin),
    )
    assert reopened.status_code == 200, reopened.text
    (debt,) = await _clawbacks(paid)
    assert debt.status == "open"
    listed = await app_client.get(
        "/api/hr/payroll/clawbacks", headers=_headers(payroll)
    )
    item = next(i for i in listed.json()["items"] if i["id"] == debt.id)
    assert (item["settled"], item["remaining"]) == ("1000.00", "512.00")

    # Osoba widzi dług w „Moim czasie” i potrącenie w szacunku miesiąca.
    me = await app_client.get("/api/hr/payroll/me", headers=_headers(dl))
    assert [c["remaining"] for c in me.json()["clawbacks"]] == ["512.00"]
    settlement = await app_client.get(
        f"/api/hr/payroll/me/settlement?year={year}", headers=_headers(dl)
    )
    estimate = next(m for m in settlement.json()["months"] if m["month"] == month)
    assert estimate["lines"][0]["clawback_total"] == "512.00"


@pytest.mark.asyncio
async def test_several_debts_go_oldest_first(app_client, payroll_on) -> None:
    payroll, dl, _admin = await _team()
    older = await _contract(started_days_ago=200, ended_days_ago=30)
    newer = await _contract(started_days_ago=150, ended_days_ago=20)
    first = await _bonus(dl, "300.00", 5, contract_id=older, assigned_by=payroll)
    second = await _bonus(dl, "500.00", 4, contract_id=newer, assigned_by=payroll)
    await _close(app_client, payroll, 5)
    await _close(app_client, payroll, 4)
    await _hook(older, "ended")
    await _hook(newer, "ended")
    await _bonus(dl, "600.00", 3, assigned_by=payroll)

    line = await _line(app_client, payroll, dl, 3)
    assert (line["bonus_total"], line["clawback_total"]) == ("0.00", "600.00")
    await _close(app_client, payroll, 3)
    (one,) = await _clawbacks(first)
    (two,) = await _clawbacks(second)
    assert one.status == "settled" and two.status == "open"
    listed = await app_client.get(
        "/api/hr/payroll/clawbacks", headers=_headers(payroll)
    )
    remaining = {i["id"]: i["remaining"] for i in listed.json()["items"]}
    assert remaining == {one.id: "0.00", two.id: "200.00"}


@pytest.mark.asyncio
async def test_undoing_contract_end_cancels_automatic_debt_but_not_manual_decision(
    app_client, payroll_on
) -> None:
    payroll, dl, _admin = await _team()
    contract_id = await _contract(started_days_ago=90, ended_days_ago=5)
    bonus = await _bonus(dl, "700.00", 2, contract_id=contract_id, assigned_by=payroll)
    await _hook(contract_id, "ended")

    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        contract.status, contract.end_date = ContractStatus.active, None
        await db.commit()
    result = await _hook(contract_id, "end_undone")
    assert result["guarantee_cancelled"] == 1
    (cancelled,) = await _clawbacks(bonus)
    assert (cancelled.status, cancelled.cancel_reason) == (
        "cancelled",
        "contract_restored",
    )
    line = await _line(app_client, payroll, dl, 2)
    assert line["clawback_total"] == "0.00"

    # Kontrakt znów zakończony: automat zakłada nowy dług.
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        contract.status = ContractStatus.ended
        contract.end_date = business_today() - timedelta(days=1)
        await db.commit()
    await _hook(contract_id, "ended")
    live = [c for c in await _clawbacks(bonus) if c.status == "open"]
    assert len(live) == 1

    # Płace zdejmują dług — automat go nie wskrzesza.
    refused = await app_client.post(
        f"/api/hr/payroll/clawbacks/{live[0].id}/cancel",
        json={"note": "ok"},
        headers=_headers(payroll),
    )
    assert refused.status_code == 422
    dropped = await app_client.post(
        f"/api/hr/payroll/clawbacks/{live[0].id}/cancel",
        json={"note": "Zastępstwo dał ten sam DL"},
        headers=_headers(payroll),
    )
    assert dropped.status_code == 200, dropped.text
    await _hook(contract_id, "ended")
    assert not [c for c in await _clawbacks(bonus) if c.status != "cancelled"]


@pytest.mark.asyncio
async def test_payroll_registers_manual_clawback_while_contract_still_active(
    app_client, payroll_on
) -> None:
    payroll, dl, _admin = await _team()
    contract_id = await _contract(started_days_ago=3)
    bonus = await _bonus(dl, "1512.00", 1, contract_id=contract_id, assigned_by=payroll)
    recruiter_bonus = await _bonus(
        dl,
        "500.00",
        1,
        contract_id=contract_id,
        category="recruiter",
        assigned_by=payroll,
    )
    own = await _bonus(payroll, "100.00", 1, assigned_by=dl)

    url = f"/api/hr/payroll/bonuses/{bonus}/clawback"
    note = {"note": "Konsultant odszedł zaraz po starcie"}
    assert (
        await app_client.post(url, json=note, headers=_headers(dl))
    ).status_code == 403
    assert (
        await app_client.post(url, json={"note": ""}, headers=_headers(payroll))
    ).status_code == 422
    created = await app_client.post(url, json=note, headers=_headers(payroll))
    assert created.status_code == 201, created.text
    body = created.json()
    assert (body["origin"], body["amount"], body["remaining"]) == (
        "manual",
        "1512.00",
        "1512.00",
    )
    assert body["ended_on"] is None
    again = await app_client.post(url, json=note, headers=_headers(payroll))
    assert again.status_code == 409
    other_role = await app_client.post(
        f"/api/hr/payroll/bonuses/{recruiter_bonus}/clawback",
        json=note,
        headers=_headers(payroll),
    )
    assert other_role.status_code == 409
    mine = await app_client.post(
        f"/api/hr/payroll/bonuses/{own}/clawback", json=note, headers=_headers(payroll)
    )
    assert mine.status_code == 403

    listed = await app_client.get(
        f"/api/hr/payroll/bonuses?user_id={dl.id}", headers=_headers(payroll)
    )
    rows = {item["id"]: item for item in listed.json()["items"]}
    assert rows[bonus]["has_clawback"] and not rows[bonus]["can_clawback"]
    assert not rows[recruiter_bonus]["can_clawback"]
    assert (
        await app_client.get("/api/hr/payroll/clawbacks", headers=_headers(dl))
    ).status_code == 403

    # Dług ręczny przeżywa nocny przebieg mimo trwającego kontraktu.
    async with AsyncSessionLocal() as db:
        await bonus_guarantee.sync_guarantees(db, today=business_today())
        await db.commit()
    (debt,) = await _clawbacks(bonus)
    assert debt.status == "open"


@pytest.mark.asyncio
async def test_cancelling_unpaid_bonus_drops_its_debt(app_client, payroll_on) -> None:
    payroll, dl, _admin = await _team()
    contract_id = await _contract(started_days_ago=60, ended_days_ago=2)
    bonus = await _bonus(dl, "900.00", 1, contract_id=contract_id, assigned_by=payroll)
    await _hook(contract_id, "ended")
    # Premia z otwartego miesiąca i jej dług: na wypłacie zero.
    line = await _line(app_client, payroll, dl, 1)
    assert (line["bonus_total"], line["clawback_total"]) == ("0.00", "900.00")

    cancelled = await app_client.post(
        f"/api/hr/payroll/bonuses/{bonus}/cancel",
        json={"note": "Kontrakt zakończony"},
        headers=_headers(payroll),
    )
    assert cancelled.status_code == 200, cancelled.text
    (debt,) = await _clawbacks(bonus)
    assert (debt.status, debt.cancel_reason) == ("cancelled", "bonus_cancelled")
