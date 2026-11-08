"""Kto oznacza ogłoszenie jako wiszące na portalu (decyzja Artura 08.11.2026)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.models.user import UserRole
from app.services.job_ad.publications import can_mark


def _user(user_id: int, *roles: UserRole):
    return SimpleNamespace(
        id=user_id, has_any_role=lambda *wanted: bool(set(wanted) & set(roles))
    )


JOB = SimpleNamespace(delivery_lead_id=7)


def test_delivery_lead_of_the_job_can_mark():
    assert can_mark(_user(7, UserRole.delivery_lead), JOB)


@pytest.mark.parametrize("role", [UserRole.admin, UserRole.head_of_recruitment])
def test_head_of_recruitment_and_admin_can_mark(role):
    assert can_mark(_user(1, role), JOB)


@pytest.mark.parametrize(
    "role",
    [UserRole.recruiter, UserRole.delivery_lead, UserRole.talent_community_manager],
)
def test_others_cannot_mark(role):
    """Także Delivery Lead innej rekrutacji — jak przy publikacji przez API."""
    assert not can_mark(_user(1, role), JOB)


def test_job_without_lead_stays_closed_for_a_recruiter():
    job = SimpleNamespace(delivery_lead_id=None)
    assert not can_mark(_user(1, UserRole.recruiter), job)
