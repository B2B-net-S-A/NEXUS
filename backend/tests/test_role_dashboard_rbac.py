"""Focused contracts for role dashboards, capabilities, and session RBAC."""

import pytest
from fastapi import HTTPException

from app.analytics.capabilities import AnalyticsCapability, capabilities_for
from app.api.admin import _acquires_onboarding_role, _normalized_role_values
from app.api.auth import _dashboard_presets_for
from app.api.dashboard import _legacy_organization_dashboard_guard
from app.api.deps import require_onboarded_user, require_roles
from app.api.dynareporter_delivery_lead_dashboard import (
    _require_legacy_team_dashboard_scope,
)
from app.api.financial_access import has_financial_access
from app.api.jobs import (
    _apply_delivery_lead_job_scope,
    _assert_delivery_lead_client_visible,
    _assert_delivery_lead_cross_client_disabled,
    _assert_delivery_lead_finance_write,
    _assert_delivery_lead_job_visible,
    _redact_delivery_lead_job_finance,
)
from app.api.reports import _recruitment_ranking_guard
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    token_authorization_version_matches,
)
from app.models.activity import Activity
from app.models.job import Job
from app.models.user import User, UserRole
from app.services.access_scope import (
    DashboardScope,
    ScopeKind,
    apply_delivery_lead_activity_scope,
    resolve_dashboard_scope,
)
from app.services.access_scope import (
    apply_delivery_lead_client_scope,
    assert_delivery_lead_client_visible,
)
from app.services.onboarding_access import (
    onboarding_persona_changed,
    onboarding_persona_for_roles,
)


def _user(
    role: UserRole,
    *,
    roles: list[str] | None = None,
    profile_completed: bool = True,
) -> User:
    return User(
        id=100,
        email=f"{role.value}@example.com",
        name=role.value,
        role=role,
        roles=roles or [role.value],
        is_active=True,
        profile_completed=profile_completed,
        authorization_version=1,
    )


def test_finance_capabilities_are_exclusive_from_delivery_lead() -> None:
    finance_caps = capabilities_for(_user(UserRole.finance))
    assert {
        AnalyticsCapability.VIEW_FINANCE,
        AnalyticsCapability.MANAGE_FINANCE,
        AnalyticsCapability.VIEW_EXECUTIVE,
    }.issubset(finance_caps)
    assert AnalyticsCapability.APPROVE_FINANCE not in finance_caps
    assert has_financial_access(_user(UserRole.finance))

    delivery_caps = capabilities_for(_user(UserRole.delivery_lead))
    assert AnalyticsCapability.VIEW_FINANCE not in delivery_caps
    assert AnalyticsCapability.MANAGE_FINANCE not in delivery_caps
    assert AnalyticsCapability.APPROVE_FINANCE not in delivery_caps
    assert AnalyticsCapability.VIEW_RECRUITMENT_RANKING not in delivery_caps
    assert not has_financial_access(_user(UserRole.delivery_lead))


def test_admin_is_superadmin_and_legacy_viewer_has_no_dashboard_capability() -> None:
    assert capabilities_for(_user(UserRole.admin)) == frozenset(AnalyticsCapability)
    assert capabilities_for(_user(UserRole.user)) == frozenset()


def test_legacy_organization_wide_delivery_report_rejects_plain_dl() -> None:
    with pytest.raises(HTTPException) as exc:
        _require_legacy_team_dashboard_scope(_user(UserRole.delivery_lead))
    assert exc.value.status_code == 403

    _require_legacy_team_dashboard_scope(_user(UserRole.head_of_recruitment))
    _require_legacy_team_dashboard_scope(_user(UserRole.admin))


