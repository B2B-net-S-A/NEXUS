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

from app.api.deps import _viewer_request_is_allowed, require_roles
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


@pytest.mark.parametrize("role", list(UserRole))
def test_viewer_write_backstop_covers_all_seven_roles(role: UserRole):
    user = _make_user(role)

    allowed = _viewer_request_is_allowed(user, "POST", "/api/contacts")

    assert allowed is (role is not UserRole.user)


def test_viewer_write_backstop_honours_valid_secondary_role():
    user = _make_user(UserRole.user, ["user", "recruiter"])

    assert _viewer_request_is_allowed(user, "POST", "/api/contacts") is True


def test_unknown_secondary_role_never_upgrades_viewer():
    user = _make_user(UserRole.user, ["user", "removed_role"])

    assert _viewer_request_is_allowed(user, "POST", "/api/contacts") is False


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_viewer_rejects_every_unsafe_method_by_default(method: str):
    user = _make_user(UserRole.user)

    assert _viewer_request_is_allowed(user, method, "/api/legacy-unclassified") is False


def test_viewer_can_only_mutate_explicit_personal_state():
    user = _make_user(UserRole.user)

    assert (
        _viewer_request_is_allowed(user, "POST", "/api/auth/change-password")
        is True
    )
    assert (
        _viewer_request_is_allowed(user, "PATCH", "/api/users/me/preferences")
        is True
    )
    assert _viewer_request_is_allowed(user, "POST", "/api/candidates") is False


def test_viewer_search_allowlist_is_exact_and_future_mutators_fail_closed():
    user = _make_user(UserRole.user)

    assert _viewer_request_is_allowed(user, "POST", "/api/search/candidates") is True
    assert _viewer_request_is_allowed(user, "POST", "/api/search/semantic") is True
    assert _viewer_request_is_allowed(user, "POST", "/api/search/reindex") is False
