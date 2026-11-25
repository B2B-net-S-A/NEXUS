"""„Najmocniejszy wynik” po zmianie treści CV (przegląd 25.11.2026, bez bazy).

Wynik modelu sprawdzono na HTML-u, z którego go policzono
(`results_source_sha`). Gdy rekruter potem usunął rolę albo zmienił liczbę,
flaga `verified` jest nieaktualna: render sprawdza wybrany wynik jeszcze raz
na bieżących rolach (sam kod, bez sieci), a niesprawdzony ustępuje trzeciemu
punktowi generatora. Zdanie wpisane przez rekrutera zostaje. Dane fikcyjne.
"""

from __future__ import annotations

import copy

import pytest

from app.services import cv_new_layout, cv_new_pdf
from app.services.cv_generator_b2b.html_export import render_interactive_html
from app.services.cv_layout import forget_page1_result
from app.services.cv_page1_result_checks import source_sha
from tests.test_cv_page1_results import GOOD, PAYLOAD

THIRD_POINT = PAYLOAD["why_points"][2]
HTML = render_interactive_html(PAYLOAD, None, document_only=True)


def _html(change) -> str:
    payload = copy.deepcopy(PAYLOAD)
    change(payload)
    return render_interactive_html(payload, None, document_only=True)


def _extras(sha: str, **values) -> dict:
    return {
        "results": [{**GOOD, "verified": True}],
        "result_index": 0,
        "results_source_sha": sha,
        **values,
    }


@pytest.fixture
def captured(monkeypatch):
    """Render bez WeasyPrint — zapamiętuje dokument, który dostałby renderer."""
    seen: dict = {}

    def fake_render(document):
        seen["document"] = document
        report = type("Report", (), {"fits": True, "font_pt": 10.0, "steps": ()})
        return b"%PDF-fake", report

    monkeypatch.setattr(cv_new_layout, "render_new_cv_pdf_with_report", fake_render)
    return seen


def _why(captured, html: str, extras: dict, *, blind: bool = False) -> tuple:
    cv_new_pdf._render(
        html, language="pl", blind=blind, fallback=None, extras=extras, consent=None
    )
    return captured["document"].why


def _drop_first_role(payload: dict) -> None:
    payload["experience"] = payload["experience"][1:]


def _change_number(payload: dict) -> None:
    duties = payload["experience"][0]["responsibilities"]
    duties[0] = duties[0].replace("30%", "10%")


def test_fresh_result_reaches_page_1(captured):
    why = _why(captured, HTML, _extras(source_sha(HTML)))
    assert why[2].startswith("Ograniczenie defektów produkcyjnych")


def test_result_from_a_removed_role_falls_back_to_point_3(captured):
    html = _html(_drop_first_role)
    why = _why(captured, html, _extras(source_sha(HTML)))
    assert why[2] == THIRD_POINT


def test_result_with_a_changed_number_falls_back_to_point_3(captured):
    html = _html(_change_number)
    why = _why(captured, html, _extras(source_sha(HTML)))
    assert why[2] == THIRD_POINT


def test_result_still_true_after_other_edits_stays(captured):
    def rename_second_role(payload: dict) -> None:
        payload["experience"][1]["position"] = "Tester automatyzujący"

    html = _html(rename_second_role)
    why = _why(captured, html, _extras(source_sha(HTML)))
    assert why[2].startswith("Ograniczenie defektów produkcyjnych")


def test_extras_without_sha_are_checked_too(captured):
    extras = _extras("x")
    extras.pop("results_source_sha")
    why = _why(captured, _html(_drop_first_role), extras)
    assert why[2] == THIRD_POINT


def test_recruiter_sentence_is_not_rechecked(captured):
    extras = _extras(source_sha(HTML), result_text="Zdanie rekrutera o 99% wyniku")
    why = _why(captured, _html(_drop_first_role), extras)
    assert why[2] == "Zdanie rekrutera o 99% wyniku"


def test_recheck_does_not_change_stored_extras(captured):
    extras = _extras(source_sha(HTML))
    before = copy.deepcopy(extras)
    _why(captured, _html(_drop_first_role), extras)
    assert extras == before


# ── Inna generacja: wynik i własny wyróżnik znikają, wieniec zostaje ────────


def test_other_generation_forgets_result_and_custom_highlight():
    extras = _extras(
        source_sha(HTML),
        result_text="Zdanie rekrutera",
        wreath="school",
        highlight={"mode": "custom", "label": "Bank", "token": "B", "text": "Zdanie"},
    )
    assert forget_page1_result(extras) == {"wreath": "school"}


def test_other_generation_keeps_highlight_turned_off():
    extras = _extras("x", highlight={"mode": "off"})
    assert forget_page1_result(extras) == {"highlight": {"mode": "off"}}


def test_nothing_left_is_none():
    assert forget_page1_result(_extras("x")) is None
    assert forget_page1_result(None) is None


def test_new_cv_forgets_sentences_1_to_3_too():
    """Zdania 1–3 strony 1 (#3972) opisują poprzednie CV jak wynik."""
    extras = {
        "why": ["Zdanie 1.", "", ""],
        "why_generated": [
            {"slot": "experience", "text": "Zdanie 1.", "verified": True}
        ],
        "why_source_sha": "abc",
        "wreath": "cert",
    }
    assert forget_page1_result(extras) == {"wreath": "cert"}
