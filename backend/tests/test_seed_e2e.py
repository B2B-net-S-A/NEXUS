"""Kontrakt skryptu zasiewu kont E2E (`backend/scripts/seed_e2e.py`).

Stack E2E w CI stoi na tym skrypcie: jeśli model ``User`` zmieni wymagane
pola albo bramka onboardingu zacznie łapać zasiane konta, scenariusze
Playwrighta zobaczą ekran ``/onboarding`` zamiast przepływu. Ten test łapie
to w zwykłym pytest, zanim zrobi to nocny bieg.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.user import User, UserRole
from scripts import seed_e2e


def _unique_accounts() -> tuple[seed_e2e.E2EAccount, ...]:
    suffix = uuid.uuid4().hex[:8]
    return (
        seed_e2e.E2EAccount(f"e2e-admin-{suffix}@example.com", "E2E Admin", UserRole.admin),
        seed_e2e.E2EAccount(
            f"e2e-recruiter-{suffix}@example.com", "E2E Rekruter", UserRole.recruiter
        ),
    )


@pytest.fixture
def unique_accounts(monkeypatch: pytest.MonkeyPatch) -> tuple[seed_e2e.E2EAccount, ...]:
    accounts = _unique_accounts()
    monkeypatch.setattr(seed_e2e, "ACCOUNTS", accounts)
    # Wspólna baza testowa ma setki kont z innych testów — bramka „świeżej
    # bazy" jest sprawdzana osobnym testem niżej.
    monkeypatch.setattr(seed_e2e, "MAX_EXISTING_USERS", 10**9)
    return accounts


async def test_seed_creates_ready_accounts_idempotently(
    unique_accounts: tuple[seed_e2e.E2EAccount, ...],
) -> None:
    password = "E2e-Password-" + uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        created = await seed_e2e.seed_accounts(db, password)
    assert created == [account.email for account in unique_accounts]

    async with AsyncSessionLocal() as db:
        again = await seed_e2e.seed_accounts(db, password)
        users = (
            await db.scalars(
                select(User).where(User.email.in_([a.email for a in unique_accounts]))
            )
        ).all()
    assert again == []
    assert len(users) == len(unique_accounts)
    for user in users:
        assert user.is_active and user.email_verified and user.profile_completed
        assert user.role.value in user.roles


async def test_seeded_recruiter_logs_in_past_onboarding_gate(
    app_client: AsyncClient,
    unique_accounts: tuple[seed_e2e.E2EAccount, ...],
) -> None:
    password = "E2e-Password-" + uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        await seed_e2e.seed_accounts(db, password)
    recruiter = unique_accounts[1]

    login = await app_client.post(
        "/api/auth/login", json={"email": recruiter.email, "password": password}
    )
    assert login.status_code == 200, login.text
    me = await app_client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    )
    assert me.status_code == 200, me.text
    assert me.json()["profile_completed"] is True


async def test_seed_refuses_short_password(
    unique_accounts: tuple[seed_e2e.E2EAccount, ...],
) -> None:
    async with AsyncSessionLocal() as db:
        with pytest.raises(seed_e2e.SeedRefused):
            await seed_e2e.seed_accounts(db, "short")


async def test_seed_refuses_database_with_foreign_accounts(
    monkeypatch: pytest.MonkeyPatch,
    unique_accounts: tuple[seed_e2e.E2EAccount, ...],
) -> None:
    # Baza testowa ma zawsze co najmniej konto admina z `app_client` albo
    # z innych testów; próg -1 odtwarza „to nie jest świeży stack".
    monkeypatch.setattr(seed_e2e, "MAX_EXISTING_USERS", -1)
    async with AsyncSessionLocal() as db:
        with pytest.raises(seed_e2e.SeedRefused):
            await seed_e2e.seed_accounts(db, "E2e-Password-long-enough")
        created = await db.scalar(
            select(User.id).where(User.email == unique_accounts[0].email)
        )
    assert created is None


async def test_main_requires_confirm_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("E2E_SEED_CONFIRM", raising=False)
    assert await seed_e2e._main() == 2
