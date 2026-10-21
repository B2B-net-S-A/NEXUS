"""Konto NEXUSA idzie za kontem Microsoft 365 (``m365_account_sweep``).

404 z ``Request_ResourceNotFound`` albo ``accountEnabled=false`` wyłącza
konto (tryb ``enforce``); 5xx, 429, inne 404, brak poświadczeń i odmowa
rejestracji nic nie zmieniają; przebieg z więcej niż limitem kont do
wyłączenia nie wyłącza żadnego; ostatni admin i włączenie przez admina po
naszym wyłączeniu wygrywają; tryb ``report`` nie zapisuje. Dane fikcyjne.

Katalog to atrapa: konto, którego atrapa nie zna, jest żywe — konta
z ``azure_oid`` zostawione w bazie przez inne testy nie zmieniają wyniku.
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.activity import Activity
from app.models.user import User, UserRole
from app.services import m365_account_sweep as sweep
from app.services.hr.account_profiles import DEACTIVATION_ACTIONS
from app.services.hr.m365.ops import MailboxError


class FakeDirectory:
    def __init__(self) -> None:
        self.gone: set[str] = set()
        self.disabled: set[str] = set()
        self.failures: dict[str, MailboxError] = {}
        self.calls: list[str] = []
        self.closed = False

    async def get_account(self, object_id: str) -> dict[str, Any]:
        self.calls.append(object_id)
        if object_id in self.failures:
            raise self.failures[object_id]
        if object_id in self.gone:
            raise MailboxError(404, "Request_ResourceNotFound")
        return {"id": object_id, "accountEnabled": object_id not in self.disabled}

    async def aclose(self) -> None:
        self.closed = True


@pytest.fixture
def enforce(monkeypatch):
    monkeypatch.setattr(settings, "M365_ACCOUNT_SWEEP_MODE", "enforce")
    monkeypatch.setattr(settings, "M365_ACCOUNT_SWEEP_MAX_PER_RUN", 10)


async def _make_user(role: str = "recruiter") -> tuple[int, str]:
    marker = uuid.uuid4().hex[:10]
    oid = str(uuid.uuid4())
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"sweep-{marker}@example.com",
            name=f"Osoba {marker}",
            role=UserRole(role),
            roles=[role],
            is_active=True,
            oauth_provider="microsoft",
            external_id=oid,
            azure_oid=oid,
        )
        db.add(user)
        await db.commit()
        return user.id, oid


async def _user(user_id: int) -> User:
    async with AsyncSessionLocal() as db:
        user = await db.get(User, user_id)
        assert user is not None
        return user


async def _actions(user_id: int) -> list[str]:
    async with AsyncSessionLocal() as db:
        rows = await db.scalars(
            select(Activity.action)
            .where(Activity.entity_type == "user", Activity.entity_id == user_id)
            .order_by(Activity.id)
        )
        return list(rows)


async def _switch_off(user_id: int) -> None:
    """Sprzątanie: dodatkowy aktywny admin nie zostaje w bazie innych testów."""

    async with AsyncSessionLocal() as db:
        user = await db.get(User, user_id)
        if user is not None:
            user.is_active = False
            await db.commit()


async def _run(directory: FakeDirectory) -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        return await sweep.run_once(db, directory=directory)


# ── Czyste reguły ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("data", "error", "expected"),
    [
        (None, MailboxError(404, "Request_ResourceNotFound"), "not_found"),
        (None, MailboxError(404, "ResourceNotFound"), "not_found"),
        (None, MailboxError(404, "MailboxNotEnabledForRESTAPI"), None),
        (None, MailboxError(404), None),
        (None, MailboxError(500), None),
        (None, MailboxError(503), None),
        (None, MailboxError(429), None),
        (None, MailboxError(None, category="network"), None),
        ({"accountEnabled": False}, None, "disabled"),
        ({"accountEnabled": True}, None, None),
        ({}, None, None),
        ({"accountEnabled": None}, None, None),
    ],
)
def test_gone_reason_only_on_unambiguous_signal(data, error, expected) -> None:
    assert sweep.gone_reason(data, error) == expected


@pytest.mark.parametrize(
    ("value", "mode"),
    [
        ("off", "off"),
        ("enforce", "enforce"),
        (" ENFORCE ", "enforce"),
        ("report", "report"),
        ("", "report"),
        ("live", "report"),
    ],
)
def test_unknown_mode_falls_back_to_report(monkeypatch, value, mode) -> None:
    monkeypatch.setattr(settings, "M365_ACCOUNT_SWEEP_MODE", value)
    assert sweep.current_mode() == mode


def test_deactivation_action_dates_the_profile_exit() -> None:
    assert sweep.DEACTIVATION_ACTION in DEACTIVATION_ACTIONS


@pytest.mark.asyncio
async def test_off_mode_touches_nothing(monkeypatch) -> None:
    monkeypatch.setattr(settings, "M365_ACCOUNT_SWEEP_MODE", "off")
    directory = FakeDirectory()
    assert (await sweep.run_once(None, directory=directory))["status"] == "disabled"  # type: ignore[arg-type]
    assert directory.calls == []


@pytest.mark.asyncio
async def test_missing_credentials_touch_nothing(monkeypatch, enforce) -> None:
    monkeypatch.setattr(sweep, "_credentials_configured", lambda: False)
    result = await sweep.run_once(None)  # type: ignore[arg-type]
    assert result["status"] == "no_credentials"


# ── Przebieg na bazie ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_deleted_account_is_deactivated_like_admin_delete(enforce) -> None:
    user_id, oid = await _make_user()
    before = await _user(user_id)
    directory = FakeDirectory()
    directory.gone.add(oid)

    result = await _run(directory)

    assert result["status"] == "ok"
    assert user_id in result["deactivated"]
    assert oid in directory.calls and directory.closed
    after = await _user(user_id)
    assert after.is_active is False
    assert after.authorization_version == before.authorization_version + 1
    assert after.tokens_valid_after is not None
    assert await _actions(user_id) == [sweep.DEACTIVATION_ACTION]
    async with AsyncSessionLocal() as db:
        entry = await db.scalar(
            select(Activity).where(
                Activity.entity_id == user_id,
                Activity.action == sweep.DEACTIVATION_ACTION,
            )
        )
        assert entry is not None and entry.user_id is None
        assert entry.details["m365_reason"] == "not_found"

    # Konto już wyłączone nie jest czytane ponownie.
    second = FakeDirectory()
    second.gone.add(oid)
    await _run(second)
    assert oid not in second.calls


@pytest.mark.asyncio
async def test_disabled_account_is_deactivated(enforce) -> None:
    user_id, oid = await _make_user()
    directory = FakeDirectory()
    directory.disabled.add(oid)

    result = await _run(directory)

    assert user_id in result["deactivated"]
    assert (await _user(user_id)).is_active is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        MailboxError(500),
        MailboxError(503),
        MailboxError(429),
        MailboxError(None, category="network"),
        MailboxError(404, "SomethingElse"),
    ],
)
async def test_transient_or_ambiguous_errors_change_nothing(enforce, error) -> None:
    user_id, oid = await _make_user()
    directory = FakeDirectory()
    directory.failures[oid] = error

    result = await _run(directory)

    assert result["status"] == "ok"
    assert result["errors"] >= 1
    assert user_id not in result["deactivated"]
    assert (await _user(user_id)).is_active is True
    assert await _actions(user_id) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403])
async def test_rejected_registration_aborts_without_changes(enforce, status) -> None:
    gone_id, gone_oid = await _make_user()
    _, failing_oid = await _make_user()
    directory = FakeDirectory()
    directory.gone.add(gone_oid)
    directory.failures[failing_oid] = MailboxError(status)

    result = await _run(directory)

    assert result["status"] == "aborted"
    assert directory.closed
    assert (await _user(gone_id)).is_active is True


@pytest.mark.asyncio
async def test_more_than_limit_deactivates_nobody(enforce, monkeypatch) -> None:
    monkeypatch.setattr(settings, "M365_ACCOUNT_SWEEP_MAX_PER_RUN", 2)
    users = [await _make_user() for _ in range(3)]
    directory = FakeDirectory()
    directory.gone.update(oid for _, oid in users)

    result = await _run(directory)

    assert result["status"] == "mass_suspected"
    assert {user_id for user_id, _ in users} <= set(result["planned"])
    for user_id, _ in users:
        assert (await _user(user_id)).is_active is True
        assert await _actions(user_id) == []


@pytest.mark.asyncio
async def test_report_mode_writes_nothing(monkeypatch) -> None:
    monkeypatch.setattr(settings, "M365_ACCOUNT_SWEEP_MODE", "report")
    user_id, oid = await _make_user()
    directory = FakeDirectory()
    directory.gone.add(oid)

    result = await _run(directory)

    assert result["status"] == "ok" and result["mode"] == "report"
    assert user_id in result["planned"]
    assert "deactivated" not in result
    assert (await _user(user_id)).is_active is True
    assert await _actions(user_id) == []


@pytest.mark.asyncio
async def test_last_active_admin_stays_enabled(enforce, monkeypatch) -> None:
    user_id, oid = await _make_user(role="admin")

    async def refuse(*_args, **_kwargs):
        raise HTTPException(
            status_code=409, detail="At least one active administrator must remain"
        )

    monkeypatch.setattr(sweep, "protect_active_admin_membership", refuse)
    directory = FakeDirectory()
    directory.gone.add(oid)

    result = await _run(directory)

    assert user_id in result["skipped_last_admin"]
    assert user_id not in result["deactivated"]
    assert (await _user(user_id)).is_active is True
    await _switch_off(user_id)


@pytest.mark.asyncio
async def test_admin_with_another_active_admin_is_deactivated(enforce) -> None:
    other_id, _ = await _make_user(role="admin")
    user_id, oid = await _make_user(role="admin")
    directory = FakeDirectory()
    directory.gone.add(oid)

    result = await _run(directory)

    assert user_id in result["deactivated"]
    assert (await _user(user_id)).is_active is False
    await _switch_off(other_id)


@pytest.mark.asyncio
async def test_admin_reenable_after_sweep_wins(enforce) -> None:
    user_id, oid = await _make_user()
    directory = FakeDirectory()
    directory.gone.add(oid)
    await _run(directory)
    assert (await _user(user_id)).is_active is False

    # Admin włącza konto w „Osoby i role” (PUT /api/admin/users/{id}).
    async with AsyncSessionLocal() as db:
        user = await db.get(User, user_id)
        assert user is not None
        user.is_active = True
        db.add(
            Activity(
                entity_type="user",
                entity_id=user_id,
                action="active_changed",
                user_id=None,
                details={"from": False, "to": True},
            )
        )
        await db.commit()

    again = FakeDirectory()
    again.gone.add(oid)
    result = await _run(again)

    assert user_id in result["kept_by_admin"]
    assert user_id not in result["deactivated"]
    assert (await _user(user_id)).is_active is True
    assert await _actions(user_id) == [sweep.DEACTIVATION_ACTION, "active_changed"]


@pytest.mark.asyncio
async def test_unknown_or_missing_admin_decision_does_not_protect(enforce) -> None:
    user_id, oid = await _make_user()
    assert await _kept(user_id) is False
    directory = FakeDirectory()
    directory.gone.add(oid)
    result = await _run(directory)
    assert user_id in result["deactivated"]


async def _kept(user_id: int) -> Optional[bool]:
    async with AsyncSessionLocal() as db:
        return await sweep._kept_by_admin(db, user_id)
