"""Panel konsultanta: wejście tylko po aktywacji przez człowieka, bez kodu SMS.

Dane fikcyjne. Testy pilnują też ścieżek odmowy: kontrakt bez aktywacji wygląda z zewnątrz
tak samo jak nieznany adres, a wyłączenie panelu zamyka sesję od razu.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.consultant_panel import CpActivation
from app.models.contract import Contract, ContractStatus
from app.models.user import UserRole
from app.services.consultant_portal import activation
from app.services.consultant_portal.auth import PortalError
from app.services.hr_foundation_schema import HR_MODULE_KEYS, HR_MODULES_SETTING
from tests.care_announcements_seed import _set_setting, make_user, tag
from tests.consultant_portal_seed import (  # noqa: F401  (fixture'y)
    BASE,
    install_mailer,
    make_person,
    portal_all,
    portal_restored,
    session_headers,
    set_portal,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _modules_off() -> None:
    await _set_setting(HR_MODULES_SETTING, {key: False for key in HR_MODULE_KEYS})


@pytest.mark.usefixtures("portal_all")
async def test_contract_without_activation_gets_the_same_answer_as_a_stranger(
    app_client, monkeypatch
) -> None:
    mailer = install_mailer(monkeypatch)
    person = await make_person(activated=False)
    known = await app_client.post(f"{BASE}/link", json={"email": person.email})
    unknown = await app_client.post(f"{BASE}/link", json={"email": "nikt@example.com"})
    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()
    assert mailer.sent == []


@pytest.mark.usefixtures("portal_restored")
async def test_pilot_works_without_back_office_module(app_client) -> None:
    person = await make_person()
    await set_portal("pilot")
    await _modules_off()
    headers = await session_headers(app_client, person)
    assert (await app_client.get(f"{BASE}/me", headers=headers)).status_code == 200


@pytest.mark.usefixtures("portal_restored")
async def test_all_stays_closed_without_back_office_module(app_client) -> None:
    await set_portal("all")
    await _modules_off()
    assert (await app_client.get(f"{BASE}/status")).status_code == 404


@pytest.mark.usefixtures("portal_restored")
async def test_finance_opens_with_a_plain_session(app_client) -> None:
    person = await make_person()
    await set_portal("pilot")
    headers = await session_headers(app_client, person)
    assert (
        await app_client.get(f"{BASE}/finance/overview", headers=headers)
    ).status_code == 200
    assert (
        await app_client.post(f"{BASE}/finance/sms", headers=headers)
    ).status_code == 404


@pytest.mark.usefixtures("portal_restored")
async def test_deactivation_closes_the_session_at_once(app_client) -> None:
    person = await make_person()
    await set_portal("pilot")
    admin = await make_user(UserRole.admin)
    headers = await session_headers(app_client, person)
    async with AsyncSessionLocal() as db:
        await activation.deactivate(db, person.contract_id, actor=admin, now=_now())
        await db.commit()
    assert (await app_client.get(f"{BASE}/me", headers=headers)).status_code == 401


async def test_activation_confirms_the_address_on_the_contract() -> None:
    person = await make_person(activated=False)
    admin = await make_user(UserRole.admin)
    suffix = tag()
    async with AsyncSessionLocal() as db:
        await activation.activate(
            db,
            person.contract_id,
            email=f" Nowy.{suffix}@Example.com ",
            actor=admin,
            now=_now(),
        )
        await db.commit()
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, person.contract_id)
        row = await db.scalar(
            select(CpActivation).where(CpActivation.contract_id == person.contract_id)
        )
    assert contract.candidate_email == f"nowy.{suffix}@example.com"
    assert row.activated_by == admin.id
    assert row.deactivated_at is None


async def test_address_of_another_active_person_is_refused() -> None:
    taken = await make_person()
    person = await make_person(activated=False)
    admin = await make_user(UserRole.admin)
    async with AsyncSessionLocal() as db:
        with pytest.raises(PortalError) as refused:
            await activation.activate(
                db, person.contract_id, email=taken.email, actor=admin, now=_now()
            )
    assert refused.value.code == "email_taken"


async def test_ended_contract_cannot_be_activated() -> None:
    person = await make_person(activated=False, status=ContractStatus.ended)
    admin = await make_user(UserRole.admin)
    async with AsyncSessionLocal() as db:
        with pytest.raises(PortalError) as refused:
            await activation.activate(
                db, person.contract_id, email=person.email, actor=admin, now=_now()
            )
    assert refused.value.code == "contract_not_live"


async def test_reactivation_opens_the_same_row() -> None:
    person = await make_person()
    admin = await make_user(UserRole.admin)
    async with AsyncSessionLocal() as db:
        await activation.deactivate(db, person.contract_id, actor=admin, now=_now())
        await db.commit()
    async with AsyncSessionLocal() as db:
        with pytest.raises(PortalError):
            await activation.deactivate(db, person.contract_id, actor=admin, now=_now())
    async with AsyncSessionLocal() as db:
        await activation.activate(
            db, person.contract_id, email=person.email, actor=admin, now=_now()
        )
        await db.commit()
        rows = (
            await db.scalars(
                select(CpActivation).where(
                    CpActivation.contract_id == person.contract_id
                )
            )
        ).all()
    assert len(rows) == 1
    assert rows[0].deactivated_at is None


@pytest.mark.usefixtures("portal_restored")
async def test_address_changed_after_activation_closes_the_panel(
    app_client, monkeypatch
) -> None:
    mailer = install_mailer(monkeypatch)
    person = await make_person()
    await set_portal("pilot")
    headers = await session_headers(app_client, person)
    changed = f"zmieniony-{tag()}@example.com"
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, person.contract_id)
        contract.candidate_email = changed
        await db.commit()
    assert (await app_client.get(f"{BASE}/me", headers=headers)).status_code == 401
    await app_client.post(f"{BASE}/link", json={"email": changed})
    assert mailer.sent == []
    async with AsyncSessionLocal() as db:
        state = await activation.state_for(db, person.contract_id)
    assert state.active is True
    assert state.address_changed is True


@pytest.mark.usefixtures("portal_restored")
async def test_copied_address_on_another_contract_does_not_block_the_owner(
    app_client, monkeypatch
) -> None:
    mailer = install_mailer(monkeypatch)
    owner = await make_person()
    other = await make_person()
    await set_portal("pilot")
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, other.contract_id)
        contract.candidate_email = owner.email
        await db.commit()
    await app_client.post(f"{BASE}/link", json={"email": owner.email})
    assert [mail["to"] for mail in mailer.sent] == [owner.email]
