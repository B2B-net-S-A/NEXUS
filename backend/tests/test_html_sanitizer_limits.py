"""Sanitizer HTML CV: koszt parsowania i zepsuty ``style`` (12.10.2026).

Błędy znalezione w przeglądzie bezpieczeństwa PR-a #2146:

* czas ``sanitize_cv_html`` rósł z kwadratem rozmiaru treści — przy głębokim
  drzewie (500 KB zagnieżdżonych ``<div>``: kilka minut), przy tysiącach
  akapitów z elementem w środku (walker szukał rodzica wśród rodzeństwa)
  i przy treści wpisanej wprost w ``<table>``. Handlery wołają sanitizer
  w pętli zdarzeń, więc jedno żądanie zatrzymywało serwer,
* nieprawidłowa deklaracja w ``style`` (choćby urwane ``font-size``) kończyła
  zapis CV błędem 500.

Zwykłe CV ma wyjść bez zmian bajt w bajt: wynik sanitizera jest porównywany
przy ponownym zatwierdzeniu i w skrótach treści kontroli AI. Limity siedzą
w parserze bleach (``_OpenElements``, licznik treści w tabeli, własny walker),
więc po podbiciu wersji bleach te testy mówią, czy zaczepy nadal działają.
"""

import re
import time

import bleach
import pytest

from app.services import html_sanitizer
from app.services.html_sanitizer import (
    MAX_MISNESTED_IN_TABLE,
    MAX_NESTING,
    MAX_TREE_DEPTH,
    sanitize_cv_html,
)

# Jedno żądanie nie może trwać minut. Mierzymy czas procesora, nie zegar: na
# obciążonej maszynie zegar pokazywał 80 s tam, gdzie procesor pracował 3 s.
# Zapas na wolny runner CI (lokalnie 1–4 s).
QUICK = 30


def _stock(markup: str) -> str:
    """Potok sprzed zmiany: ten sam pre-parser i allowlista, ``bleach.clean`` wprost."""
    cleaned = bleach.clean(
        html_sanitizer._visible(markup),
        tags=html_sanitizer.ALLOWED_TAGS,
        attributes=html_sanitizer.ALLOWED_ATTRIBUTES,
        protocols=html_sanitizer.ALLOWED_PROTOCOLS,
        css_sanitizer=html_sanitizer._CSS_SANITIZER,
        strip=True,
        strip_comments=True,
    )
    cleaned = html_sanitizer._NUMERIC_REFERENCE.sub(
        html_sanitizer._without_incompatible_reference, cleaned
    )
    return html_sanitizer._XML_INCOMPATIBLE.sub(" ", cleaned)


def _depth(markup: str) -> int:
    deepest = current = 0
    for closing, _tag in re.findall(r"<(/?)([a-z0-9]+)[^>]*>", markup):
        current += -1 if closing else 1
        deepest = max(deepest, current)
    return deepest


@pytest.fixture
def parser_depth(monkeypatch):
    """Najwięcej elementów, jakie parser HTML miał otwarte naraz."""
    peak = {"value": 0}

    class Recording(html_sanitizer._OpenElements):
        def append(self, element):
            super().append(element)
            peak["value"] = max(peak["value"], len(self))

        def insert(self, index, element):
            super().insert(index, element)
            peak["value"] = max(peak["value"], len(self))

    monkeypatch.setattr(html_sanitizer, "_OpenElements", Recording)
    return peak


# ── style ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("style", "kept"),
    [
        ("color: red; font-size", "color: red;"),
        ("color:red;)", "color:red;"),
        ("color:red;}", "color:red;"),
        ("color:red;]", "color:red;"),
        ("font-weight: bold; : 12px; margin: 0", "font-weight: bold;  margin: 0;"),
    ],
)
def test_broken_declaration_is_dropped_and_the_rest_of_the_style_stays(style, kept):
    assert (
        sanitize_cv_html(f'<p style="{style}">tekst</p>')
        == f'<p style="{kept}">tekst</p>'
    )


@pytest.mark.parametrize("style", [")", "}", "]", ";;;)", "font-size"])
def test_style_with_nothing_valid_does_not_break_saving(style):
    cleaned = sanitize_cv_html(f'<p style="{style}">tekst</p>')
    assert cleaned in ('<p style="">tekst</p>', "<p>tekst</p>")


# ── głębokie drzewo ─────────────────────────────────────────────────────────

# Jednostki powtarzane w kółko. Druga połowa nie wygląda na zagnieżdżoną,
# a parser buduje z niej drzewo głębokie na tysiące poziomów.
DEEP_UNITS = [
    "<div>",
    "<span>",
    "<blockquote>",
    "<ul><li>",
    "<table><tbody><tr><td>",
    "<b><i>",
    "<div/>",
    '<div class="a" style="color: red">',
    "<li><h1>",
    "<h1><li>",
    "<dd><h2>",
    "<b><div></b>",
    "<i><div></i>",
    "<span><div></span>",
    "<span><ul></span>",
    "<table><b>x<tr><td>",
    "<nobr><div>",
]


