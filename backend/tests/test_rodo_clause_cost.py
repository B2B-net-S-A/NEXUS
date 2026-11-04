"""Strażnik klauzuli RODO ma koszt liniowy (audyt 13.10.2026, punkt 1).

Do 14.10.2026 `_pinned_by_word` przy każdym akapicie wyglądającym na klauzulę
sklejał od nowa cały tekst opakowania (`is_rodo_node(parent)`). Tysiące
akapitów w jednym `<div>` dawały koszt kwadratowy: ~3 s CPU przy 4000
akapitach, minuty przy limicie treści — a strażnik biegnie synchronicznie
w trasie `async` jedynego procesu uvicorna, więc stał cały NEXUS.
"""

from __future__ import annotations

import time

import pytest

from app.services.cv_generator_b2b.docx_renderer import TRANSLATIONS
from app.services.cv_rodo_clause import keep_rodo_clause
from app.services.html_sanitizer import sanitize_cv_html

CLAUSE = TRANSLATIONS["pl"]["rodo"]
SAVED = f'<h1>Jan</h1><p>Treść</p><p class="rodo" data-cv-section="rodo">{CLAUSE}</p>'
# Przy kosztach kwadratowych ten rozmiar to kilkadziesiąt sekund CPU.
PARAGRAPHS = 12_000
BUDGET_S = 5.0


@pytest.mark.parametrize(
    "unit",
    [
        '<p class="rodo">x</p>',
        '<p class="rodo"></p>',
        "<p>x</p>",
    ],
    ids=["klasa-z-tekstem", "klasa-pusty", "zwykly-akapit"],
)
def test_many_paragraphs_in_one_wrapper_cost_linear_time(unit: str) -> None:
    incoming = sanitize_cv_html("<div>" + unit * PARAGRAPHS + "</div>")

    started = time.process_time()
    out = keep_rodo_clause(SAVED, incoming)
    spent = time.process_time() - started

    assert spent < BUDGET_S, f"{spent:.1f} s CPU dla {PARAGRAPHS} akapitów"
    # Zapisana klauzula dalej stoi w treści.
    assert CLAUSE.split()[0] in out


def test_untouched_clause_still_comes_back_byte_for_byte() -> None:
    incoming = sanitize_cv_html(SAVED.replace("<p>Treść</p>", "<p>Nowa treść</p>"))

    assert keep_rodo_clause(SAVED, incoming) == incoming
