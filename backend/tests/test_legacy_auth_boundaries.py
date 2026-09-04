"""Pure regression contracts for onboarding, chat and legacy session guards."""

from __future__ import annotations

import inspect
from typing import get_args, get_type_hints
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from fastapi.params import Depends as DependsParam
from sqlalchemy.dialects import postgresql

from app.analytics.capabilities import AnalyticsCapability, require_capability
from app.api import auth, candidate_chat, job_chat, onboarding
from app.api.candidate_access import (
    CandidatePIIAccess,
    CandidateWriteAccess,
    user_can_access_candidate_domain,
)
from app.api.deps import (
    CurrentUser,
    ensure_onboarding_complete,
    get_authenticated_user,
    get_current_user,
    require_dl_assigned_or_admin,
)
from app.api.dynareporter_admin_users import ToggleActivePayload, toggle_active
from app.models.user import User, UserRole
from app.services.access_scope import DashboardScope, ScopeKind
from app.services.candidate_membership import is_member_of_candidate_chat
from app.services.job_membership import is_member_of_job
from app.services.mention_parser import parse_mentions_global
from app.tasks.chat_email_fallback import _eligible_chat_email_recipient


def _user(
    role: UserRole,
    *,
    roles: list[str] | None = None,
    active: bool = True,
    completed: bool = True,
) -> User:
    return User(
        id=11,
        email=f"{role.value}@example.com",
        name=role.value,
        role=role,
        roles=roles or [role.value],
        is_active=active,
        profile_completed=completed,
        authorization_version=1,
    )


def _annotated_dependency(annotation: object):
    assert get_args(annotation), f"expected Annotated dependency, got {annotation!r}"
    for metadata in get_args(annotation)[1:]:
        if isinstance(metadata, DependsParam):
            return metadata.dependency
    raise AssertionError(f"no Depends metadata in {annotation!r}")


def test_only_profile_recovery_routes_use_raw_pre_onboarding_auth() -> None:
    assert _annotated_dependency(CurrentUser) is get_current_user
    for handler in (auth.me, auth.change_password):
        annotation = get_type_hints(handler, include_extras=True)["current_user"]
        assert _annotated_dependency(annotation) is get_authenticated_user
    assert (
        _annotated_dependency(onboarding.OnboardingUser)
        is onboarding.require_onboarding_user
    )
    onboarding_auth = get_type_hints(
        onboarding.require_onboarding_user,
        include_extras=True,
    )["current_user"]
    assert _annotated_dependency(onboarding_auth) is get_authenticated_user
    for handler in (
        onboarding.list_onboarding_jobs,
        onboarding.complete_onboarding,
    ):
        annotation = get_type_hints(handler, include_extras=True)["current_user"]
        assert _annotated_dependency(annotation) is onboarding.require_onboarding_user


def test_direct_and_factory_domain_dependencies_use_global_boundary() -> None:
    capability_guard = require_capability(
        AnalyticsCapability.VIEW_OPERATIONAL_AGGREGATES
    )
    assert (
        inspect.signature(capability_guard)
        .parameters["current_user"]
        .default.dependency
        is get_current_user
    )
    assert (
        _annotated_dependency(
            get_type_hints(
                require_dl_assigned_or_admin,
                include_extras=True,
            )["current_user"]
        )
        is get_current_user
    )


@pytest.mark.parametrize("role", [UserRole.delivery_lead, UserRole.recruiter])
def test_incomplete_primary_onboarding_personas_are_blocked(role: UserRole) -> None:
    with pytest.raises(HTTPException, match="onboarding_required"):
        ensure_onboarding_complete(_user(role, completed=False))


def test_secondary_role_onboarding_prefers_dl_and_admin_is_exempt() -> None:
    secondary_dl = _user(
        UserRole.tac,
        roles=[UserRole.tac.value, UserRole.delivery_lead.value],
        completed=False,
    )
    with pytest.raises(HTTPException) as exc:
        ensure_onboarding_complete(secondary_dl)
    assert exc.value.detail == "onboarding_required"

    admin_hybrid = _user(
        UserRole.admin,
        roles=[UserRole.admin.value, UserRole.delivery_lead.value],
        completed=False,
    )
    assert ensure_onboarding_complete(admin_hybrid) is admin_hybrid


def test_invalid_finance_or_viewer_hybrid_fails_before_domain_access() -> None:
    for exclusive in (UserRole.finance, UserRole.user):
        malformed = _user(
            exclusive,
            roles=[exclusive.value, UserRole.recruiter.value],
        )
        with pytest.raises(HTTPException) as exc:
            ensure_onboarding_complete(malformed)
        assert exc.value.detail == "invalid_exclusive_role_configuration"


