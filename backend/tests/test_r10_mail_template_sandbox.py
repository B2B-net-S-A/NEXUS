"""Runda 10 (R10-V3-1): sandbox szablonów maili — napisy pośrednie mają sufit.

Każda z poniższych operacji buduje w jednym wywołaniu kodu C napis większy niż
limit wyniku, zanim funkcja śledząca albo limit długości wyjścia zdążą
zareagować. Ma paść SecurityError szybko, zanim napis powstanie.
"""

from __future__ import annotations

import time

import pytest
from jinja2.exceptions import SecurityError

from app.api import user_email_templates as uet


def _render_fast(env, source: str, ctx: dict | None = None) -> str:
    start = time.monotonic()
    try:
        return uet._render_bounded(env, source, ctx or {})
    finally:
        assert time.monotonic() - start < 1.0


DOUBLING = '{% set s = "a"*100000 %}' + "{% set s = s + s %}" * 6 + "{{ s|length }}"

EXPLOSIVE = [
    DOUBLING,
    '{% set s = "a"*100000 %}' + "{% set s = s ~ s %}" * 6 + "{{ s|length }}",
    '{% set a = "%99999999s" % "a" %}{{ a|length }}',
    '{% set a = "%.99999999f" % 1.5 %}{{ a|length }}',
    '{% set a = "%*s" % (99999999, "a") %}{{ a|length }}',
    '{% set a = "%((x))99999999s" % {"(x)": "a"} %}{{ a|length }}',
    '{% set a = "%99999999s"|format("a") %}{{ a|length }}',
    '{% set a = "{:99999999}".format("a") %}{{ a|length }}',
    '{% set a = "{x:>99999999}".format_map({"x": "a"}) %}{{ a|length }}',
    '{% set s = "a"*1000 %}{% set a = s|replace(old="", new="b"*1000) %}{{ a|length }}',
    '{% set s = "a"*100000 %}{% set a = [s, s, s, s, s, s]|join %}{{ a|length }}',
    '{% set s = "a"*100000 %}{% set a = s.join(["b"] * 50) %}{{ a|length }}',
    '{% set s = "a\n"*50000 %}{% set a = s|indent(9999999) %}{{ a|length }}',
    '{% set a = "a"|center(9999999) %}{{ a|length }}',
    '{% set a = "a".ljust(9999999) %}{{ a|length }}',
    '{% set a = ("a b " * 20000)|wordwrap(1, wrapstring="x" * 1000) %}{{ a|length }}',
    '{% set a = ("\t" * 50000).expandtabs(9999999) %}{{ a|length }}',
    "{% set a = (range(1000)|batch(1)|list)|sum(start=[]) %}{{ a|length }}",
    # `str()` listy stu tysięcy odwołań do długiego napisu — jedno wywołanie w C.
    '{% set s = "a"*100000 %}{{ [s] * 100000 }}',
    '{% set s = "a"*100000 %}{{ ([s] * 100000)|string|length }}',
    '{% set s = "a"*100000 %}{{ ("%s" % ([s] * 100000,))|length }}',
    '{% set s = "a"*100000 %}{{ ([s] * 100000 ~ "")|length }}',
    '{% set s = "a"*100000 %}{% set n = namespace(l=[s] * 100000) %}{{ n }}',
    # Bufor bloku: `concat` sklejał wszystko naraz na `{% endset %}`.
    '{% set s = "a"*100000 %}{% set x %}{% for i in range(1000) %}{{ s }}'
    "{% endfor %}{% endset %}{{ x|length }}",
    '{% set s = "a"*100000 %}{% macro m() %}{% for i in range(1000) %}{{ s }}'
    "{% endfor %}{% endmacro %}{{ m()|length }}",
    # Podwajanie listy w miejscu.
    "{% set l = [1] %}{% for i in range(40) %}{% set _ = l.extend(l) %}"
    "{% endfor %}{{ l|length }}",
    '{{ "a".encode() }}',
]


@pytest.mark.parametrize(
    "source", EXPLOSIVE, ids=[f"case{i}" for i in range(len(EXPLOSIVE))]
)
def test_explosive_operation_is_refused_before_it_runs(source):
    with pytest.raises(SecurityError):
        _render_fast(uet._jinja_env, source)


def test_doubling_is_refused_in_the_subject_env_too():
    with pytest.raises(SecurityError):
        _render_fast(uet._subject_env, DOUBLING)


def test_percent_format_width_cannot_hide_behind_a_mapping_key():
    with pytest.raises(SecurityError):
        _render_fast(uet._jinja_env, '{{ ("%(a)99999999s" % {"a": "x"})|length }}')


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("{{ 'Dzień dobry, ' + name + '!' }}", "Dzień dobry, Anna!"),
        ("{{ 'Dzień dobry, ' ~ name ~ '!' }}", "Dzień dobry, Anna!"),
        ("{{ '%s ma %d lat' % (name, 30) }}", "Anna ma 30 lat"),
        ("{{ '%.2f zł' % 125.5 }}", "125.50 zł"),
        ("{{ '%(n)s' % {'n': name} }}", "Anna"),
        ("{{ '%-6s|' % name }}", "Anna  |"),
        ("{{ '100%%' % () }}", "100%"),
        ("{{ loop_index % 2 }}", "1"),
        ("{{ '%s, %s'|format(name, 'hej') }}", "Anna, hej"),
        ("{{ '{} {:>6}'.format(name, 'x') }}", "Anna      x"),
        ("{{ name|replace(old='A', new='Ha') }}", "Hanna"),
        ("{{ [name, 'B']|join(', ') }}", "Anna, B"),
        ("{{ ', '.join([name, 'B']) }}", "Anna, B"),
        ("{{ 'a\nb'|indent(2, first=True) }}", "  a\n  b"),
        ("{{ name|center(8) }}", "  Anna  "),
        ("{{ [1, 2, 3]|sum }}", "6"),
        ("{{ ([1] + [2])|length }}", "2"),
        ("{{ 2 + 3 }}", "5"),
    ],
)
def test_ordinary_templates_still_render(source, expected):
    out = _render_fast(uet._subject_env, source, {"name": "Anna", "loop_index": 5})
    assert out == expected


def test_python_loop_that_allocates_too_much_is_stopped(monkeypatch):
    """`|map('upper')` na liście długich napisów to pętla w Pythonie — każdy
    krok jest mały, ale razem alokują GB szybciej niż limit czasu."""
    monkeypatch.setattr(uet, "_RENDER_MEMORY_GROWTH_LIMIT", 64 * 1024 * 1024)
    monkeypatch.setattr(uet, "_TRACER_CHECK_EVERY", 16)
    source = (
        '{% set s = "a"*100000 %}{% set l = [s] * 20000 %}'
        "{{ (l|map('upper')|list)|length }}"
    )
    monkeypatch.setattr(uet, "_RENDER_DEADLINE_SECONDS", 30.0)
    with pytest.raises(SecurityError, match="pamięci"):
        uet._render_bounded(uet._subject_env, source, {})


def test_concat_keeps_escaping_in_the_html_env():
    out = _render_fast(uet._jinja_env, "{{ '<b>' ~ name }}", {"name": "R&D"})
    assert out == "&lt;b&gt;R&amp;D"
