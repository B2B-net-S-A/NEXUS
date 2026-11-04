"""Bufor polityki dostępu: trafienie, kasowanie po commicie, limit 30 s, odmowa.

Decyzja Artura 04.11.2026. Odebranie uprawnienia ma działać od następnego
żądania, więc najważniejsze są tu ścieżki, w których bufor mógłby oddać stary
wiersz: odczyt równoległy do commitu, zapis w SAVEPOINT i sesja przed commitem.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, event, select, text, update

from app.core.database import AsyncSessionLocal, engine
from app.core.security import hash_password
from app.models.app_setting import AppSetting
from app.models.section_permission import (
    RbacPermissionAudit,
    RoleActionPermission,
    UserActionOverride,
    UserSectionOverride,
)
from app.models.user import User, UserRole
from app.services import notification_role_mutes as role_mutes
from app.services import policy_cache
from app.services.action_permissions import has_permission
from app.services.effective_access import resolve_effective_access
from app.services.notification_categories import GROUP_INFO, group_is_mutable
from app.services.section_permissions import ProductSection, SectionAccess

pytestmark = pytest.mark.asyncio

PANEL = "/api/admin/section-permissions"
# Trasa z ``FinanceModuleUser``: puste ciało przechodzi bramkę i odpada na
# walidacji, więc 403 znaczy odmowę bramki.
FINANCE_ROUTE = "/api/finance/order-changes/checks"
PERMISSION = "finance_module"

Account = dict[str, object]


@pytest.fixture(autouse=True)
def _cache_on(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(policy_cache, "_CACHE_TTL_SECONDS", 30.0)
    policy_cache.invalidate_policy_cache()
    yield
    policy_cache.invalidate_policy_cache()


@pytest.fixture
def statements() -> Iterator[list[str]]:
    """Instrukcje SQL wysłane do bazy w trakcie testu."""
    seen: list[str] = []

    def _record(_conn, _cursor, statement, _params, _context, _many) -> None:
        seen.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", _record)
    yield seen
    event.remove(engine.sync_engine, "before_cursor_execute", _record)


@pytest_asyncio.fixture
async def make_account() -> AsyncIterator[Callable[[UserRole], Awaitable[Account]]]:
    created: list[int] = []

    async def _make(role: UserRole) -> Account:
        unique = uuid.uuid4().hex[:10]
        email = f"pytest-policy-cache-{unique}@example.com"
        password = f"Policy_{unique}_Pass!"
        async with AsyncSessionLocal() as db:
            user = User(
                email=email,
                password_hash=hash_password(password),
                name="Policy Target",
                role=role,
                roles=[role.value],
                is_active=True,
                email_verified=True,
                profile_completed=True,
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)
            created.append(user.id)
            return {"id": user.id, "email": email, "password": password}

    yield _make

    async with AsyncSessionLocal() as db:
        for user_id in created:
            await db.execute(
                delete(RbacPermissionAudit).where(
                    RbacPermissionAudit.target_kind == "user",
                    RbacPermissionAudit.target_key == str(user_id),
                )
            )
            await db.execute(
                delete(UserSectionOverride).where(
                    UserSectionOverride.user_id == user_id
                )
            )
            await db.execute(
                delete(UserActionOverride).where(UserActionOverride.user_id == user_id)
            )
            target = await db.scalar(select(User).where(User.id == user_id))
            if target is not None:
                await db.delete(target)
        await db.commit()


async def _resolved(user_id: int) -> User:
    async with AsyncSessionLocal() as db:
        user = await db.scalar(select(User).where(User.id == user_id))
        assert user is not None
        await resolve_effective_access(db, [user])
        return user


async def _set_override(user_id: int, access: str | None) -> None:
    """Zapis ORM w osobnej sesji: tak jak trasa panelu, ale bez API."""
    async with AsyncSessionLocal() as db:
        row = await db.scalar(
            select(UserActionOverride).where(
                UserActionOverride.user_id == user_id,
                UserActionOverride.action == PERMISSION,
            )
        )
        if access is None:
            if row is not None:
                await db.delete(row)
        elif row is None:
            db.add(
                UserActionOverride(user_id=user_id, action=PERMISSION, access=access)
            )
        else:
            row.access = access
        await db.commit()


async def _write_past_the_session(user_id: int, access: str) -> None:
    """Zapis, którego zdarzenia sesji nie widzą: jak drugi proces."""
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO rbac_user_action_overrides (user_id, action, access) "
                "VALUES (:user_id, :action, :access) "
                "ON CONFLICT (user_id, action) DO UPDATE SET access = :access"
            ),
            {"user_id": user_id, "action": PERMISSION, "access": access},
        )


def _advance_clock(monkeypatch: pytest.MonkeyPatch, seconds: float) -> None:
    now = policy_cache._clock()
    monkeypatch.setattr(policy_cache, "_clock", lambda: now + seconds)


# ── Trafienie ────────────────────────────────────────────────────────────────


async def test_second_resolve_asks_the_database_for_nothing(
    make_account: Callable[[UserRole], Awaitable[Account]],
    statements: list[str],
) -> None:
    account = await make_account(UserRole.finance)
    user_id = int(account["id"])

    first = await _resolved(user_id)
    loaded = [sql for sql in statements if "rbac_" in sql or "app_settings" in sql]
    assert len(loaded) == 5

    statements.clear()
    second = await _resolved(user_id)
    assert [sql for sql in statements if "rbac_" in sql or "app_settings" in sql] == []
    assert second.effective_action_access == first.effective_action_access
    assert second.effective_section_access == first.effective_section_access


async def test_hit_gives_the_same_policy_as_reading_through_the_session(
    make_account: Callable[[UserRole], Awaitable[Account]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Migawka i stara ścieżka to ta sama polityka dla każdej roli i wyjątku."""
    accounts = [
        await make_account(role)
        for role in (UserRole.finance, UserRole.recruiter, UserRole.delivery_lead)
    ]
    await _set_override(int(accounts[1]["id"]), "manage")
    await _set_override(int(accounts[0]["id"]), "none")

    for account in accounts:
        user_id = int(account["id"])
        cached = await _resolved(user_id)
        monkeypatch.setattr(policy_cache, "_CACHE_TTL_SECONDS", -1)
        direct = await _resolved(user_id)
        monkeypatch.setattr(policy_cache, "_CACHE_TTL_SECONDS", 30.0)
        assert cached.effective_action_access == direct.effective_action_access
        assert cached.effective_section_access == direct.effective_section_access
        assert (
            cached.role_muted_notification_types == direct.role_muted_notification_types
        )