@pytest.mark.asyncio
async def test_dl_onboarding_jobs_use_all_clients_regardless_of_tac(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = DashboardScope(
        kind=ScopeKind.delivery_clients,
        user_id=11,
        allowed_client_ids=frozenset({10, 20}),
        allowed_tac_user_ids=frozenset({101, 202}),
        allowed_client_tac_pairs=frozenset({(10, 101), (20, 202)}),
    )
    monkeypatch.setattr(
        onboarding,
        "resolve_dashboard_scope",
        AsyncMock(return_value=scope),
    )

    query = await onboarding._scoped_onboarding_jobs_query(
        AsyncMock(),
        _user(UserRole.delivery_lead, completed=False),
        UserRole.delivery_lead,
    )
    sql = " ".join(
        str(
            query.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        ).split()
    )

    assert "jobs.client_id IN (10, 20)" in sql
    where_sql = sql.partition(" WHERE ")[2]
    assert "jobs.tac_id" not in where_sql
    assert "jobs.status = 'published'" in sql


@pytest.mark.asyncio
async def test_recruiter_onboarding_jobs_reuse_job_membership_policy() -> None:
    query = await onboarding._scoped_onboarding_jobs_query(
        AsyncMock(),
        _user(UserRole.recruiter, completed=False),
        UserRole.recruiter,
    )
    sql = " ".join(
        str(
            query.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        ).split()
    )

    assert "jobs.recruiter_id = 11" in sql
    assert "jobs.delivery_lead_id = 11" in sql
    assert "jobs.tac_id = 11" in sql
    assert "job_collaborators.user_id = 11" in sql
    assert "jobs.status = 'published'" in sql


@pytest.mark.asyncio
async def test_onboarding_write_rejects_any_id_missing_from_read_scope() -> None:
    result = MagicMock()
    result.scalars.return_value.all.return_value = [MagicMock(id=7)]
    db = AsyncMock()
    db.execute.return_value = result

    with pytest.raises(HTTPException) as exc:
        await onboarding._load_selected_scoped_jobs(
            db,
            _user(UserRole.recruiter, completed=False),
            UserRole.recruiter,
            [7, 8],
        )

    assert exc.value.status_code == 403
    assert exc.value.detail == ("One or more selected jobs is outside onboarding scope")


def test_chat_email_fallback_rechecks_current_role_and_activity() -> None:
    assert _eligible_chat_email_recipient(_user(UserRole.recruiter))
    # Finance ma pełny dostęp operacyjny od 19.08 (decyzja produktowa) —
    # kwalifikuje się do maili czatu jak pozostałe role operacyjne.
    assert _eligible_chat_email_recipient(_user(UserRole.finance))
    assert not _eligible_chat_email_recipient(_user(UserRole.user))
    assert _eligible_chat_email_recipient(
        _user(
            UserRole.recruiter,
            roles=[UserRole.recruiter.value, UserRole.finance.value],
        )
    )
    assert not _eligible_chat_email_recipient(_user(UserRole.recruiter, active=False))


# Jedyna wykluczona persona to wycofywany viewer `user` — finance przeszedł
# do ról operacyjnych (19.08) i jest członkiem czatów jak recruiter.
@pytest.mark.parametrize("role", [UserRole.user])
@pytest.mark.asyncio
async def test_chat_membership_rejects_excluded_roles_before_db(
    role: UserRole,
) -> None:
    user = _user(role)
    db = AsyncMock()
    assert not user_can_access_candidate_domain(user)
    assert not await is_member_of_candidate_chat(db, user, candidate_id=7)
    assert not await is_member_of_job(db, user, job_id=8)
    db.get.assert_not_awaited()
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_global_candidate_mentions_exclude_viewer_role_unions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recruiter = _user(UserRole.recruiter)
    recruiter.id = 1
    finance = _user(UserRole.finance)
    finance.id = 2
    viewer = _user(UserRole.user)
    viewer.id = 3
    malformed_finance_admin = _user(
        UserRole.finance,
        roles=[UserRole.finance.value, UserRole.admin.value],
    )
    malformed_finance_admin.id = 4

    result = MagicMock()
    result.scalars.return_value.all.return_value = [
        recruiter,
        finance,
        viewer,
        malformed_finance_admin,
    ]
    db = AsyncMock()
    db.execute.return_value = result
    # This unit exercises the legacy role-union guard only. Runtime policy
    # resolution has its own DB-backed tests; avoid turning this fixture into a
    # partial mock of the role/override tables.
    monkeypatch.setattr(
        "app.services.mention_parser.resolve_effective_section_access_for_users",
        AsyncMock(),
    )

    # Finance (2) i hybryda finance+admin (4) wchodzą od 19.08 — wykluczony
    # zostaje wyłącznie viewer `user` (3).
    assert await parse_mentions_global(db, "@1 @2 @3 @4") == [1, 2, 4]


def test_all_chat_routes_declare_candidate_read_or_write_guards() -> None:
    read_handlers = (
        candidate_chat.list_messages,
        candidate_chat.list_pinned,
        candidate_chat.mark_read,
        candidate_chat.unread_count,
        candidate_chat.list_members,
        candidate_chat.message_read_by,
        job_chat.list_messages,
        job_chat.list_pinned,
        job_chat.mark_read,
        job_chat.unread_count,
        job_chat.list_members,
        job_chat.message_read_by,
    )
    write_handlers = (
        candidate_chat.create_message,
        candidate_chat.edit_message,
        candidate_chat.delete_message,
        candidate_chat.add_reaction,
        candidate_chat.remove_reaction,
        job_chat.create_message,
        job_chat.edit_message,
        job_chat.delete_message,
        job_chat.add_reaction,
        job_chat.remove_reaction,
    )
    for handler in read_handlers:
        assert (
            get_type_hints(handler, include_extras=True)["current_user"]
            == CandidatePIIAccess
        )
    for handler in write_handlers:
        assert (
            get_type_hints(handler, include_extras=True)["current_user"]
            == CandidateWriteAccess
        )


@pytest.mark.asyncio
async def test_legacy_active_toggle_is_atomic_and_noop_safe() -> None:
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db = AsyncMock()
    db.execute.return_value = result

    response = await toggle_active(
        user_id=42,
        payload=ToggleActivePayload(is_active=False),
        current_user=_user(UserRole.admin),
        db=db,
    )

    statement, params = db.execute.await_args.args
    sql = " ".join(str(statement).split())
    assert "authorization_version = authorization_version + 1" in sql
    assert "tokens_valid_after = CURRENT_TIMESTAMP" in sql
    assert "is_active IS DISTINCT FROM :a" in sql
    assert params == {"a": False, "uid": 42}
    db.commit.assert_awaited_once()
    assert response == {"ok": True, "is_active": False}
