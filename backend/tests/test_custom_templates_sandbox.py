"""Wzory własne: render w izolacji i walidacja szablonu (bez bazy).

Wzór własny to DOCX od człowieka albo szkic modelu — szablon nie jest kodem
zaufanym. Te testy pilnują, że każda próba wyjścia poza pola z listy pada
przy zapisie (walidacja) i przy renderze (sandbox), a to, co liczy kod
(kwota słownie, data, formy Pan/Pani), liczy się poprawnie.
"""

from __future__ import annotations

import io
from pathlib import Path

import docx
import pytest
from jinja2.exceptions import SecurityError, UndefinedError

from app.services.custom_templates import sandbox
from app.services.custom_templates.base import BASES_BY_KEY, fields_from_paths
from app.services.custom_templates.fields import (
    CustomField,
    FieldsError,
    ItemKey,
    build_context,
    parse_fields,
    sample_values,
    value_problems,
)


def _docx(*lines: str) -> bytes:
    document = docx.Document()
    for line in lines:
        document.add_paragraph(line)
    buf = io.BytesIO()
    document.save(buf)
    return buf.getvalue()


def _text(data: bytes) -> str:
    return "\n".join(p.text for p in docx.Document(io.BytesIO(data)).paragraphs)


FIELDS = [
    CustomField(key="partner.name", label="Imię i nazwisko", required=True),
    CustomField(key="partner.gender", label="Płeć", kind="gender"),
    CustomField(key="fee", label="Wynagrodzenie", kind="money", required=True),
    CustomField(key="document_date", label="Data", kind="date"),
    CustomField(
        key="agenda",
        label="Agenda",
        kind="list",
        item_keys=(ItemKey("no", "Nr"), ItemKey("text", "Treść")),
    ),
]


# ── Wyjście poza pola musi paść ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "source",
    [
        "{{ ''.__class__ }}",
        "{{ ''.__class__.__mro__[1].__subclasses__() }}",
        "{{ partner.__class__ }}",
        "{{ partner.name.__class__ }}",
        "{{ partner._secret }}",
        "{{ partner }}",
        "{{ config }}",
        "{{ lipsum }}",
        "{{ range(10) }}",
        "{{ partner.name.upper() }}",
        "{{ partner['name'] }}",
        "{{ cycler.__init__.__globals__ }}",
        "{{ partner.name | attr('__class__') }}",
        "{{ partner.name | format('x') }}",
        "{% for x in range(3) %}{{ x }}{% endfor %}",
        "{% for m in partner.name %}{{ m }}{% endfor %}",
        "{% for m in agenda %}{{ m.__class__ }}{% endfor %}",
        "{% for m in agenda %}{{ m.missing }}{% endfor %}",
        "{% set x = 1 %}{{ x }}",
        "{% include 'x' %}",
        "{% macro m() %}{% endmacro %}",
        "{{ company.__dict__ }}",
        "{{ g.g_pan.__class__ }}",
        "{{ unknown_field }}",
    ],
)
def test_template_outside_fields_is_rejected_on_save(source: str) -> None:
    check = sandbox.validate(_docx(source), FIELDS)
    assert check.problems, source


def test_render_refuses_invalid_template() -> None:
    with pytest.raises(sandbox.TemplateInvalid) as exc:
        sandbox.render(_docx("{{ ''.__class__ }}"), FIELDS, {})
    assert exc.value.problems


def test_sandbox_environment_blocks_class_escape_even_without_validation() -> None:
    """Druga warstwa: gdyby walidacja przepuściła, sandbox nie wypuści."""
    env = sandbox._env()
    with pytest.raises((SecurityError, UndefinedError)):
        env.from_string("{{ ''.__class__.__mro__ }}").render()
    with pytest.raises((SecurityError, UndefinedError)):
        env.from_string("{{ x.__init__.__globals__ }}").render(x=object())
    assert "attr" not in env.filters and "format" not in env.filters
    assert env.globals == {}


def test_allowed_constructs_pass() -> None:
    source = (
        "{{ partner.name | upper }} {{ g.g_pan }} {{ g.pan }} {{ fee }} "
        "{{ fee_words }} {{ company.name }} {{ document_place }} "
        "{% if partner.name and fee %}tak{% else %}nie{% endif %} "
        "{% for m in agenda %}{{ loop.index }}. {{ m.no }} {{ m.text }}{% endfor %}"
    )
    check = sandbox.validate(_docx(source), FIELDS)
    assert check.problems == []
    assert check.unused(FIELDS) == ["Data"]


