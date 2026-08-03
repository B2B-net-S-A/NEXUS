"""Contract tests for the role-cutover compatibility test harness."""

from app.models.user import User, UserRole
from tests._user_fixture_compat import normalise_omitted_user_rollout_fields


def _user(label: str, role: UserRole, **overrides: object) -> User:
    return User(
        email=f"{label}@example.com",
        name=label,
        role=role,
        **overrides,
    )


def test_omitted_rollout_fields_model_an_established_account() -> None:
    legacy_viewer = _user("legacy-viewer", UserRole.user)
    recruiter = _user("established-recruiter", UserRole.recruiter)

    normalise_omitted_user_rollout_fields([legacy_viewer, recruiter])

    assert legacy_viewer.profile_completed is True
    assert legacy_viewer.roles == [UserRole.user.value]
    assert recruiter.profile_completed is True
    assert recruiter.roles == [UserRole.recruiter.value]


def test_explicit_onboarding_and_role_states_are_never_overwritten() -> None:
    incomplete = _user(
        "incomplete",
        UserRole.recruiter,
        profile_completed=False,
        roles=[],
    )
    hybrid = _user(
        "hybrid",
        UserRole.delivery_lead,
        profile_completed=False,
        roles=[UserRole.delivery_lead.value, UserRole.tac.value],
    )
    malformed_viewer_hybrid = _user(
        "malformed-viewer-hybrid",
        UserRole.user,
        profile_completed=False,
        roles=[UserRole.user.value, UserRole.recruiter.value],
    )

    normalise_omitted_user_rollout_fields([incomplete, hybrid, malformed_viewer_hybrid])

    assert incomplete.profile_completed is False
    assert incomplete.roles == []
    assert hybrid.profile_completed is False
    assert hybrid.roles == [UserRole.delivery_lead.value, UserRole.tac.value]
    assert malformed_viewer_hybrid.profile_completed is False
    assert malformed_viewer_hybrid.roles == [
        UserRole.user.value,
        UserRole.recruiter.value,
    ]