async def test_concurrent_misses_load_the_snapshot_once(
    make_account: Callable[[UserRole], Awaitable[Account]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account = await make_account(UserRole.finance)
    user_id = int(account["id"])
    load = policy_cache._load_snapshot
    loads = 0

    async def _slow_load(db):
        # Bez przerwy pierwsze zadanie kończy, zanim reszta dostanie połączenie.
        nonlocal loads
        loads += 1
        await asyncio.sleep(0.2)
        return await load(db)

    monkeypatch.setattr(policy_cache, "_load_snapshot", _slow_load)

    resolved = await asyncio.gather(*(_resolved(user_id) for _ in range(8)))

    assert loads == 1
    assert all(has_permission(user, PERMISSION) for user in resolved)


async def test_snapshot_holds_values_not_orm_objects(
    make_account: Callable[[UserRole], Awaitable[Account]],
) -> None:
    account = await make_account(UserRole.finance)
    user_id = int(account["id"])
    await _set_override(user_id, "none")
    await _resolved(user_id)

    snapshot = policy_cache._snapshot
    assert snapshot is not None
    assert snapshot.section_role_rows and snapshot.action_role_rows
    rows = [
        *snapshot.section_role_rows,
        *snapshot.action_role_rows,
        *snapshot.action_overrides[user_id],
    ]
    assert all(isinstance(row, tuple) for row in rows)
    assert not any(hasattr(row, "_sa_instance_state") for row in rows)


# ── Kasowanie po zapisie ─────────────────────────────────────────────────────


async def test_personal_override_change_takes_effect_immediately(
    make_account: Callable[[UserRole], Awaitable[Account]],
) -> None:
    account = await make_account(UserRole.finance)
    user_id = int(account["id"])

    assert has_permission(await _resolved(user_id), PERMISSION)
    await _set_override(user_id, "none")
    revoked = await _resolved(user_id)
    assert not has_permission(revoked, PERMISSION)
    assert revoked.effective_section_access["finance"] == "none"

    await _set_override(user_id, None)
    assert has_permission(await _resolved(user_id), PERMISSION)


async def test_personal_section_override_change_takes_effect_immediately(
    make_account: Callable[[UserRole], Awaitable[Account]],
) -> None:
    account = await make_account(UserRole.recruiter)
    user_id = int(account["id"])
    section = ProductSection.insights.value

    assert (await _resolved(user_id)).effective_section_access[section] != "none"
    async with AsyncSessionLocal() as db:
        db.add(
            UserSectionOverride(
                user_id=user_id, section=section, access=SectionAccess.none.name
            )
        )
        await db.commit()
    assert (await _resolved(user_id)).effective_section_access[section] == "none"


async def test_role_change_takes_effect_immediately(
    make_account: Callable[[UserRole], Awaitable[Account]],
) -> None:
    account = await make_account(UserRole.finance)
    user_id = int(account["id"])
    role = UserRole.finance.value

    async with AsyncSessionLocal() as db:
        original = (
            await db.scalars(
                select(RoleActionPermission).where(
                    RoleActionPermission.role == role,
                    RoleActionPermission.action == PERMISSION,
                )
            )
        ).one()
        original_access = original.access
    assert has_permission(await _resolved(user_id), PERMISSION)
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(RoleActionPermission)
                .where(
                    RoleActionPermission.role == role,
                    RoleActionPermission.action == PERMISSION,
                )
                .values(access="none")
            )
            await db.commit()
        assert not has_permission(await _resolved(user_id), PERMISSION)
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(RoleActionPermission)
                .where(
                    RoleActionPermission.role == role,
                    RoleActionPermission.action == PERMISSION,
                )
                .values(access=original_access)
            )
            await db.commit()
    assert has_permission(await _resolved(user_id), PERMISSION)