# ── Render liczy kod ────────────────────────────────────────────────────────


def test_render_fills_money_words_dates_and_gender_forms() -> None:
    data = _docx(
        "{{ g.g_pan }} {{ partner.name }}, {{ g.zwany }} Partnerem.",
        "Wynagrodzenie {{ fee }} zł ({{ fee_words }}), dnia {{ document_date }}.",
        "{%p for m in agenda %}",
        "{{ m.no }}. {{ m.text }}",
        "{%p endfor %}",
    )
    out = sandbox.render(
        data,
        FIELDS,
        {
            "partner.name": "Anna Przykładowa",
            "partner.gender": "k",
            "fee": "6200,5",
            "document_date": "2026-12-01",
            "agenda": [{"no": "1", "text": "Wstęp"}, {"no": "2", "text": "Praktyka"}],
        },
    )
    text = _text(out)
    assert "Panią Anna Przykładowa, zwana Partnerem." in text
    assert "6 200,50 zł (sześć tysięcy dwieście złotych 50/100)" in text
    assert "01.12.2026" in text
    assert "1. Wstęp" in text and "2. Praktyka" in text


def test_values_are_xml_escaped() -> None:
    out = sandbox.render(
        _docx("{{ partner.name }}"),
        FIELDS,
        {"partner.name": "A & B <w:t>x</w:t>", "fee": "1"},
    )
    assert "A & B <w:t>x</w:t>" in _text(out)


def test_context_has_only_fields_and_computed_values() -> None:
    ctx = build_context(FIELDS, {"partner.name": "X", "extra": "nie wchodzi"})
    assert set(ctx) == {
        "company",
        "document_place",
        "partner",
        "fee",
        "fee_words",
        "document_date",
        "agenda",
        "g",
    }
    assert "extra" not in ctx


# ── Lista pól i wartości ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw",
    [
        [{"key": "Partner.Nip", "label": "x"}],
        [{"key": "a.b.c.d", "label": "x"}],
        [{"key": "company.nip", "label": "x"}],
        [{"key": "g.pan", "label": "x"}],
        [{"key": "a", "label": "x"}, {"key": "a", "label": "y"}],
        [{"key": "partner", "label": "x"}, {"key": "partner.nip", "label": "y"}],
        [{"key": "x", "label": "x", "kind": "select"}],
        [{"key": "x", "label": "x", "kind": "eval"}],
        [{"key": "x", "label": "x", "kind": "list", "item_keys": [{"key": "__a"}]}],
        "nie lista",
    ],
)
def test_bad_field_lists_are_rejected(raw) -> None:
    with pytest.raises(FieldsError):
        parse_fields(raw)


def test_value_problems_name_missing_and_invalid_fields() -> None:
    problems = value_problems(FIELDS, {"fee": "dużo", "document_date": "jutro"})
    assert "Imię i nazwisko: wymagane" in problems
    assert "Wynagrodzenie: niepoprawna kwota" in problems
    assert "Data: niepoprawna data" in problems


# ── Wzór bazowy „Umowa B2B — szkolenia” ─────────────────────────────────────


def test_training_base_yields_valid_field_list_and_renders_sample() -> None:
    base = BASES_BY_KEY["training_agreement"]
    data = Path(base.path).read_bytes()
    fields = fields_from_paths(sandbox.discover(data))
    keys = {f.key for f in fields}
    assert {"partner.nip", "partner.gender", "fees.total", "agenda", "t.title"} <= keys
    assert "fees.total_words" not in keys  # słownie liczy kod
    assert not any(k.startswith(("g.", "company.")) for k in keys)
    by_key = {f.key: f for f in fields}
    assert by_key["fees.total"].kind == "money"
    assert by_key["partner.nip"].source == "ceidg"
    assert {i.key for i in by_key["agenda"].item_keys} == {"no", "text"}
    assert sandbox.validate(data, fields).problems == []
    out = sandbox.render(data, fields, sample_values(fields))
    text = _text(out)
    assert "Jan Przykładowy" in text or "Janem Przykładowym" in text
    assert "{{" not in text and "{%" not in text
