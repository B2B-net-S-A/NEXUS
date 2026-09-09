"""CV-14: one text matcher, independent policy and unchanged document content."""

from dataclasses import replace
from html.parser import HTMLParser

import pytest
from docx import Document

from app.services.cv_generator_b2b.client_rules import CvRuleSnapshot
from app.services.cv_generator_b2b.docx_renderer import (
    add_text_with_highlights,
    compile_keyword_patterns,
    highlight_spans,
)
from app.services.cv_generator_b2b.format_annotations import text_annotations
from app.services.cv_generator_b2b.highlight_policy import apply_highlight_policy
from app.services.cv_generator_b2b.html_export import _bold
from app.services.cv_generator_b2b.public_view import build_public_payload


BASE_RULE = CvRuleSnapshot(None, False, None, False, False)


@pytest.mark.parametrize(
    "policy,expected",
    [
        ("none", []),
        ("technologies", ["Python", "SQL"]),
        ("must", ["Python"]),
        ("must_nice", ["Python", "SQL"]),
        ("explicit", ["SQL"]),
    ],
)
def test_typed_policy_selects_only_source_present_technologies(policy, expected):
    data = {"experience": [{"technologies": ["Python", "SQL"]}], "skills": []}
    rule = replace(
        BASE_RULE,
        highlight_policy=policy,
        highlight_terms=("SQL", "Leadership", "Rust"),
    )
    apply_highlight_policy(
        data, rule, "Praca w Python i SQL", ["Python"], ["SQL", "Rust"]
    )
    assert data["highlight_keywords"] == expected
    assert data["experience"] == [{"technologies": ["Python", "SQL"]}]


@pytest.mark.parametrize(
    "text", ["Jest odpowiedzialny za integrację API.", "Jest doświadczonym inżynierem."]
)
def test_polish_sentence_start_is_not_a_tool_mention(text, monkeypatch):
    from app.services.cv_generator_b2b import docx_renderer as renderer

    monkeypatch.setattr(
        renderer, "is_taxonomy_technology", lambda value: value.casefold() == "jest"
    )
    assert highlight_spans(text, compile_keyword_patterns(["Jest"])) == []


def test_genuine_testing_context_still_highlights_jest(monkeypatch):
    from app.services.cv_generator_b2b import docx_renderer as renderer

    monkeypatch.setattr(
        renderer, "is_taxonomy_technology", lambda value: value.casefold() == "jest"
    )
    text = "Testy jednostkowe w Jest i testy integracyjne."
    assert [
        text[a:b] for a, b in highlight_spans(text, compile_keyword_patterns(["Jest"]))
    ] == ["Jest"]


class BoldText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.bold = False
        self.fragments = []

    def handle_starttag(self, tag, attrs):
        self.bold = tag == "b"

    def handle_endtag(self, tag):
        self.bold = False

    def handle_data(self, data):
        if self.bold:
            self.fragments.append(data)


@pytest.mark.parametrize(
    "text",
    [
        "🚀 Budowa API w Pythonie i SQL.",
        "C++ oraz .NET, nie digital.",
        "Python <script>alert(1)</script> SQL",
    ],
)
def test_docx_html_and_public_runs_have_identical_bold_text(text):
    keywords = ["Python", "SQL", "C++", ".NET", "Git"]
    para = Document().add_paragraph()
    add_text_with_highlights(para, text, keywords)
    docx_bold = [run.text for run in para.runs if run.bold]
    parsed = BoldText()
    parsed.feed(_bold(text, compile_keyword_patterns(keywords)))
    runs = text_annotations({"why_points": [text], "highlight_keywords": keywords})[
        text
    ]
    assert [run["text"] for run in runs if run["bold"]] == parsed.fragments == docx_bold
    assert "".join(run["text"] for run in runs) == para.text == text


def test_annotations_cannot_reintroduce_private_or_blind_fields():
    source = {
        "name": "Private Name",
        "blind_cv": True,
        "language": "pl",
        "warnings": ["Private Python warning"],
        "why_points": ["Python i SQL"],
        "highlight_keywords": ["Python", "SQL"],
    }
    public = build_public_payload(source)
    annotations = text_annotations(public)
    assert "Private" not in str(annotations)
    assert "Python i SQL" in annotations


def test_empty_explicit_policy_can_be_drafted_but_not_published():
    from pydantic import ValidationError
    from app.api.client_cv_rules import ClientCvRulePayload

    assert ClientCvRulePayload(highlight_policy="explicit").highlight_terms == []
    with pytest.raises(ValidationError):
        ClientCvRulePayload(highlight_policy="explicit", confirm=True)


def test_must_policy_reports_missing_must_even_when_nice_exists():
    data = {"experience": [], "skills": []}
    apply_highlight_policy(
        data, replace(BASE_RULE, highlight_policy="must"), "SQL", [], ["SQL"]
    )
    assert data["highlight_keywords"] == []
    assert data["highlight_policy_result"]["requires_champion"] is True