async def test_plain_sql_through_the_session_also_invalidates(
    make_account: Callable[[UserRole], Awaitable[Account]],
) -> None:
    account = await make_account(UserRole.finance)
    user_id = int(account["id"])
    assert has_permission(await _resolved(user_id), PERMISSION)

    async with AsyncSessionLocal() as db:
        await db.execute(
            text(
                "INSERT INTO rbac_user_action_overrides (user_id, action, access) "
                "VALUES (:user_id, :action, 'none')"
            ),
            {"user_id": user_id, "action": PERMISSION},
        )
        await db.commit()

    assert not has_permission(await _resolved(user_id), PERMISSION)


async def test_role_mutes_change_takes_effect_immediately(
    make_account: Callable[[UserRole], Awaitable[Account]],
) -> None:
    account = await make_account(UserRole.recruiter)
    user_id = int(account["id"])
    role = UserRole.recruiter.value
    group = next(name for name in GROUP_INFO if group_is_mutable(name))

    async with AsyncSessionLocal() as db:
        before = await db.scalar(
            select(AppSetting).where(AppSetting.key == role_mutes.SETTING_KEY)
        )
        had_row = before is not None
        original = before.value if before is not None else None
    assert policy_cache._ROLE_MUTES_KEY == role_mutes.SETTING_KEY

    await _resolved(user_id)
    try:
        async with AsyncSessionLocal() as db:
            actor = await db.get(User, user_id)
            revision = (await role_mutes.load_value(db))["revision"]
            await role_mutes.save_changes(
                db,
                actor=actor,
                revision=revision,
                changes=[role_mutes.RoleMuteChange(role=role, group=group, muted=True)],
            )
            await db.commit()
        assert (await _resolved(user_id)).role_muted_notification_types
    finally:
        async with AsyncSessionLocal() as db:
            if had_row:
                await db.execute(
                    update(AppSetting)
                    .where(AppSetting.key == role_mutes.SETTING_KEY)
                    .values(value=original)
                )
            else:
                await db.execute(
                    delete(AppSetting).where(AppSetting.key == role_mutes.SETTING_KEY)
                )
            await db.commit()
        policy_cache.invalidate_policy_cache()


# ── Nic starego nie zostaje w buforze ────────────────────────────────────────


