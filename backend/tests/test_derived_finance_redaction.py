"""Regression coverage for salary redaction on derived recruitment surfaces.

These tests are intentionally host-native and database-free.  Integration
coverage for the underlying role/client assignment tables lives in the
dashboard RBAC suite; this file protects the projections and the presence of
the exact Delivery Lead scope calls in endpoints that historically leaked a
job budget indirectly.
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.candidate_access import require_candidate_read, require_candidate_write
from app.api.phase3_actions import (
    _format_jobs_html,
    prepare_client_proposal,
    send_candidate_shortlist_email,
)
from app.api.prep_kit import _salary_info_for_overview, generate_prep_kit
from app.api.recommendations import (
    _assert_salary_filter_access,
    _score_breakdown_payload,
    _shape_recommended_job,
    _shape_seek_job,
    recommend_jobs_for_candidate,
    seeking_contractors,
)
from app.api.user_email_templates import _job_ctx, render_template
from app.models.user import User, UserRole


def _job() -> SimpleNamespace:
    return SimpleNamespace(
        id=101,
        title="Senior Python Engineer",
        client_id=77,
        client=SimpleNamespace(name="Scoped Client"),
        location="Warszawa",
        salary_min=18_000,
        salary_max=24_000,
        remote_policy=None,
        status=None,
        priority=None,
        seniority=None,
        industry="IT",
        deadline=None,
    )


def _user(role: UserRole) -> User:
    return User(
        id=1,
        email=f"{role.value}@example.com",
        name=role.value,
        role=role,
        roles=[role.value],
        is_active=True,
        profile_completed=True,
    )


def test_prep_overview_salary_requires_explicit_finance_capability() -> None:
    job = _job()

    assert _salary_info_for_overview(job) == ""
    assert "18,000" in _salary_info_for_overview(job, include_finance=True)
    assert "24,000" in _salary_info_for_overview(job, include_finance=True)


def test_recommendation_job_shapes_keep_contract_but_redact_salary() -> None:
    job = _job()

    for shape in (_shape_recommended_job(job), _shape_seek_job(job)):
        assert shape["id"] == job.id
        assert shape["title"] == job.title
        assert shape["salary_min"] is None
        assert shape["salary_max"] is None

    finance_shape = _shape_recommended_job(job, include_finance=True)
    assert finance_shape["salary_min"] == 18_000
    assert finance_shape["salary_max"] == 24_000


def test_score_breakdown_salary_layer_is_not_a_budget_oracle() -> None:
    breakdown = SimpleNamespace(
        as_dict=lambda: {
            "total": 80.0,
            "salary": {
                "points": 13.0,
                "max": 15.0,
                "reason": "budget overlap",
                "status": "scored",
            },
        }
    )

    redacted = _score_breakdown_payload(breakdown)
    assert redacted["salary"] == {
        "points": None,
        "max": None,
        "reason": None,
        "status": "redacted",
    }

    finance = _score_breakdown_payload(breakdown, include_finance=True)
    assert finance["salary"]["reason"] == "budget overlap"


def test_non_finance_user_cannot_probe_hidden_budget_with_filters() -> None:
    delivery_lead = _user(UserRole.delivery_lead)
    admin = _user(UserRole.admin)

    _assert_salary_filter_access(
        delivery_lead,
        salary_min=None,
        salary_max=None,
    )
    with pytest.raises(HTTPException) as exc:
        _assert_salary_filter_access(
            delivery_lead,
            salary_min=20_000,
            salary_max=None,
        )
    assert exc.value.status_code == 403

    _assert_salary_filter_access(
        admin,
        salary_min=20_000,
        salary_max=25_000,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("guard", [require_candidate_read, require_candidate_write])
async def test_finance_role_passes_candidate_guards(guard) -> None:
    # Od 19.08 finance ma pelny dostep operacyjny (decyzja produktowa) —
    # dawna granica "finance nie przekracza PII kandydatow" zdjeta; redakcje
    # per-permission (VIEW_FINANCE) pozostaja niezalezna osia.
    user = _user(UserRole.finance)
    assert await guard(user) is user


def test_shortlist_html_and_template_context_redact_salary_by_default() -> None:
    job = _job()

    html = _format_jobs_html([job])
    assert "18,000" not in html
    assert "24,000" not in html
    assert "💰" not in html
    assert "18,000" in _format_jobs_html([job], include_finance=True)

    context = _job_ctx(job)
    assert context["salary_min"] is None
    assert context["salary_max"] is None
    finance_context = _job_ctx(job, include_finance=True)
    assert finance_context["salary_min"] == 18_000
    assert finance_context["salary_max"] == 24_000


@pytest.mark.parametrize(
    ("handler", "required_names"),
    [
        (
            generate_prep_kit,
            (
                "resolve_delivery_lead_client_ids",
                "assert_delivery_lead_client_visible",
            ),
        ),
        (
            recommend_jobs_for_candidate,
            (
                "resolve_delivery_lead_client_ids",
                "apply_delivery_lead_client_scope",
            ),
        ),
        (
            seeking_contractors,
            (
                "resolve_delivery_lead_client_ids",
                "apply_delivery_lead_client_scope",
                "_assert_salary_filter_access",
            ),
        ),
        (
            send_candidate_shortlist_email,
            (
                "resolve_delivery_lead_client_ids",
                "assert_delivery_lead_client_visible",
            ),
        ),
        (
            prepare_client_proposal,
            (
                "resolve_delivery_lead_client_ids",
                "assert_delivery_lead_client_visible",
            ),
        ),
        (
            render_template,
            (
                "resolve_delivery_lead_client_ids",
                "assert_delivery_lead_client_visible",
            ),
        ),
    ],
)
def test_derived_surface_keeps_authoritative_delivery_lead_scope(
    handler,
    required_names: tuple[str, ...],
) -> None:
    source = inspect.getsource(handler)
    for required_name in required_names:
        assert required_name in source