@pytest.mark.asyncio
async def test_frozen_legacy_dashboards_are_admin_or_hor_only() -> None:
    for role in (UserRole.admin, UserRole.head_of_recruitment):
        user = _user(role)
        assert await _legacy_organization_dashboard_guard(current_user=user) is user

    for role in (
        UserRole.delivery_lead,
        UserRole.tac,
        UserRole.recruiter,
        UserRole.sourcer,
        UserRole.finance,
        UserRole.user,
    ):
        with pytest.raises(HTTPException) as exc:
            await _legacy_organization_dashboard_guard(current_user=_user(role))
        assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_legacy_recruitment_report_follows_ranking_capability() -> None:
    for role in (
        UserRole.admin,
        UserRole.head_of_recruitment,
        UserRole.tac,
        UserRole.recruiter,
        UserRole.sourcer,
    ):
        user = _user(role)
        assert await _recruitment_ranking_guard(current_user=user) is user

    for role in (UserRole.delivery_lead, UserRole.finance, UserRole.user):
        with pytest.raises(HTTPException) as exc:
            await _recruitment_ranking_guard(current_user=_user(role))
        assert exc.value.status_code == 403

    hybrid = _user(
        UserRole.delivery_lead,
        roles=[UserRole.delivery_lead.value, UserRole.tac.value],
    )
    assert await _recruitment_ranking_guard(current_user=hybrid) is hybrid


def test_finance_role_cannot_be_combined() -> None:
    hybrid = _user(
        UserRole.finance,
        roles=[UserRole.finance.value, UserRole.admin.value],
    )
    with pytest.raises(ValueError, match="finance role cannot be combined"):
        hybrid.ensure_exclusive_roles()

    with pytest.raises(HTTPException) as exc:
        _normalized_role_values(
            UserRole.finance,
            [UserRole.finance, UserRole.delivery_lead],
        )
    assert exc.value.status_code == 422

    viewer_hybrid = _user(
        UserRole.user,
        roles=[UserRole.user.value, UserRole.recruiter.value],
    )
    with pytest.raises(ValueError, match="user role cannot be combined"):
        viewer_hybrid.ensure_exclusive_roles()
    with pytest.raises(HTTPException) as exc:
        _normalized_role_values(
            UserRole.user,
            [UserRole.user, UserRole.recruiter],
        )
    assert exc.value.status_code == 422


def test_runtime_viewer_promotion_requires_role_specific_onboarding() -> None:
    assert _acquires_onboarding_role(["user"], ["recruiter"])
    assert _acquires_onboarding_role(["tac"], ["tac", "delivery_lead"])
    assert not _acquires_onboarding_role(["recruiter"], ["recruiter", "tac"])
    assert not _acquires_onboarding_role(["finance"], ["finance"])
    assert onboarding_persona_changed(
        ["recruiter"],
        ["recruiter", "delivery_lead"],
    )
    assert onboarding_persona_changed(
        ["delivery_lead", "recruiter"],
        ["recruiter"],
    )


def test_onboarding_persona_uses_role_union_with_dl_precedence() -> None:
    assert onboarding_persona_for_roles(["tac", "recruiter"]) is UserRole.recruiter
    assert (
        onboarding_persona_for_roles(["recruiter", "delivery_lead"])
        is UserRole.delivery_lead
    )
    assert onboarding_persona_for_roles(["admin", "delivery_lead"]) is None


def test_dashboard_presets_follow_personas_and_multi_role_union() -> None:
    assert _dashboard_presets_for(_user(UserRole.finance)) == ["finance"]
    assert _dashboard_presets_for(_user(UserRole.head_of_recruitment)) == [
        "head-of-recruitment"
    ]
    hybrid = _user(
        UserRole.delivery_lead,
        roles=[UserRole.delivery_lead.value, UserRole.tac.value],
    )
    assert _dashboard_presets_for(hybrid) == ["delivery-lead", "my-work"]
    assert _dashboard_presets_for(_user(UserRole.admin)) == [
        "admin-ops",
        "delivery-lead",
        "head-of-recruitment",
        "my-work",
        "finance",
    ]