async def test_read_started_before_the_commit_is_not_stored(
    make_account: Callable[[UserRole], Awaitable[Account]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Odczyt, który wziął stare wiersze, nie może ich wstawić po kasowaniu."""
    account = await make_account(UserRole.finance)
    user_id = int(account["id"])
    load = policy_cache._load_snapshot

    async def _load_then_someone_commits(db):
        snapshot = await load(db)
        await _set_override(user_id, "none")
        return snapshot

    monkeypatch.setattr(policy_cache, "_load_snapshot", _load_then_someone_commits)
    racing = await _resolved(user_id)
    monkeypatch.setattr(policy_cache, "_load_snapshot", load)

    # Żądanie w locie liczy się ze starym stanem; następne już nie.
    assert has_permission(racing, PERMISSION)
    assert policy_cache._snapshot is None
    assert not has_permission(await _resolved(user_id), PERMISSION)


async def test_uncommitted_write_stays_invisible_and_is_seen_by_its_own_session(
    make_account: Callable[[UserRole], Awaitable[Account]],
) -> None:
    account = await make_account(UserRole.finance)
    user_id = int(account["id"])
    assert has_permission(await _resolved(user_id), PERMISSION)

    async with AsyncSessionLocal() as db:
        db.add(UserActionOverride(user_id=user_id, action=PERMISSION, access="none"))
        await db.flush()

        # Sesja, która zapisała, widzi swój wiersz, a inni jeszcze nie.
        own = await db.scalar(select(User).where(User.id == user_id))
        await resolve_effective_access(db, [own])
        assert not has_permission(own, PERMISSION)
        assert has_permission(await _resolved(user_id), PERMISSION)

        await db.rollback()

    # Wycofany zapis nie zmienia polityki ani nie kasuje bufora.
    snapshot = policy_cache._snapshot
    assert snapshot is not None
    assert has_permission(await _resolved(user_id), PERMISSION)
    assert policy_cache._snapshot is snapshot


async def test_savepoint_release_does_not_publish_until_the_real_commit(
    make_account: Callable[[UserRole], Awaitable[Account]],
) -> None:
    account = await make_account(UserRole.finance)
    user_id = int(account["id"])
    assert has_permission(await _resolved(user_id), PERMISSION)

    async with AsyncSessionLocal() as db:
        async with db.begin_nested():
            db.add(
                UserActionOverride(user_id=user_id, action=PERMISSION, access="none")
            )
            await db.flush()
        snapshot = policy_cache._snapshot
        assert snapshot is not None, (
            "zwolnienie SAVEPOINT-u skasowało bufor za wcześnie"
        )

        # Po zwolnieniu SAVEPOINT-u sesja dalej czyta przez siebie.
        own = await db.scalar(select(User).where(User.id == user_id))
        await resolve_effective_access(db, [own])
        assert not has_permission(own, PERMISSION)
        assert has_permission(await _resolved(user_id), PERMISSION)

        await db.commit()

    assert not has_permission(await _resolved(user_id), PERMISSION)


# ── Limit 30 s ───────────────────────────────────────────────────────────────


async def test_change_from_another_process_is_seen_after_thirty_seconds(
    make_account: Callable[[UserRole], Awaitable[Account]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account = await make_account(UserRole.finance)
    user_id = int(account["id"])
    assert has_permission(await _resolved(user_id), PERMISSION)
    await _write_past_the_session(user_id, "none")

    _advance_clock(monkeypatch, 29.0)
    assert has_permission(await _resolved(user_id), PERMISSION)

    _advance_clock(monkeypatch, 31.0)
    assert not has_permission(await _resolved(user_id), PERMISSION)


# ── Cała ścieżka przez API ───────────────────────────────────────────────────


async def _login(client: AsyncClient, account: Account) -> dict[str, str]:
    response = await client.post(
        "/api/auth/login",
        json={"email": account["email"], "password": account["password"]},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def test_revoking_through_the_panel_gives_403_on_the_next_request(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
    make_account: Callable[[UserRole], Awaitable[Account]],
) -> None:
    """Ścieżka odmowy: bufor jest ciepły przed zmianą, a odmowa przychodzi od razu."""
    account = await make_account(UserRole.finance)
    colleague = await make_account(UserRole.finance)
    target_url = f"{PANEL}/users/{account['id']}"
    headers = await _login(app_client, account)
    colleague_headers = await _login(app_client, colleague)
    # Zmiany w zamówieniach mają od 04.11.2026 własne uprawnienie, więc odebranie
    # „Modułu Finanse” widać na trasie Wyników.
    results_route = "/api/finance/periods"

    allowed = await app_client.get(results_route, headers=headers)
    assert allowed.status_code == 200, allowed.text
    assert policy_cache._snapshot is not None

    panel = await app_client.get(PANEL, headers=app_auth_headers)
    assert panel.status_code == 200, panel.text
    revision = panel.json()["revision"]
    revoke = await app_client.put(
        target_url,
        headers=app_auth_headers,
        json={
            "revision": revision,
            "action_changes": [{"action": PERMISSION, "access": "none"}],
        },
    )
    assert revoke.status_code == 200, revoke.text

    # Stary token odpada przez `authorization_version`, a nowy trafia na bufor.
    stale = await app_client.get(results_route, headers=headers)
    assert stale.status_code == 401, stale.text
    headers = await _login(app_client, account)
    denied = await app_client.get(results_route, headers=headers)
    assert denied.status_code == 403, denied.text
    assert denied.json()["detail"]["code"] == "permission_denied"
    assert denied.json()["detail"]["permission"] == PERMISSION

    untouched = await app_client.get(results_route, headers=colleague_headers)
    assert untouched.status_code == 200, untouched.text

    lifted = await app_client.put(
        target_url,
        headers=app_auth_headers,
        json={
            "revision": revision + 1,
            "action_changes": [{"action": PERMISSION, "access": "inherit"}],
        },
    )
    assert lifted.status_code == 200, lifted.text
    headers = await _login(app_client, account)
    restored = await app_client.get(results_route, headers=headers)
    assert restored.status_code == 200, restored.text
