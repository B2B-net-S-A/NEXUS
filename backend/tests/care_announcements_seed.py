"""Zasiew testów komunikatów do konsultantów (O12). Dane fikcyjne — repo jest publiczne.

Baza testowa nie jest czyszczona między testami, więc asercje dotyczą
wyłącznie kont, klientów i kontraktów założonych w danym teście (grupa
„klient” albo „wybrane osoby”), a grupa „wszyscy” — tylko tego, że NASI
konsultanci są w środku.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from typing import Optional

import pytest
import pytest_asyncio
from sqlalchemy import select, update

import app.models  # noqa: F401  (rejestracja wszystkich mapperów)
from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.core.security import create_access_token
from app.models.app_setting import AppSetting
from app.models.candidate import Candidate
from app.models.care_announcement import CareAnnouncement, CareAnnouncementRecipient
from app.models.client import Client, ClientStatus
from app.models.contract import Contract, ContractStatus, ContractType, RateUnit
from app.models.team_structure import DeliveryLeadClientAssignment
from app.models.user import User, UserRole
from app.services.care_announcements_schema import SETTING_KEY
from app.services.care.announcement_mail import MailOutcome
from app.services.hr_foundation_schema import (
    HR_DIVISIONS_SETTING,
    HR_MODULE_KEYS,
    HR_MODULES_SETTING,
)

BASE = "/api/care/announcements"


def tag() -> str:
    return uuid.uuid4().hex[:8]


def headers(user: User) -> dict[str, str]:
    token = create_access_token(subject=user.id, role=user.role.value)
    return {"Authorization": f"Bearer {token}"}


async def make_user(role: UserRole, *extra: UserRole, name: str = "Zofia") -> User:
    marker = tag()
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"komunikaty-{marker}@example.com",
            name=f"{name} Opiekuńska-{marker}",
            role=role,
            roles=[role.value, *(r.value for r in extra)],
            is_active=True,
            profile_completed=True,
        )
        db.add(user)
        await db.commit()
        return user


async def make_client(*, dl: Optional[User] = None) -> int:
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Bank Przykładowy {tag()}", status=ClientStatus.active)
        db.add(client)
        await db.flush()
        if dl is not None:
            db.add(
                DeliveryLeadClientAssignment(
                    delivery_lead_user_id=dl.id, client_id=client.id, is_head=True
                )
            )
        await db.commit()
        return client.id


async def make_consultant(
    client_id: int,
    *,
    first_name: str = "Anna",
    email: Optional[str] = "auto",
    contract_email: Optional[str] = None,
    contract_type: ContractType = ContractType.b2b,
    status: ContractStatus = ContractStatus.active,
    end_in_days: Optional[int] = None,
    owner_id: Optional[int] = None,
    started_days_ago: int = 100,
) -> tuple[int, int]:
    """(contract_id, candidate_id) — konsultant z aktywnym kontraktem."""

    marker = tag()
    today = business_today()
    async with AsyncSessionLocal() as db:
        candidate = Candidate(
            name=first_name,
            lastname=f"Przykładowa-{marker}",
            email=f"konsultant-{marker}@example.com" if email == "auto" else email,
        )
        db.add(candidate)
        await db.flush()
        contract = Contract(
            candidate_id=candidate.id,
            client_id=client_id,
            status=status,
            contract_type=contract_type,
            start_date=today - timedelta(days=started_days_ago),
            end_date=today + timedelta(days=end_in_days) if end_in_days else None,
            candidate_email=contract_email,
            rate_candidate=Decimal("100.000"),
            rate_client=Decimal("130.000"),
            rate_unit=RateUnit.hourly,
        )
        db.add(contract)
        await db.flush()
        if owner_id is not None:
            from sqlalchemy import text

            await db.execute(
                text("UPDATE contracts SET care_owner_user_id = :owner WHERE id = :id"),
                {"owner": owner_id, "id": contract.id},
            )
        await db.commit()
        return contract.id, candidate.id


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


async def _get_setting(key: str):
    async with AsyncSessionLocal() as db:
        return await db.scalar(select(AppSetting.value).where(AppSetting.key == key))


@pytest_asyncio.fixture
async def care_on():
    previous = await _get_setting(HR_MODULES_SETTING)
    await _set_setting(HR_MODULES_SETTING, {key: True for key in HR_MODULE_KEYS})
    yield
    await _set_setting(
        HR_MODULES_SETTING, previous or {key: False for key in HR_MODULE_KEYS}
    )


@pytest_asyncio.fixture
async def care_off():
    previous = await _get_setting(HR_MODULES_SETTING)
    await _set_setting(HR_MODULES_SETTING, {key: False for key in HR_MODULE_KEYS})
    yield
    await _set_setting(
        HR_MODULES_SETTING, previous or {key: False for key in HR_MODULE_KEYS}
    )


async def set_sending(enabled: Optional[bool]) -> None:
    await _set_setting(
        SETTING_KEY, None if enabled is None else {"sending_enabled": enabled}
    )


@pytest_asyncio.fixture
async def sending_on():
    previous = await _get_setting(SETTING_KEY)
    await set_sending(True)
    yield
    await _set_setting(SETTING_KEY, previous)


@pytest_asyncio.fixture
async def sending_default():
    """Brak wiersza w ``app_settings`` — stan po wdrożeniu."""

    previous = await _get_setting(SETTING_KEY)
    await set_sending(None)
    yield
    await _set_setting(SETTING_KEY, previous)


async def set_back_office_head(user_id: Optional[int]) -> None:
    current = await _get_setting(HR_DIVISIONS_SETTING) or {}
    await _set_setting(HR_DIVISIONS_SETTING, {**current, "back_office": user_id})


@pytest_asyncio.fixture
async def divisions_restored():
    """Przywraca ``app_settings['hr_divisions']`` po teście z ``make_head``."""

    previous = await _get_setting(HR_DIVISIONS_SETTING)
    yield
    await _set_setting(HR_DIVISIONS_SETTING, previous)


async def make_head() -> User:
    """Head back office z ``app_settings['hr_divisions']`` (bez roli opieki).

    Test używa go razem z ``divisions_restored``.
    """

    user = await make_user(UserRole.recruiter, name="Borys")
    await set_back_office_head(user.id)
    return user


@dataclass
class FakeMailer:
    """Fałszywy nadawca: zapisuje maile, nic nie wychodzi."""

    outcome: MailOutcome = field(default_factory=lambda: MailOutcome("accepted"))
    sent: list[dict] = field(default_factory=list)
    per_address: dict[str, MailOutcome] = field(default_factory=dict)

    async def send(self, *, to: str, subject: str, text: str) -> MailOutcome:
        self.sent.append({"to": to, "subject": subject, "text": text})
        return self.per_address.get(to, self.outcome)


def install_mailer(monkeypatch) -> FakeMailer:
    """Każda ścieżka bez wstrzykniętego nadawcy dostaje fałszywego."""

    from app.services.care import announcement_mail

    fake = FakeMailer()
    monkeypatch.setattr(announcement_mail, "default_mailer", lambda: fake)
    monkeypatch.setattr(
        announcement_mail, "sender_address", lambda: "administracja@example.com"
    )
    return fake


@pytest_asyncio.fixture
async def quiet_queue():
    """Komunikaty z kolejki po innych testach nie mieszają się z tym testem."""

    async with AsyncSessionLocal() as db:
        await db.execute(
            update(CareAnnouncementRecipient)
            .where(CareAnnouncementRecipient.status.in_(("pending", "sending")))
            .values(status="cancelled")
        )
        await db.execute(
            update(CareAnnouncement)
            .where(CareAnnouncement.status == "queued")
            .values(status="cancelled")
        )
        await db.commit()
    yield


@pytest.fixture(scope="module")
def announcement_routes():
    """Trasy są w ``main.py`` (za wyłącznikiem programu) — fixture zostaje jako
    znacznik zależności testów; montowanie drugi raz omijało wyłącznik."""

    yield


def draft_body(**overrides) -> dict:
    body = {
        "kind": "mandatory",
        "subject": "Od listopada faktury do 5. dnia miesiąca",
        "body": "Cześć {imię},\nprosimy o faktury do 5. dnia miesiąca.\n"
        "W razie pytań napisz do: {opiekun}.",
        "audience": {"group": "all"},
    }
    body.update(overrides)
    return body