@pytest.mark.parametrize("unit", DEEP_UNITS)
def test_deep_tree_is_cut_inside_the_parser_and_text_stays(unit, parser_depth):
    cleaned = sanitize_cv_html(unit * (60_000 // len(unit)) + "treść CV")
    assert "treść CV" in cleaned
    assert parser_depth["value"] <= MAX_TREE_DEPTH
    assert _depth(cleaned) <= MAX_TREE_DEPTH


def test_flattened_content_keeps_at_most_the_allowed_nesting():
    cleaned = sanitize_cv_html("<div>" * 3000 + "treść CV" + "</div>" * 3000)
    assert "treść CV" in cleaned
    assert cleaned.count("<div>") == MAX_NESTING


def test_raw_text_of_a_dropped_textarea_does_not_turn_into_markup():
    # Python oddaje tekst ``<textarea>`` surowy; po pominięciu jej znacznika
    # zawartość stałaby się prawdziwymi znacznikami, już poza limitem.
    hostile = "<div>" * 200 + "<textarea>" + "<b>" * 2000 + "</textarea>"
    cleaned = sanitize_cv_html(hostile)
    assert "<b>" not in cleaned
    assert "&lt;b&gt;" in cleaned


def test_parser_hooks_are_alive():
    """Zaczepy w bleach 6.4.0 — po zmianie wersji ten test pada pierwszy."""
    with pytest.raises(html_sanitizer._TreeTooDeep):
        html_sanitizer._allowlisted("<div>" * (MAX_TREE_DEPTH + 5))
    with pytest.raises(html_sanitizer._TableMisnested):
        html_sanitizer._allowlisted(
            "<p>a</p><table>" + "<b>x</b>" * (MAX_MISNESTED_IN_TABLE + 5)
        )


# ── czas dla największej przyjmowanej treści (500 000 znaków) ───────────────


@pytest.mark.parametrize(
    "hostile",
    [
        pytest.param("<div>" * 100_000, id="niedomknięte-div"),
        pytest.param(
            ("<div>" * 100 + "x" + "</div>" * 100) * 450, id="piła-100-poziomów"
        ),
        pytest.param("<li><h1>" * 62_500, id="li-h1"),
        pytest.param("<b><div></b>" * 41_600, id="b-div-koniec-b"),
        pytest.param(
            "<div>" + "<p><b>x</b></p>" * 33_000 + "</div>", id="szerokie-drzewo"
        ),
        pytest.param("<table>" + "<b>x</b>" * 62_000, id="treść-wprost-w-tabeli"),
        pytest.param("<div>" * 50_000 + "</span>" * 35_000, id="zbłąkane-zamknięcia"),
    ],
)
def test_largest_accepted_payload_is_quick(hostile):
    assert 450_000 < len(hostile) <= 500_000
    started = time.process_time()
    sanitize_cv_html(hostile)
    assert time.process_time() - started < QUICK


def test_wide_tree_and_table_content_are_kept():
    wide = "<div>" + "<p><b>x</b></p>" * 5000 + "</div>"
    assert sanitize_cv_html(wide) == wide
    in_table = sanitize_cv_html("<p>a</p><table>" + "<b>x</b>" * 3000)
    assert in_table.count("x") == 3000
    assert "<table" not in in_table


# ── atrybuty, ukryte znaczniki, zagnieżdżony CSS ────────────────────────────


def test_tag_with_thousands_of_attributes_reaches_the_parser_with_a_capped_list():
    # Tokenizer html5lib porównuje każdy atrybut ze wszystkimi wcześniejszymi:
    # 10 000 atrybutów w jednym znaczniku (58 KB) to kilkadziesiąt sekund.
    hostile = '<p class="a"' + "".join(f" a{i}" for i in range(20_000)) + ">tekst</p>"
    visible = html_sanitizer._visible(hostile)
    assert len(re.findall(r"\sa\d+", visible)) < html_sanitizer.MAX_ATTRIBUTES
    started = time.process_time()
    assert sanitize_cv_html(hostile) == '<p class="a">tekst</p>'
    assert time.process_time() - started < QUICK


@pytest.mark.parametrize(
    "hostile",
    [
        '<p class="a"' + ' b="1"' * 5000 + ">tekst</p>",
        "<br" + " x" * 5000 + "/>tekst",
        '<p class="a" '
        + " ".join(f'k{i}="&quot;&lt;{i}"' for i in range(300))
        + ">tekst</p>",
    ],
)
def test_capped_attribute_list_keeps_the_tag_and_its_leading_attributes(hostile):
    cleaned = sanitize_cv_html(hostile)
    assert "tekst" in cleaned
    assert cleaned.startswith(('<p class="a">', "<br>"))


def test_tag_with_an_ordinary_number_of_attributes_is_passed_through_verbatim():
    markup = (
        '<td colspan="2" rowspan="1" class="x y" style="color: red;" width=10 height=\'5\' '
        'data-a="1" data-b data-c=3 lang="pl" dir="ltr" id="k" title="t" align=left valign=top>x</td>'
    )
    assert html_sanitizer._visible(markup) == markup


HIDDEN = {
    "a<style>b</style>c": "ac",
    "a<style>b<script>c</style>d</script>e": "ade",
    "a<script>b<style>c</script>d</style>e": "ade",
    "<head><title>t</title></head><p>x</p>": "<p>x</p>",
    "<template><p>a</p></template>b</template>c": "bc",
    "a<noscript>b<head>c</noscript>d</head>e": "ade",
    "<head><head><style>x</head>y</style>z</head>k": "k",
    "<script/>po": "po",
    "<style>a</b>c</style>d": "d",
    "x</style>y</head>z": "xyz",
    "<head>a<template>b<head>c</template>d</head>e": "e",
    "<noscript><p>a</noscript></p>b": "</p>b",
}


@pytest.mark.parametrize(("markup", "visible"), HIDDEN.items())
def test_hidden_content_is_cut_exactly_as_before(markup, visible):
    assert html_sanitizer._visible(markup) == visible


@pytest.mark.parametrize("hidden", ["head", "template", "noscript"])
def test_thousands_of_hidden_tags_do_not_cost_a_scan_per_end_tag(hidden):
    hostile = f"<{hidden}>" * 50_000 + "</x>" * 30_000 + f"</{hidden}>widać"
    started = time.process_time()
    assert html_sanitizer._visible(hostile) == "widać"
    assert time.process_time() - started < QUICK


@pytest.mark.parametrize("nested", ["f(" * 600, "[" * 600, "(" * 600, "{" * 600])
def test_deeply_nested_css_value_drops_the_style_instead_of_crashing(nested):
    cleaned = sanitize_cv_html(f'<p style="color:{nested}">tekst</p>')
    assert cleaned in ('<p style="">tekst</p>', "<p>tekst</p>")


# ── zwykła treść bez zmian ──────────────────────────────────────────────────

ORDINARY = [
    # generator: sekcje, stanowiska, listy, klauzula
    '<article class="cv"><h1>Senior Developer – Anna P.</h1><p><strong>Rozważany na stanowisko:</strong> Dev</p><hr>'
    '<section><h2 data-cv-section="experience">DOŚWIADCZENIE</h2><div class="job">'
    '<p data-cv-section="role"><strong>Dev</strong> 2020 – 2024</p><p class="job-co">Firma</p>'
    "<ul><li>Pierwszy <strong>punkt</strong>.</li><li>Drugi punkt &amp; więcej.</li></ul></div></section>"
    '<p class="rodo">Wyrażam zgodę…</p></article>',
    # edytor: płasko, punkty jako <li><p>
    '<h1>Dev</h1><h2 data-cv-section="skills">UMIEJĘTNOŚCI</h2><ul><li><p>Java</p></li><li><p>SQL</p></li></ul>'
    '<p data-cv-section="rodo" style="font-size: 8pt; line-height: 1.35;">Wyrażam zgodę…</p>',
    # dwanaście poziomów listy
    "<ul><li>" * 12 + "dno" + "</li></ul>" * 12,
    # dziesięć tabel układu jedna w drugiej, z opakowaniami z poczty
    "<table><tbody><tr><td><div><font>" * 10
    + "treść"
    + "</font></div></td></tr></tbody></table>" * 10,
    # znaczniki wklejone z Worda: tekst, dzieci i ogony w każdym układzie
    '<div>przed<span style="color: red;"><b><i><u>x</u></i></b></span>po<br>nowa linia<p>akapit</p>ogon</div>końcówka',
    # niedomknięte akapity i punkty (HTML z poczty) — parser zamyka je sam
    "<p>raz<p>dwa<p>trzy<ul><li>a<li>b<li>c</ul>" * 80,
    # źle zagnieżdżone formatowanie i treść między wierszami tabeli
    "<b>raz<i>dwa</b>trzy</i><p><b>cztery<p>pięć</b>sześć",
    "<p>a</p><table>tekst<tr><td>komórka</td></tr><b>x</b></table><p>b</p>",
    # komentarz, encje, puste elementy
    "<p>Krak&oacute;w &amp; &#243; <!-- komentarz --><span></span><b></b></p><ul></ul>",
    # głowa dokumentu i skrypt znikają razem z treścią
    "<html><head><style>p{color:red}</style></head><body><p>widać</p><script>alert(1)</script></body></html>",
    # kilka tysięcy akapitów — długi dokument nie jest „wrogi”
    '<p data-cv-section="role"><strong>Dev</strong> 2020</p><ul><li><p>Punkt</p></li></ul>'
    * 1500,
]


@pytest.mark.parametrize("markup", ORDINARY)
def test_ordinary_cv_markup_comes_out_exactly_as_before(markup, parser_depth):
    cleaned = sanitize_cv_html(markup)
    assert cleaned == _stock(markup)
    assert sanitize_cv_html(cleaned) == cleaned
    assert parser_depth["value"] < MAX_TREE_DEPTH
