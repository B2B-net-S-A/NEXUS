"""„Napisz od nowa”: nowa wersja CV, ręcznie poprawione części zostają (PR 5).

Szkic powstał z generacji A, rekruter go poprawiał, generacja B przychodzi
po „Napisz od nowa”. Części szkicu, których tekst różni się od A, zostają
w wersji rekrutera; reszta przychodzi z B. Dane fikcyjne.
"""

from __future__ import annotations

import copy
import re

from app.services.cv_generator_b2b.html_export import render_interactive_html
from app.services.cv_generator_b2b.public_view import build_public_payload
from app.services.cv_rewrite_merge import merge_rewrite

PAYLOAD = {
    "name": "Anna Testowa",
    "first_name": "Anna",
    "position": "Java Developer",
    "language": "pl",
    "why_points": ["7 lat w Javie, w tym 3 lata w bankowości."],
    "skills": [{"label": "Backend", "content": "Java, Spring Boot"}],
    "languages": ["Polski – ojczysty", "Angielski – B2"],
    "experience": [
        {
            "dates": "03.2021 – obecnie",
            "company": "Bank Przykładowy",
            "industry": "Bankowość",
            "position": "Senior Java Developer",
            "responsibilities": ["Rozwój usług płatności.", "Code review."],
            "technologies": ["Java", "Kafka"],
        },
        {
            "dates": "06.2017 – 02.2021",
            "company": "Logistyka Przykład",
            "industry": "Logistyka",
            "position": "Java Developer",
            "responsibilities": ["Rozwój systemu śledzenia przesyłek."],
            "technologies": ["Java"],
        },
    ],
}


def _generated(payload: dict) -> str:
    return render_interactive_html(
        build_public_payload(payload), [], document_only=True
    )


def _editor(markup: str) -> str:
    """Kształt po edytorze: bez `article` i `div.job`, `b` → `strong`."""
    markup = re.sub(r"</?article[^>]*>|<div class=\"job\"[^>]*>|</div>", "", markup)
    return markup.replace("<b>", "<strong>").replace("</b>", "</strong>")


def _newer() -> dict:
    payload = copy.deepcopy(PAYLOAD)
    payload["why_points"] = ["Projektował płatności w Javie i **Kafka**."]
    payload["experience"][0]["responsibilities"] = ["Usługi płatności w Kafka."]
    payload["experience"][1]["responsibilities"] = ["System przesyłek w Javie."]
    return payload


PREVIOUS = _generated(PAYLOAD)
NEW = _generated(_newer())


def test_untouched_draft_takes_the_whole_new_version() -> None:
    result = merge_rewrite(PREVIOUS, _editor(PREVIOUS), NEW)
    assert result.recognized and result.kept == ()
    assert "Usługi płatności w Kafka." in result.html
    assert "System przesyłek w Javie." in result.html
    assert "Rozwój systemu śledzenia przesyłek." not in result.html


def test_role_edited_by_hand_stays_in_the_recruiters_version() -> None:
    draft = _editor(PREVIOUS).replace(
        "Rozwój systemu śledzenia przesyłek.", "Śledzenie przesyłek dla 40 magazynów."
    )
    result = merge_rewrite(PREVIOUS, draft, NEW)
    assert result.kept == ("Logistyka Przykład",)
    assert "Śledzenie przesyłek dla 40 magazynów." in result.html
    assert "System przesyłek w Javie." not in result.html
    # Reszta przyszła z nowej wersji, w kolejności nowej wersji.
    assert "Usługi płatności w Kafka." in result.html
    assert result.html.index("Bank Przykładowy") < result.html.index(
        "Logistyka Przykład"
    )


def test_section_edited_by_hand_stays() -> None:
    draft = _editor(PREVIOUS).replace("Angielski – B2", "Angielski – C1")
    result = merge_rewrite(PREVIOUS, draft, NEW)
    assert result.kept == ("Języki",)
    assert "Angielski – C1" in result.html


def test_bold_only_is_not_an_edit() -> None:
    draft = _editor(PREVIOUS).replace("Code review.", "<strong>Code review.</strong>")
    result = merge_rewrite(PREVIOUS, draft, NEW)
    assert result.kept == ()
    assert "Usługi płatności w Kafka." in result.html


def test_role_removed_by_hand_does_not_come_back() -> None:
    draft = _editor(PREVIOUS)
    start = draft.index(
        '<p class="job-head" data-cv-section="role"><strong>Java Developer'
    )
    end = draft.index('<p class="rodo">')
    draft = draft[:start] + draft[end:]
    result = merge_rewrite(PREVIOUS, draft, NEW)
    assert "Logistyka Przykład" not in result.html
    assert "Bank Przykładowy" in result.html


def test_paragraph_added_by_hand_stays_where_it_was() -> None:
    draft = _editor(PREVIOUS).replace(
        '<h2 data-cv-section="experience">',
        "<h2>CERTYFIKATY WŁASNE</h2><p>Kurs Kafki (fikcyjny).</p>"
        '<h2 data-cv-section="experience">',
    )
    result = merge_rewrite(PREVIOUS, draft, NEW)
    assert result.kept == ("Certyfikaty własne",)
    assert result.html.index("Kurs Kafki") < result.html.index("Bank Przykładowy")


def test_consent_clause_always_comes_from_the_new_version_at_the_end() -> None:
    result = merge_rewrite(PREVIOUS, _editor(PREVIOUS), NEW)
    assert result.html.rstrip().endswith("</p>")
    assert result.html.count('class="rodo"') == 1
    assert result.html.rindex('class="rodo"') > result.html.index("Logistyka Przykład")


def test_draft_not_from_the_generator_is_not_recognised() -> None:
    result = merge_rewrite("", "<p>CV wklejone z Worda.</p>", NEW)
    assert not result.recognized
    assert result.html == NEW


def test_everything_different_is_not_treated_as_hand_edits() -> None:
    # Np. zmiana sposobu składania HTML między generacjami — nie zostawiamy
    # wszystkiego „w wersji rekrutera”, bo nowa wersja nic by nie zmieniła.
    other = copy.deepcopy(PAYLOAD)
    other["why_points"] = ["Inny powód."]
    other["skills"] = [{"label": "Inne", "content": "Python"}]
    other["languages"] = ["Niemiecki – A2"]
    other["experience"][0]["responsibilities"] = ["Inne zadanie."]
    other["experience"][1]["responsibilities"] = ["Jeszcze inne zadanie."]
    result = merge_rewrite(PREVIOUS, _editor(_generated(other)), NEW)
    assert not result.recognized
    assert result.html == NEW
