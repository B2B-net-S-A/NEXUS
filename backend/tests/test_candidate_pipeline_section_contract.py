"""Structural contract for configurable candidate/pipeline section ceilings.

The panel can only be authoritative if legacy role-gated routes also consult
the request-local section snapshot.  Keep this focused on the parallel API
surfaces that historically lived outside the main candidates/pipeline routers.
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest

from app.services.section_permissions import ProductSection, SectionAccess
from tests._route_introspection import iter_api_routes


def _route(path: str, method: str) -> Any:
    from app.main import app

    for registered_path, route in iter_api_routes(app):
        if registered_path == path and method in (
            getattr(route, "methods", None) or ()
        ):
            return route
    raise AssertionError(f"route not registered: {method} {path}")


def _dependency_calls(route: Any) -> list[Any]:
    calls: list[Any] = []
    stack = [route.dependant]
    seen: set[int] = set()
    while stack:
        dependant = stack.pop()
        if dependant is None or id(dependant) in seen:
            continue
        seen.add(id(dependant))
        if dependant.call is not None:
            calls.append(dependant.call)
        stack.extend(dependant.dependencies or ())
    return calls


def _candidate_access_levels(route: Any) -> set[SectionAccess]:
    levels: set[SectionAccess] = set()
    for call in _dependency_calls(route):
        qualname = getattr(call, "__qualname__", "")
        if "require_candidate_roles" not in qualname:
            continue
        levels.add(inspect.getclosurevars(call).nonlocals["required_access"])
    return levels


def _section_dependencies(route: Any) -> set[ProductSection]:
    sections: set[ProductSection] = set()
    for call in _dependency_calls(route):
        qualname = getattr(call, "__qualname__", "")
        if "require_section_access" not in qualname:
            continue
        sections.add(inspect.getclosurevars(call).nonlocals["section"])
    return sections


@pytest.mark.parametrize(
    ("method", "path"),
    (
        ("POST", "/api/search/candidates"),
        ("POST", "/api/recommendations/cv-upload-preview"),
        ("POST", "/api/jobs/{job_id}/generate-criteria-preview"),
        ("POST", "/api/prep-kit/generate"),
        ("POST", "/api/email-templates/{template_id}/preview"),
    ),
)
def test_read_only_posts_require_candidate_read_not_write(
    method: str, path: str
) -> None:
    assert _candidate_access_levels(_route(path, method)) == {SectionAccess.read}


@pytest.mark.parametrize(
    ("method", "path"),
    (
        ("POST", "/api/candidates/stages/{stage_id}/cv/original/refresh"),
        ("POST", "/api/cv-generator/generate"),
        ("POST", "/api/candidates/{candidate_id}/emails/compose"),
        ("POST", "/api/calls"),
        ("POST", "/api/saved-searches"),
    ),
)
def test_candidate_mutations_require_candidate_write(method: str, path: str) -> None:
    assert SectionAccess.write in _candidate_access_levels(_route(path, method))


@pytest.mark.parametrize(
    ("method", "path"),
    (
        ("GET", "/api/pipeline-stages/{stage_def_id}/scorecard"),
        ("GET", "/api/interview-questions"),
        ("GET", "/api/pipeline-templates"),
        ("GET", "/api/invite-links"),
        ("GET", "/api/jobs/{job_id}/proposals/latest"),
        ("POST", "/api/jobs/{job_id}/proposals/regenerate"),
        ("GET", "/api/jobs/{job_id}/assignable-stages"),
        ("POST", "/api/jobs/{job_id}/proposals/bulk"),
        ("GET", "/api/jobs/{job_id}/shortlist"),
        ("POST", "/api/jobs/{job_id}/shortlist"),
        ("PATCH", "/api/shortlist/{entry_id}"),
        ("DELETE", "/api/shortlist/{entry_id}"),
        ("POST", "/api/shortlist/{entry_id}/promote"),
        ("GET", "/api/champion-suggestions/{suggestion_id}"),
        ("POST", "/api/champion-suggestions/{suggestion_id}/apply"),
        ("POST", "/api/ai/generate-job-description"),
        ("POST", "/api/ai/generate-job"),
        ("POST", "/api/jobs/{job_id}/refresh-criteria"),
        ("POST", "/api/jobs/{job_id}/recompute-scores"),
        ("POST", "/api/candidates/{candidate_id}/assign-to-job/{job_id}"),
    ),
)
def test_pipeline_only_routers_have_pipeline_section_ceiling(
    method: str, path: str
) -> None:
    assert ProductSection.pipeline in _section_dependencies(_route(path, method))


@pytest.mark.parametrize(
    ("method", "path"),
    (
        ("GET", "/api/b2b-generator/roles"),
        ("POST", "/api/b2b-generator/generate"),
    ),
)
def test_b2b_generator_has_sourcing_section_ceiling(method: str, path: str) -> None:
    assert ProductSection.sourcing in _section_dependencies(_route(path, method))


@pytest.mark.parametrize(
    ("method", "path"),
    (
        ("GET", "/api/competitions/current"),
        ("GET", "/api/competitions/monthly-races"),
        ("GET", "/api/competitions/history"),
        ("GET", "/api/competitions/my-position"),
        ("POST", "/api/competitions/freeze"),
    ),
)
def test_competitions_have_insights_section_ceiling(method: str, path: str) -> None:
    assert ProductSection.insights in _section_dependencies(_route(path, method))


@pytest.mark.parametrize(
    ("method", "path"),
    (
        ("POST", "/api/calls/webhook"),
        ("GET", "/api/public/cv/{token}"),
        ("GET", "/api/public/apply/{token}"),
        ("POST", "/api/public/apply/{token}"),
    ),
)
def test_webhook_and_public_token_routes_remain_without_user_rbac(
    method: str, path: str
) -> None:
    qualnames = {
        getattr(call, "__qualname__", "")
        for call in _dependency_calls(_route(path, method))
    }
    assert not any("get_current_user" in name for name in qualnames)
    assert not any("require_candidate_roles" in name for name in qualnames)
    assert not any("require_section_access" in name for name in qualnames)
