from types import SimpleNamespace

from app.models.user import UserRole
from app.services.action_permissions import (
    DEFAULT_ROLE_ACTION_ACCESS,
    ActionAccess,
    ProductAction,
    action_access_for_roles,
    action_access_for_user,
    base_action_policy_from_rows,
    effective_action_policy_from_rows,
)


ACTION = ProductAction.b2b_contract_generator


def _user(*roles: UserRole):
    role_set = set(roles)
    return SimpleNamespace(
        id=17,
        get_all_roles=lambda: role_set,
        has_role=lambda role: role in role_set,
    )


def test_action_matrix_is_closed_over_every_role_and_action() -> None:
    assert set(DEFAULT_ROLE_ACTION_ACCESS) == set(UserRole)
    for policy in DEFAULT_ROLE_ACTION_ACCESS.values():
        assert set(policy) == set(ProductAction)


def test_generator_defaults_preserve_operators_and_keep_tcm_view_only() -> None:
    for role in (
        UserRole.admin,
        UserRole.finance,
        UserRole.head_of_recruitment,
        UserRole.delivery_lead,
        UserRole.tac,
        UserRole.recruiter,
        UserRole.sourcer,
    ):
        assert action_access_for_roles([role], ACTION) is ActionAccess.manage

    assert (
        action_access_for_roles([UserRole.talent_community_manager], ACTION)
        is ActionAccess.view
    )
    assert action_access_for_roles([UserRole.user], ACTION) is ActionAccess.view


def test_multi_role_union_uses_strongest_action_access() -> None:
    assert (
        action_access_for_roles(
            [UserRole.talent_community_manager, UserRole.recruiter], ACTION
        )
        is ActionAccess.manage
    )


def test_persisted_role_union_and_user_override_replace_the_base() -> None:
    user = _user(UserRole.talent_community_manager, UserRole.user)
    role_rows = [
        SimpleNamespace(
            role="talent_community_manager",
            action=ACTION.value,
            access="view",
        ),
        SimpleNamespace(role="user", action=ACTION.value, access="view"),
    ]
    assert (
        base_action_policy_from_rows(user.get_all_roles(), role_rows)[ACTION]
        is ActionAccess.view
    )

    overrides = [
        SimpleNamespace(user_id=user.id, action=ACTION.value, access="generate")
    ]
    assert (
        effective_action_policy_from_rows(user, role_rows, overrides)[ACTION]
        is ActionAccess.generate
    )

    overrides[0].access = "none"
    assert (
        effective_action_policy_from_rows(user, role_rows, overrides)[ACTION]
        is ActionAccess.none
    )


def test_missing_or_corrupt_persisted_rows_fail_closed() -> None:
    user = _user(UserRole.recruiter)
    assert (
        base_action_policy_from_rows(user.get_all_roles(), [])[ACTION]
        is ActionAccess.none
    )

    corrupt = [SimpleNamespace(role="recruiter", action=ACTION.value, access="root")]
    assert (
        base_action_policy_from_rows(user.get_all_roles(), corrupt)[ACTION]
        is ActionAccess.none
    )


def test_request_snapshot_wins_over_bootstrap_role_default() -> None:
    user = _user(UserRole.recruiter)
    user.effective_action_access = {ACTION.value: "generate"}
    assert action_access_for_user(user, ACTION) is ActionAccess.generate

    user.effective_action_access = {ACTION.value: "unexpected"}
    assert action_access_for_user(user, ACTION) is ActionAccess.none
