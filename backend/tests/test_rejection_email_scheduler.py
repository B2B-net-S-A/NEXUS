"""Unit tests for `app.services.rejection_email_scheduler`.

Pure-function tests (no DB, no Graph). Focus:
- trigger_previous_stages correctness (the business rule)
- `_apply()` renderer — simple placeholders, conditional block
- renderer doesn't leak client/company names (only job.title is exposed)
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.models.recruitment_pipeline import PipelineStage
from app.services.rejection_email_scheduler import (
    ACTIVE_OTHER_STAGES_EXCLUDE,
    DELAY_MINUTES,
    MAX_ATTEMPTS,
    TRIGGER_PREVIOUS_STAGES,
    _apply,
    _render,
)


# ── Constants ──────────────────────────────────────────────────────────────


def test_trigger_previous_stages_contains_all_client_visible() -> None:
    """The trigger set must include every stage after which the client has
    seen the candidate — including `cv_sent`, even though STAGE_CATEGORY
    labels it `internal`. This is the core business rule."""
    assert PipelineStage.cv_sent in TRIGGER_PREVIOUS_STAGES
    assert PipelineStage.client_interview in TRIGGER_PREVIOUS_STAGES
    assert PipelineStage.acceptance in TRIGGER_PREVIOUS_STAGES
    assert PipelineStage.negotiation in TRIGGER_PREVIOUS_STAGES
    assert PipelineStage.onboarding in TRIGGER_PREVIOUS_STAGES


def test_trigger_previous_stages_excludes_early_internal() -> None:
    """Early-internal stages must NOT trigger — otherwise we spam candidates
    who were rejected at screening/interview before the client even saw them."""
    for stage in (
        PipelineStage.new,
        PipelineStage.prep_call,
        PipelineStage.screening,
        PipelineStage.interview,
    ):
        assert stage not in TRIGGER_PREVIOUS_STAGES, (
            f"{stage} must not trigger rejection email — too early"
        )


def test_active_other_stages_exclude_terminals() -> None:
    """All terminal stages must be in the exclude-set so they never appear
    as an 'other active process' in the rendered body."""
    assert PipelineStage.rejected in ACTIVE_OTHER_STAGES_EXCLUDE
    assert PipelineStage.withdrawn in ACTIVE_OTHER_STAGES_EXCLUDE
    assert PipelineStage.hired in ACTIVE_OTHER_STAGES_EXCLUDE


def test_delay_is_fifteen_minutes() -> None:
    assert DELAY_MINUTES == 15


def test_max_attempts_is_three() -> None:
    assert MAX_ATTEMPTS == 3


# ── Renderer: _apply() ─────────────────────────────────────────────────────


@pytest.fixture
def ctx() -> dict[str, str]:
    return {
        "candidate_name": "Jan",
        "candidate_lastname": "Kowalski",
        "candidate_full_name": "Jan Kowalski",
        "job_title": "Senior Python Developer",
        "recruiter_name": "Ania",
        "other_processes_count": "2",
        "other_processes_list": "DevOps Lead, Backend Architect",
    }


def test_apply_simple_placeholder_replacement(ctx: dict[str, str]) -> None:
    template = "Hi {{candidate_name}}, role: {{job_title}}"
    rendered = _apply(template, ctx, has_others=False)
    assert rendered == "Hi Jan, role: Senior Python Developer"


def test_apply_strips_if_block_when_no_others(ctx: dict[str, str]) -> None:
    template = (
        "Hello {{candidate_name}}. "
        "{{#if other_processes}}You have {{other_processes_count}} others.{{/if}}"
        " Bye."
    )
    rendered = _apply(template, ctx, has_others=False)
    assert rendered == "Hello Jan.  Bye."
    assert "{{#if" not in rendered
    assert "{{/if}}" not in rendered
    assert "others" not in rendered


def test_apply_keeps_if_block_when_has_others(ctx: dict[str, str]) -> None:
    template = (
        "Hello {{candidate_name}}. "
        "{{#if other_processes}}You have {{other_processes_count}} others: "
        "{{other_processes_list}}.{{/if}} Bye."
    )
    rendered = _apply(template, ctx, has_others=True)
    assert "You have 2 others: DevOps Lead, Backend Architect." in rendered
    assert "{{#if" not in rendered
    assert "{{/if}}" not in rendered


def test_apply_handles_multiline_if_block(ctx: dict[str, str]) -> None:
    template = """Line 1
{{#if other_processes}}
Line 2 — {{other_processes_count}}
Line 3 — {{other_processes_list}}
{{/if}}
Line 4"""
    stripped = _apply(template, ctx, has_others=False)
    assert "Line 2" not in stripped
    assert "Line 3" not in stripped
    assert "Line 1" in stripped and "Line 4" in stripped

    rendered = _apply(template, ctx, has_others=True)
    assert "Line 2 — 2" in rendered
    assert "Line 3 — DevOps Lead, Backend Architect" in rendered


def test_apply_unknown_placeholder_left_intact(ctx: dict[str, str]) -> None:
    """Unknown placeholders stay as-is; easier to spot template bugs than to
    silently drop content."""
    rendered = _apply("{{candidate_name}} + {{unknown_thing}}", ctx, has_others=False)
    assert rendered == "Jan + {{unknown_thing}}"


# ── Renderer: _render() integration ────────────────────────────────────────


def _mk_candidate(name: str = "Jan", lastname: str = "Kowalski") -> SimpleNamespace:
    return SimpleNamespace(name=name, lastname=lastname)


def _mk_job(title: str = "Senior Python Developer") -> SimpleNamespace:
    return SimpleNamespace(title=title)


def _mk_recruiter(name: str = "Anna Nowak", email: str = "anna@co.pl") -> SimpleNamespace:
    return SimpleNamespace(name=name, email=email)


def test_render_uses_default_template_when_none_given() -> None:
    """Renderer falls back to the hard-coded Polish template if no row exists."""
    subject, body = _render(
        template=None,
        candidate=_mk_candidate(),
        job=_mk_job(),
        recruiter=_mk_recruiter(),
        other_processes=[],
    )
    assert "Senior Python Developer" in subject
    assert "Cześć Jan," in body
    # When others=[], the if-block is gone
    assert "innych otwartych procesach" not in body


def test_render_with_others_shows_titles_only() -> None:
    others = [
        {"job_id": 10, "title": "DevOps Lead"},
        {"job_id": 11, "title": "Backend Architect"},
    ]
    _, body = _render(
        template=None,
        candidate=_mk_candidate(),
        job=_mk_job(),
        recruiter=_mk_recruiter(),
        other_processes=others,
    )
    assert "DevOps Lead" in body
    assert "Backend Architect" in body
    assert "2" in body  # other_processes_count
    # Make sure no job_id leaks into the body.
    assert '"job_id"' not in body
    assert "10" not in body  # job_id=10 — hopefully no false-positive
    assert "11" not in body  # job_id=11


def test_render_does_not_expose_client_fields() -> None:
    """Defense-in-depth: even if someone passes client-shaped data, the
    renderer only references job_id and title from each entry. Client names
    must never appear in the body."""
    others = [
        {
            "job_id": 7,
            "title": "Staff Engineer",
            # Even if these keys are present, they must not render.
            "client_name": "Acme Corp SECRET",
            "company": "TopSecret Industries",
        },
    ]
    _, body = _render(
        template=None,
        candidate=_mk_candidate(),
        job=_mk_job(),
        recruiter=_mk_recruiter(),
        other_processes=others,
    )
    assert "Staff Engineer" in body
    assert "Acme Corp SECRET" not in body
    assert "TopSecret Industries" not in body


def test_render_recruiter_fallback_to_email() -> None:
    """If a recruiter row is missing `name`, the renderer uses their email —
    at least the message isn't signed 'None'."""
    _, body = _render(
        template=None,
        candidate=_mk_candidate(),
        job=_mk_job(),
        recruiter=SimpleNamespace(name=None, email="rec@co.pl"),
        other_processes=[],
    )
    assert "rec@co.pl" in body
    assert "None" not in body
