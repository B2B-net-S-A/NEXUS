import hashlib
import json
import pytest
from fastapi import HTTPException
from app.services.cv_editor_rules import check_editor_rules
from app.services.html_sanitizer import sanitize_cv_html

HTML = '<h2 data-cv-section="why_points">Summary</h2><ul><li>A</li><li>B</li></ul><h2 data-cv-section="experience">Experience</h2><p data-cv-section="role">Engineer</p><ul><li>Python API</li><li>SQL</li></ul><p data-cv-section="role">Developer</p><ul><li>Java</li></ul>'


def metadata(rule):
    return {
        "client_rule_snapshot_status": "verified",
        "client_rule_snapshot": rule,
        "client_rule_snapshot_sha256": hashlib.sha256(
            json.dumps(
                rule, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest(),
    }


@pytest.mark.parametrize(
    "rule",
    [
        {"max_roles": 1},
        {"max_bullets_per_role": 1},
        {"max_bullet_chars": 3},
        {"why_points_max": 1},
        {"omit_sections": ["experience"]},
    ],
)
def test_client_limits_reject_edited_document(rule):
    with pytest.raises(HTTPException) as exc:
        check_editor_rules(sanitize_cv_html(HTML), metadata(rule))
    assert exc.value.status_code == 422


def test_supported_limits_pass_without_certifying_free_text():
    rule = {
        "max_roles": 2,
        "max_bullets_per_role": 2,
        "max_bullet_chars": 20,
        "why_points_max": 2,
        "generator_instructions": "Private preference",
    }
    report = check_editor_rules(sanitize_cv_html(HTML), metadata(rule))
    assert report["status"] == "needs_review"
    assert set(report["checked_fields"]) == {
        "max_roles",
        "max_bullets_per_role",
        "max_bullet_chars",
        "why_points_max",
    }
    assert report["manual_fields"] == ["generator_instructions"]
    assert "Private preference" not in str(report)


def test_lost_structure_is_not_silently_counted_as_compliant():
    with pytest.raises(HTTPException):
        check_editor_rules(
            "<h2>Experience</h2><p>Engineer</p>", metadata({"max_roles": 1})
        )
    assert check_editor_rules(HTML, {})["status"] == "needs_review"
    assert check_editor_rules(HTML, metadata(None))["status"] == "not_applicable"


@pytest.mark.parametrize(
    "body", ["<p>A</p><p>B</p>", "<ul><li><p>A</p></li></ul><p>B</p>"]
)
def test_summary_limit_survives_list_to_paragraph_conversion(body):
    content = '<h2 data-cv-section="why_points">Summary</h2>' + body
    with pytest.raises(HTTPException) as exc:
        check_editor_rules(content, metadata({"why_points_max": 1}))
    assert exc.value.status_code == 422


def test_list_paragraph_and_consent_are_not_double_counted():
    content = '<h2 data-cv-section="why_points">Summary</h2><ul><li><p>A</p></li></ul><p data-cv-section="rodo">Consent</p>'
    assert (
        check_editor_rules(content, metadata({"why_points_max": 1}))["status"]
        == "checked"
    )


def test_paragraph_duties_do_not_falsely_certify_client_limits():
    content = '<h2 data-cv-section="experience">Experience</h2><p data-cv-section="role">Engineer</p><p>First duty</p><p>Second duty</p>'
    report = check_editor_rules(content, metadata({"max_bullets_per_role": 1}))
    assert report["status"] == "needs_review"
    assert "max_bullets_per_role" not in report["checked_fields"]
    assert "max_bullets_per_role" in report["manual_fields"]


@pytest.mark.parametrize("limit", [1, 2])
def test_typed_duties_count_paragraphs_but_not_employer(limit):
    content = '<h2 data-cv-section="experience">Experience</h2><p data-cv-section="role">Engineer</p><p data-cv-section="employer">Company</p><p data-cv-section="duties_label">Responsibilities</p><p>First duty</p><p>Second duty</p><p data-cv-section="technologies">Python</p>'
    if limit == 1:
        with pytest.raises(HTTPException):
            check_editor_rules(content, metadata({"max_bullets_per_role": limit}))
    else:
        assert (
            check_editor_rules(content, metadata({"max_bullets_per_role": limit}))[
                "status"
            ]
            == "checked"
        )
