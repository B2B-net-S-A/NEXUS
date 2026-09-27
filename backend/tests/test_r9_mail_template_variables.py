"""Runda 9 (R9-N10-5): jedna lista zmiennych szablonów dla UI i wysyłki."""

from __future__ import annotations

import re
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.emails import (
    AVAILABLE_PLACEHOLDERS,
    DEFAULT_TEMPLATES,
    _assert_rejection_variables,
    _render_template,
)
from app.models.email_template import EmailCategory
from app.services.email_template_variables import (
    SUPPORTED_VARIABLES,
    TEMPLATE_VARIABLES,
    body_to_html,
    unsupported_variables,
)
from app.services.rejection_email_scheduler import _render

_FRONTEND_PAGE = (
    Path(__file__).resolve().parents[2]
    / "frontend"
    / "src"
    / "app"
    / "settings"
    / "templates"
    / "page.tsx"
)


def _candidate():
    return SimpleNamespace(name="Jan", lastname="Kowalski")


def _job(title="R&D Engineer"):
    return SimpleNamespace(title=title)


def _recruiter():
    return SimpleNamespace(name="Anna Nowak", email="anna@example.com")


def test_every_listed_variable_is_filled_by_the_sender():
    body = " ".join("{{" + name + "}}" for name, _ in TEMPLATE_VARIABLES)
    template = SimpleNamespace(subject="{{job_title}}", body="<p>" + body + "</p>")
    subject, rendered = _render(
        template=template,
        candidate=_candidate(),
        job=_job(),
        recruiter=_recruiter(),
        other_processes=[{"job_id": 1, "title": "Inna"}],
    )
    assert "{{" not in rendered
    assert "{{" not in subject


def test_backend_list_equals_ui_list():
    assert AVAILABLE_PLACEHOLDERS == ["{{" + n + "}}" for n, _ in TEMPLATE_VARIABLES]
    if not _FRONTEND_PAGE.exists():
        pytest.skip("frontend nie jest w tym checkoutcie")
    source = _FRONTEND_PAGE.read_text(encoding="utf-8")
    block = source[source.index("const AVAILABLE_PLACEHOLDERS") :]
    block = block[: block.index("];")]
    ui_keys = re.findall(r'key:\s*"\{\{([a-z_]+)\}\}"', block)
    assert ui_keys == [name for name, _ in TEMPLATE_VARIABLES]


def test_unsupported_variables_ignores_control_tokens():
    text = "{{#if other_processes}}x{{/if}} {{job_title}} {{company_name}} {{ salary }}"
    assert unsupported_variables(text) == ["{{company_name}}", "{{salary}}"]


def test_seeded_rejection_templates_have_no_unfilled_variables():
    for tpl in DEFAULT_TEMPLATES:
        if tpl["category"] == EmailCategory.rejection:
            assert unsupported_variables(tpl["subject"], tpl["body"]) == [], tpl["name"]


def test_saving_rejection_template_with_unfilled_variable_is_refused():
    with pytest.raises(HTTPException) as exc:
        _assert_rejection_variables(
            EmailCategory.rejection, "Temat", "Pozdrawiamy, {{company_name}}"
        )
    assert exc.value.status_code == 422
    assert exc.value.detail["variables"] == ["{{company_name}}"]


def test_other_categories_may_keep_manual_blanks():
    _assert_rejection_variables(EmailCategory.offer, "Oferta", "Stawka: {{salary}}")


def test_plain_text_body_becomes_paragraphs_and_escaped():
    html = body_to_html("Dzień dobry,\n\nZespół R&D\ndziękuje.\n\nPozdrawiamy")
    assert html == (
        "<p>Dzień dobry,</p>\n<p>Zespół R&amp;D<br>\ndziękuje.</p>\n<p>Pozdrawiamy</p>"
    )


def test_html_body_is_left_untouched():
    body = "<p>Cześć {{candidate_name}},</p>\n<p>Pozdrawiam</p>"
    assert body_to_html(body) == body


def test_plain_text_template_renders_paragraphs_in_sent_mail():
    template = SimpleNamespace(
        subject="Informacja — {{job_title}}",
        body="Szanowny/a {{candidate_name}},\n\nDziękujemy.\n{{recruiter_name}}",
    )
    subject, body = _render(
        template=template,
        candidate=_candidate(),
        job=_job(),
        recruiter=_recruiter(),
        other_processes=[],
    )
    assert body == "<p>Szanowny/a Jan,</p>\n<p>Dziękujemy.<br>\nAnna Nowak</p>"
    assert subject == "Informacja — R&D Engineer"


def test_preview_fills_the_same_candidate_variables_as_sending():
    cand = SimpleNamespace(name="Anna", lastname="Nowak")
    _, body = _render_template(
        "s", "{{candidate_name}}|{{candidate_lastname}}|{{candidate_full_name}}", cand
    )
    assert body == "Anna|Nowak|Anna Nowak"


def test_supported_variables_scan_is_linear():
    text = "{{" * 8000 + "x" * 8000
    start = time.perf_counter()
    unsupported_variables(text)
    body_to_html("\n" * 16000 + "a")
    assert time.perf_counter() - start < 0.05


def test_supported_set_matches_list():
    assert SUPPORTED_VARIABLES == {n for n, _ in TEMPLATE_VARIABLES}