def test_tokens_always_carry_authorization_version() -> None:
    access = decode_token(create_access_token(100, UserRole.finance.value))
    refresh = decode_token(create_refresh_token(100))
    assert access["av"] == 1
    assert refresh["av"] == 1

    bumped = decode_token(
        create_access_token(
            100,
            UserRole.finance.value,
            authorization_version=7,
        )
    )
    assert bumped["av"] == 7
    assert token_authorization_version_matches(bumped, 7)
    assert not token_authorization_version_matches({"av": "7"}, 7)
    assert not token_authorization_version_matches({}, 1)


@pytest.mark.asyncio
async def test_onboarding_gate_and_admin_superadmin_guard() -> None:
    incomplete = _user(UserRole.recruiter, profile_completed=False)
    with pytest.raises(HTTPException) as exc:
        await require_onboarded_user(incomplete)
    assert exc.value.status_code == 403
    assert exc.value.detail == "onboarding_required"

    admin = _user(UserRole.admin)
    finance_guard = require_roles(UserRole.finance)
    assert await finance_guard(current_user=admin) is admin


def test_legacy_job_surface_uses_exact_delivery_scope_and_hides_budget() -> None:
    from sqlalchemy import select

    pairs = frozenset({(10, 100), (20, 200)})
    scoped_sql = str(
        _apply_delivery_lead_job_scope(select(Job), pairs).compile(
            compile_kwargs={"literal_binds": True}
        )
    )
    assert "(jobs.client_id, jobs.tac_id) IN ((10, 100), (20, 200))" in scoped_sql

    empty_sql = str(
        _apply_delivery_lead_job_scope(select(Job), frozenset()).compile(
            compile_kwargs={"literal_binds": True}
        )
    )
    assert "(jobs.client_id, jobs.tac_id) IN ((-1, -1))" in empty_sql

    _assert_delivery_lead_job_visible(Job(client_id=10, tac_id=100), pairs)
    with pytest.raises(HTTPException) as exc:
        _assert_delivery_lead_job_visible(Job(client_id=10, tac_id=200), pairs)
    assert exc.value.status_code == 403
    _assert_delivery_lead_client_visible(10, pairs)
    with pytest.raises(HTTPException) as exc:
        _assert_delivery_lead_client_visible(30, pairs)
    assert exc.value.status_code == 403
    with pytest.raises(HTTPException) as exc:
        _assert_delivery_lead_cross_client_disabled(True, pairs)
    assert exc.value.status_code == 403

    dl_payload = {"salary_min": 100, "salary_max": 200}
    assert _redact_delivery_lead_job_finance(
        dl_payload,
        _user(UserRole.delivery_lead),
    ) == {"salary_min": None, "salary_max": None}

    admin_payload = {"salary_min": 100, "salary_max": 200}
    assert _redact_delivery_lead_job_finance(
        admin_payload,
        _user(UserRole.admin, roles=["admin", "delivery_lead"]),
    ) == {"salary_min": 100, "salary_max": 200}

    with pytest.raises(HTTPException) as exc:
        _assert_delivery_lead_finance_write(
            {"title", "salary_min"},
            _user(UserRole.delivery_lead),
        )
    assert exc.value.status_code == 403
    _assert_delivery_lead_finance_write(
        {"salary_min", "salary_max"},
        _user(UserRole.admin, roles=["admin", "delivery_lead"]),
    )


