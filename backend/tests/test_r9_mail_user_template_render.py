"""Runda 9: render szablonów użytkownika (R9-N10-6, R9-N10-7, R9-N10-11)."""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from jinja2 import TemplateError

from app.api import user_email_templates as uet
from app.models.user import UserRole


def _render(env, source: str, ctx: dict | None = None) -> str:
    return asyncio.run(uet._render_in_thread(env, source, ctx or {}))


def test_subject_is_not_html_escaped():
    ctx = {"job": {"title": "R&D <Lead>"}}
    assert _render(uet._subject_env, "Rola: {{ job.title }}", ctx) == "Rola: R&D <Lead>"


def test_body_stays_html_escaped():
    ctx = {"job": {"title": "R&D <Lead>"}}
    assert _render(uet._jinja_env, "<p>{{ job.title }}</p>", ctx) == (
        "<p>R&amp;D &lt;Lead&gt;</p>"
    )


def test_none_still_renders_as_empty_in_both_envs():
    ctx = {"candidate": {"phone": None}}
    assert _render(uet._subject_env, "[{{ candidate.phone }}]", ctx) == "[]"
    assert _render(uet._jinja_env, "[{{ candidate.phone }}]", ctx) == "[]"


def test_nested_ranges_are_stopped_by_the_deadline(monkeypatch):
    monkeypatch.setattr(uet, "_RENDER_DEADLINE_SECONDS", 0.3)
    source = (
        "{% for a in range(100000) %}{% for b in range(100000) %}"
        "{% endfor %}{% endfor %}"
    )
    start = time.monotonic()
    with pytest.raises(TemplateError):
        _render(uet._jinja_env, source)
    assert time.monotonic() - start < 3


def test_huge_power_is_refused_before_computing():
    start = time.monotonic()
    with pytest.raises(TemplateError):
        _render(uet._jinja_env, "{{ 10 ** 1000000 }}")
    assert time.monotonic() - start < 1


def test_huge_string_repeat_is_refused():
    with pytest.raises(TemplateError):
        _render(uet._jinja_env, "{{ 'x' * 100000000 }}")


def test_huge_filter_argument_is_refused():
    with pytest.raises(TemplateError):
        _render(uet._jinja_env, "{{ 'x' | center(1000000000) }}")


def test_output_length_is_capped():
    with pytest.raises(TemplateError):
        _render(uet._jinja_env, "{% for i in range(20000) %}{{ 'y' * 50 }}{% endfor %}")


def test_ordinary_arithmetic_and_filters_still_work():
    out = _render(
        uet._jinja_env,
        "{{ 2 ** 10 }} {{ 3 * 4 }} {{ 'ab' * 2 }} {{ name | upper }} "
        "{% for i in range(3) %}{{ i }}{% endfor %}",
        {"name": "anna"},
    )
    assert out == "1024 12 abab ANNA 012"


def test_tracer_is_restored_after_render():
    import sys

    before = sys.gettrace()
    _render(uet._jinja_env, "ok")
    assert sys.gettrace() is before


def _user(*roles: UserRole):
    return SimpleNamespace(has_any_role=lambda *wanted: bool(set(roles) & set(wanted)))


def test_recruiter_cannot_publish_shared_template():
    with pytest.raises(HTTPException) as exc:
        uet._assert_can_share(_user(UserRole.recruiter))
    assert exc.value.status_code == 403


@pytest.mark.parametrize(
    "role", [UserRole.admin, UserRole.head_of_recruitment, UserRole.delivery_lead]
)
def test_template_authors_can_publish_shared_template(role):
    uet._assert_can_share(_user(role))


def test_create_route_requires_candidate_write_access():
    import inspect

    annotation = inspect.signature(uet.create_template).parameters[
        "current_user"
    ].annotation
    assert "CandidateWriteAccess" in str(annotation)
