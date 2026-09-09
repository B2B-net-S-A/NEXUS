from app.services.cv_generator_b2b.client_rules import CvRuleSnapshot
from app.services.cv_generator_b2b.rule_feedback import presentation_feedback


def rule(**kwargs):
    return CvRuleSnapshot(None, False, None, False, False, **kwargs)


def test_reports_real_limit_violation_instead_of_claiming_rule_applied():
    result = presentation_feedback(
        {"experience": [{"responsibilities": ["long text", "second"]}]},
        rule(max_bullets_per_role=1, max_bullet_chars=4),
    )
    assert [item["status"] for item in result[:2]] == ["conflict", "conflict"]


def test_distinguishes_absent_content_and_unverified_instruction():
    result = presentation_feedback(
        {}, rule(max_bullet_chars=40, generator_instructions="Write a strong summary")
    )
    assert result[0]["status"] == "not_applicable"
    assert result[-1]["status"] == "needs_review"


def test_omission_is_checked_against_actual_output():
    result = presentation_feedback(
        {"education": ["School"]}, rule(omit_sections=("education",))
    )
    assert result[0]["status"] == "conflict"
    assert (
        presentation_feedback({}, rule(omit_sections=("education",)))[0]["status"]
        == "satisfied"
    )


def test_highlight_report_explains_ignored_source_absent_terms():
    result = presentation_feedback(
        {
            "highlight_policy_result": {
                "policy": "explicit",
                "ignored": ["Kubernetes"],
                "selected": ["Python"],
            }
        },
        rule(highlight_policy="explicit"),
    )
    assert result[0]["status"] == "satisfied"
    assert result[1]["status"] == "skipped"
    assert "Kubernetes" in result[1]["label"]
    assert "źródle" in result[1]["label"]


def test_missing_champion_does_not_claim_highlighting_satisfied():
    result = presentation_feedback(
        {"highlight_policy_result": {"policy": "champion", "requires_champion": True}},
        rule(highlight_policy="champion"),
    )
    assert all(item["status"] == "not_applicable" for item in result)


def test_dates_distinguish_conflict_unknown_and_absent():
    for dates, expected in [
        ("01.2020", "conflict"),
        ("January 2020", "needs_review"),
        ("", "not_applicable"),
    ]:
        result = presentation_feedback(
            {"experience": [{"dates": dates}]}, rule(date_format="YYYY-MM")
        )
        assert (
            next(item for item in result if item["field"] == "date_format")["status"]
            == expected
        )


def test_glossary_explains_rejected_wrong_language_and_untranslated_entries():
    result = presentation_feedback(
        {"language": "pl", "position": "Business Analyst"},
        rule(
            glossary=(
                ("Junior", "Senior"),
                ("Programista", "Software Developer"),
                ("Business Analyst", "Analityk Biznesowy"),
            )
        ),
    )
    assert [item["status"] for item in result if item["field"] == "glossary"] == [
        "skipped",
        "not_applicable",
        "conflict",
    ]