def test_shared_delivery_client_scope_is_deny_all_when_unassigned() -> None:
    from sqlalchemy import select

    scoped = apply_delivery_lead_client_scope(
        select(Job),
        Job.client_id,
        frozenset({10, 20}),
    )
    rendered = str(scoped.compile(compile_kwargs={"literal_binds": True}))
    assert "jobs.client_id IN (10, 20)" in rendered

    empty = apply_delivery_lead_client_scope(
        select(Job),
        Job.client_id,
        frozenset(),
    )
    empty_rendered = str(empty.compile(compile_kwargs={"literal_binds": True}))
    assert "jobs.client_id IN (-1)" in empty_rendered

    assert_delivery_lead_client_visible(10, frozenset({10, 20}))
    with pytest.raises(HTTPException) as exc:
        assert_delivery_lead_client_visible(30, frozenset({10, 20}))
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_organization_and_self_scopes_are_deterministic() -> None:
    finance = _user(UserRole.finance)
    organization = await resolve_dashboard_scope(finance, db=None)  # type: ignore[arg-type]
    assert organization.kind is ScopeKind.organization
    assert organization.as_payload() == {
        "kind": "organization",
        "user_id": 100,
        "allowed_client_ids": [],
        "allowed_tac_user_ids": [],
        "allowed_operator_user_ids": [],
        "allowed_client_tac_pairs": [],
    }

    recruiter = _user(UserRole.recruiter)
    own = await resolve_dashboard_scope(recruiter, db=None)  # type: ignore[arg-type]
    assert own.kind is ScopeKind.self
    assert own.allowed_operator_user_ids == frozenset({100})
    assert own.cache_token() == "self:u=100:c=:t=100:o=100:p="


@pytest.mark.asyncio
async def test_delivery_scope_preserves_exact_client_tac_relationships() -> None:
    class _Values:
        def __init__(self, values):
            self._values = values

        def all(self):
            return self._values

    class _Pair:
        def __init__(self, client_id: int, tac_user_id: int):
            self.client_id = client_id
            self.tac_user_id = tac_user_id

    class _Database:
        async def scalars(self, _statement):
            return _Values([10, 20])

        async def execute(self, _statement):
            # Same client/TAC unions as the forbidden cartesian product, but
            # only two of the four relationships are authoritative.
            return _Values([_Pair(10, 101), _Pair(20, 202)])

    delivery_lead = _user(UserRole.delivery_lead)
    scope = await resolve_dashboard_scope(
        delivery_lead,
        _Database(),  # type: ignore[arg-type]
    )

    assert scope.allowed_client_ids == frozenset({10, 20})
    assert scope.allowed_tac_user_ids == frozenset({101, 202})
    assert scope.allowed_client_tac_pairs == frozenset({(10, 101), (20, 202)})
    assert scope.as_payload()["allowed_client_tac_pairs"] == [
        {"client_id": 10, "tac_user_id": 101},
        {"client_id": 20, "tac_user_id": 202},
    ]
    assert scope.cache_token().endswith("p=10-101,20-202")


def test_delivery_activity_feed_uses_exact_pairs_and_only_client_job_entities() -> None:
    from sqlalchemy import select

    scope = DashboardScope(
        kind=ScopeKind.delivery_clients,
        user_id=100,
        allowed_client_ids=frozenset({10, 20}),
        allowed_tac_user_ids=frozenset({101, 202}),
        allowed_client_tac_pairs=frozenset({(10, 101), (20, 202)}),
    )
    scoped_sql = str(
        apply_delivery_lead_activity_scope(select(Activity), scope).compile(
            compile_kwargs={"literal_binds": True}
        )
    )

    assert "activities.entity_type = 'client'" in scoped_sql
    assert "activities.entity_id IN (10, 20)" in scoped_sql
    assert "activities.entity_type = 'job'" in scoped_sql
    assert "(jobs.client_id, jobs.tac_id) IN ((10, 101), (20, 202))" in scoped_sql
    assert "(10, 202)" not in scoped_sql
    assert "(20, 101)" not in scoped_sql


def test_delivery_activity_feed_empty_scope_is_deny_all() -> None:
    from sqlalchemy import select

    scope = DashboardScope(
        kind=ScopeKind.delivery_clients,
        user_id=100,
    )
    scoped_sql = str(
        apply_delivery_lead_activity_scope(select(Activity), scope).compile(
            compile_kwargs={"literal_binds": True}
        )
    )

    assert "activities.entity_id IN (-1)" in scoped_sql
    assert "(jobs.client_id, jobs.tac_id) IN ((-1, -1))" in scoped_sql
