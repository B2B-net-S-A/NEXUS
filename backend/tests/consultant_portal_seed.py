"""Zasiew testów portalu konsultanta. Dane fikcyjne — repo jest publiczne."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

import pytest_asyncio
from sqlalchemy import delete, update

from app.core.database import AsyncSessionLocal
from app.models.back_office import BoTeamMember
from app.models.consultant_portal import CpLink, CpMeeting
from app.models.contract import ContractStatus, Contract
from app.models.user import User, UserRole
from app.services.care.announcement_mail import MailOutcome
from app.services.consultant_portal import auth as portal_auth
from app.services.consultant_portal import portal_mail, sms
from app.services.consultant_portal_schema import PORTAL_SETTING
from app.services.hr_foundation_schema import HR_MODULE_KEYS, HR_MODULES_SETTING
from tests.care_announcements_seed import (
    _get_setting,
    _set_setting,
    make_client,
    make_consultant,
    make_user,
    tag,
)

BASE = "/api/public/consultant-portal"
STAFF = "/api/back-office/portal"
SESSION = "X-Portal-Session"


async def set_portal(state: Optional[str], pilot: Iterable[int] = ()) -> None:
    await _set_setting(
        PORTAL_SETTING,
        None if state is None else {"state": state, "pilot_contract_ids": list(pilot)},
    )


@pytest_asyncio.fixture
async def portal_restored():
    """Stan portalu po teście jak przed nim; moduł ``back_office`` włączony, bo bez niego portal jest zamknięty."""

    previous = await _get_setting(PORTAL_SETTING)
    modules = await _get_setting(HR_MODULES_SETTING)
    await _set_setting(
        HR_MODULES_SETTING,
        {
            **{key: False for key in HR_MODULE_KEYS},
            **(modules or {}),
            "back_office": True,
        },
    )
    yield
    await _set_setting(PORTAL_SETTING, previous)
    await _set_setting(
        HR_MODULES_SETTING, modules or {key: False for key in HR_MODULE_KEYS}
    )


@pytest_asyncio.fixture
async def portal_all(portal_restored):
    await set_portal("all")
    yield


@dataclass
class FakeSms:
    available: bool = True
    deliver: bool = True
    sent: list[dict] = field(default_factory=list)

    async def send(self, *, to: str, text: str) -> bool:
        self.sent.append({"to": to, "text": text})
        return self.deliver

    @property
    def last_code(self) -> str:
        return self.sent[-1]["text"].split(": ")[1].split(".")[0]


@dataclass
class FakePortalMailer:
    sent: list[dict] = field(default_factory=list)

    async def send(self, *, to: str, subject: str, text: str) -> MailOutcome:
        self.sent.append({"to": to, "subject": subject, "text": text})
        return MailOutcome("accepted")

    def last_token(self) -> str:
        return self.sent[-1]["text"].split("#")[1].split()[0]


def install_mailer(monkeypatch) -> FakePortalMailer:
    fake = FakePortalMailer()
    monkeypatch.setattr(portal_mail, "default_mailer", lambda: fake)
    return fake


def install_sms(monkeypatch, **kwargs) -> FakeSms:
    fake = FakeSms(**kwargs)
    monkeypatch.setattr(sms, "_override", fake)
    return fake


@dataclass
class Person:
    contract_id: int
    candidate_id: int
    client_id: int
    email: str


async def make_person(
    *,
    phone: Optional[str] = "+48 600 100 123",
    email: Optional[str] = None,
    status: ContractStatus = ContractStatus.active,
    candidate_id: Optional[int] = None,
) -> Person:
    address = email or f"konsultant-{tag()}@example.com"
    client_id = await make_client()
    contract_id, made_candidate = await make_consultant(
        client_id, contract_email=address, status=status
    )
    async with AsyncSessionLocal() as db:
        values: dict = {"candidate_phone": phone}
        if candidate_id is not None:
            values["candidate_id"] = candidate_id
        await db.execute(
            update(Contract).where(Contract.id == contract_id).values(**values)
        )
        await db.commit()
    return Person(
        contract_id=contract_id,
        candidate_id=candidate_id or made_candidate,
        client_id=client_id,
        email=address,
    )


async def direct_link(person: Person, *, ttl: timedelta = timedelta(minutes=30)) -> str:
    """Link z pominięciem maila: testy sesji nie zależą od nadawcy."""

    raw, digest = portal_auth.new_token()
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        db.add(
            CpLink(
                contract_id=person.contract_id,
                purpose="login",
                email=person.email,
                token_hash=digest,
                expires_at=now + ttl,
                created_at=now,
            )
        )
        await db.commit()
    return raw


async def session_headers(client, person: Person) -> dict[str, str]:
    raw = await direct_link(person)
    response = await client.post(f"{BASE}/session", json={"token": raw})
    assert response.status_code == 200, response.text
    return {SESSION: response.json()["session_token"]}


async def finance_headers(client, person: Person, fake_sms: FakeSms) -> dict[str, str]:
    headers = await session_headers(client, person)
    response = await client.post(f"{BASE}/finance/sms", headers=headers)
    assert response.status_code == 200, response.text
    response = await client.post(
        f"{BASE}/finance/verify", headers=headers, json={"code": fake_sms.last_code}
    )
    assert response.status_code == 200, response.text
    return headers


async def make_member(team: str, *, name: str = "Julia") -> User:
    user = await make_user(UserRole.recruiter, name=name)
    async with AsyncSessionLocal() as db:
        db.add(BoTeamMember(team=team, user_id=user.id))
        await db.commit()
    return user


@pytest_asyncio.fixture
async def clean_team():
    """Skład zespołów wpływa na domyślne członkostwo: test zaczyna od swojego."""

    async with AsyncSessionLocal() as db:
        await db.execute(delete(BoTeamMember))
        await db.commit()
    yield
    async with AsyncSessionLocal() as db:
        await db.execute(delete(BoTeamMember))
        await db.commit()


async def make_meeting(
    person: Person,
    host: Optional[User],
    *,
    start_in: timedelta = timedelta(hours=-2),
    status: str = "booked",
    **fields,
) -> int:
    start = datetime.now(timezone.utc).replace(microsecond=0) + start_in
    async with AsyncSessionLocal() as db:
        meeting = CpMeeting(
            contract_id=person.contract_id,
            host_user_id=host.id if host else None,
            topic="invoice",
            reason=fields.pop("reason", "Fikcyjny powód rozmowy"),
            start_at=start,
            end_at=start + timedelta(minutes=20),
            status=status,
            client_request_id=uuid.uuid4().hex,
            organizer_upn="wsparcie@example.com",
            **fields,
        )
        db.add(meeting)
        await db.commit()
        return meeting.id
