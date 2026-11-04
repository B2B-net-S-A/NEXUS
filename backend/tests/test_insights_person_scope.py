"""Kto stoi w tabelach osób w Insights: konta integracji OAuth poza nimi (30.10.2026).

Konto scraperów ma rolę TCM (przez nią idzie RBAC zapisu kandydatów), więc sama
reguła ról zostawiała je w „Wynikach osób” z zerami i na 1. miejscu rankingu
aktywności. Rozpoznajemy je po ``oauth_clients.acting_user_id``.
"""

import uuid

import pytest

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.oauth_client import OAuthClient
from app.models.user import User, UserRole
from app.services.insights_person_scope import outside_scope_user_ids


async def _user(db, role: UserRole) -> User:
    user = User(
        email=f"scope-{uuid.uuid4().hex[:10]}@example.com",
        name="Zakres testowy",
        password_hash=hash_password("Test-no-login-1!"),
        role=role,
        is_active=True,
        profile_completed=True,
    )
    db.add(user)
    await db.flush()
    return user


def _client_acting_as(user: User, *, enabled: bool) -> OAuthClient:
    marker = uuid.uuid4().hex[:10]
    return OAuthClient(
        name=f"Integracje {marker}",
        client_id=f"integracje-{marker}",
        secret_hash="!test-no-secret!",
        scopes=["candidate:write"],
        enabled=enabled,
        acting_user_id=user.id,
    )


@pytest.mark.asyncio
async def test_integration_account_with_recruiting_role_is_outside_people_tables() -> (
    None
):
    async with AsyncSessionLocal() as db:
        integration = await _user(db, UserRole.talent_community_manager)
        db.add(_client_acting_as(integration, enabled=True))
        await db.flush()

        outside = await outside_scope_user_ids(db, [integration.id])

        assert outside == {integration.id}
        await db.rollback()


@pytest.mark.asyncio
async def test_disabled_client_does_not_turn_the_account_into_a_person() -> None:
    """Wyłączenie klienta na chwilę nie może wstawić konta z powrotem do rankingów."""
    async with AsyncSessionLocal() as db:
        integration = await _user(db, UserRole.talent_community_manager)
        db.add(_client_acting_as(integration, enabled=False))
        await db.flush()

        outside = await outside_scope_user_ids(db, [integration.id])

        assert outside == {integration.id}
        await db.rollback()


@pytest.mark.asyncio
async def test_people_with_recruiting_roles_stay_and_admin_accounts_stay_outside() -> (
    None
):
    async with AsyncSessionLocal() as db:
        tcm = await _user(db, UserRole.talent_community_manager)
        recruiter = await _user(db, UserRole.recruiter)
        admin = await _user(db, UserRole.admin)
        await db.flush()

        outside = await outside_scope_user_ids(db, [tcm.id, recruiter.id, admin.id])

        assert outside == {admin.id}
        await db.rollback()
