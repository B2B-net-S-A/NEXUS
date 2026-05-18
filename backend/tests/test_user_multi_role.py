"""Tests for User multi-role helpers (migracja 0110).

Covers:

* ``User.has_role`` — primary + secondary role lookup
* ``User.has_any_role`` — used by ``require_roles`` dependency
* ``User.get_all_roles`` — set union of primary + roles
* ``User.ensure_roles_invariant`` — primary always inside ``roles``
* ``require_roles`` dependency — hybrid DL+TAC user passes both
  ``DeliveryLeadPlus`` and ``TacPlus``.
"""

from __future__ import annotations

import pytest

from app.api.deps import require_roles
from app.models.user import User, UserRole


def _make_user(role: UserRole, roles: list[str] | None = None) -> User:
    """Build a transient User (no DB) for helper-method tests."""
    u = User(
        email="multi@b2bnetwork.pl",
        name="Multi Role",
        role=role,
        roles=roles if roles is not None else [role.value],
        is_active=True,
        profile_completed=True,
    )
    return u


# ── has_role ────────────────────────────────────────────────────────────────


def test_has_role_finds_primary():
    u = _make_user(UserRole.delivery_lead)
    assert u.has_role(UserRole.delivery_lead) is True
    assert u.has_role("delivery_lead") is True


def test_has_role_finds_secondary():
    u = _make_user(UserRole.delivery_lead, ["delivery_lead", "tac"])
    assert u.has_role(UserRole.tac) is True
    assert u.has_role("tac") is True


def test_has_role_returns_false_for_unrelated_role():
    u = _make_user(UserRole.delivery_lead, ["delivery_lead", "tac"])
    assert u.has_role(UserRole.admin) is False
    assert u.has_role(UserRole.sourcer) is False


def test_has_role_handles_empty_roles_list():
    """Defensive: secondary list empty → fallback to primary."""
    u = _make_user(UserRole.admin, [])
    assert u.has_role(UserRole.admin) is True
    assert u.has_role(UserRole.recruiter) is False


# ── has_any_role ────────────────────────────────────────────────────────────


def test_has_any_role_passes_with_one_match():
    u = _make_user(UserRole.delivery_lead, ["delivery_lead", "tac"])
    assert u.has_any_role(UserRole.admin, UserRole.tac) is True
    assert u.has_any_role(UserRole.admin, UserRole.delivery_lead) is True


def test_has_any_role_fails_with_no_match():
    u = _make_user(UserRole.recruiter, ["recruiter"])
    assert u.has_any_role(UserRole.admin, UserRole.delivery_lead) is False


# ── get_all_roles ───────────────────────────────────────────────────────────


def test_get_all_roles_unions_primary_and_secondary():
    u = _make_user(UserRole.delivery_lead, ["delivery_lead", "tac"])
    assert u.get_all_roles() == {UserRole.delivery_lead, UserRole.tac}


def test_get_all_roles_drops_unknown_strings():
    """Stale role strings (e.g. dropped from enum) shouldn't raise."""
    u = _make_user(UserRole.admin, ["admin", "ghost_role"])
    assert u.get_all_roles() == {UserRole.admin}


def test_get_all_roles_when_primary_only():
    u = _make_user(UserRole.sourcer, ["sourcer"])
    assert u.get_all_roles() == {UserRole.sourcer}


# ── ensure_roles_invariant ──────────────────────────────────────────────────


def test_ensure_roles_invariant_inserts_missing_primary():
    """If primary somehow drops out of roles, the invariant restores it."""
    u = _make_user(UserRole.admin, ["recruiter"])
    u.ensure_roles_invariant()
    assert "admin" in u.roles
    # Primary should be at index 0 (first-class) for predictable ordering.
    assert u.roles[0] == "admin"


def test_ensure_roles_invariant_is_idempotent():
    u = _make_user(UserRole.delivery_lead, ["delivery_lead", "tac"])
    before = list(u.roles)
    u.ensure_roles_invariant()
    assert u.roles == before


# ── require_roles dependency (hybrid user) ──────────────────────────────────


@pytest.mark.asyncio
async def test_require_roles_passes_hybrid_dl_tac_user_for_tac_plus():
    """DL+TAC user must pass a TAC-only guard via the secondary role."""
    u = _make_user(UserRole.delivery_lead, ["delivery_lead", "tac"])
    dep = require_roles(UserRole.admin, UserRole.delivery_lead, UserRole.tac)
    result = await dep(current_user=u)
    assert result is u


@pytest.mark.asyncio
async def test_require_roles_passes_hybrid_dl_tac_user_for_dl_plus():
    """Same user must pass the DL-only guard via the primary role."""
    u = _make_user(UserRole.delivery_lead, ["delivery_lead", "tac"])
    dep = require_roles(UserRole.admin, UserRole.delivery_lead)
    result = await dep(current_user=u)
    assert result is u


@pytest.mark.asyncio
async def test_require_roles_rejects_user_without_required_role():
    from fastapi import HTTPException

    u = _make_user(UserRole.recruiter, ["recruiter"])
    dep = require_roles(UserRole.admin, UserRole.delivery_lead)
    with pytest.raises(HTTPException) as exc:
        await dep(current_user=u)
    assert exc.value.status_code == 403
