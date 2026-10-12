"""Dane panelu „Do poprawy” w edytorze CV (Edytor CV 2, PR 2).

Kontrola AI po edycji zapisuje tylko wskaźniki (`/why_points/<i>`) i statusy;
panel potrzebuje TEKSTU linii, żeby pokazać uwagę przy właściwym miejscu
w CV. Tekst odtwarzamy z treści, która była sprawdzana — tylko gdy to ta sama
treść i ta sama wersja podziału na linie. Funkcja nigdy nie rzuca: panel jest
dodatkiem, nie warunkiem otwarcia edytora.
"""

import hashlib

import pytest

from app.services.cv_editor_issues import generator_warnings, review_findings
from app.services.cv_editor_review import EDITOR_REVIEW_VERSION, editor_claims

HTML = (
    "<h1>Dev – Anna P.</h1>"
    '<h2 data-cv-section="why_points">DLACZEGO NASZ KANDYDAT?</h2>'
    "<ul><li><p>7 lat w Javie.</p></li></ul>"
    '<h2 data-cv-section="experience">DOŚWIADCZENIE</h2>'
    '<p data-cv-section="role"><strong>Senior Dev</strong> 2021 – 2024</p>'
    '<p data-cv-section="employer">Acme Bank</p>'
    '<p data-cv-section="duties_label">Zakres zadań:</p>'
    "<ul><li><p>Rozwój usług w Java.</p></li><li><p>Migracja do Kubernetes.</p></li></ul>"
)


def _receipt(html: str, paths: dict[str, str], **over) -> dict:
    return {
        "status": "reviewed",
        "method": "edited_source_review",
        "html_sha256": hashlib.sha256(html.encode()).hexdigest(),
        "editor_review_version": EDITOR_REVIEW_VERSION,
        "findings": {
            "reason": "unsupported_claims",
            "count": len(paths),
            "paths": list(paths),
            "statuses": paths,
        },
        **over,
    }


def _path(text: str) -> str:
    return f"/why_points/{editor_claims(HTML).index(text)}"


def test_findings_carry_the_text_of_the_line_they_point_at():
    receipt = _receipt(
        HTML,
        {
            _path("Migracja do Kubernetes."): "unsupported",
            _path("Senior Dev 2021 – 2024"): "contradicted",
        },
    )
    assert review_findings(receipt, HTML) == {
        "status": "reviewed",
        "findings": [
            {"text": "Migracja do Kubernetes.", "status": "unsupported"},
            {"text": "Senior Dev 2021 – 2024", "status": "contradicted"},
        ],
    }


def test_clean_review_has_a_status_and_no_findings():
    assert review_findings(
        {**_receipt(HTML, {}), "status": "verified", "findings": None}, HTML
    ) == {
        "status": "verified",
        "findings": [],
    }


@pytest.mark.parametrize(
    "receipt",
    [
        _receipt(HTML + "<p>dopisek</p>", {"/why_points/3": "unsupported"}),
        _receipt(
            HTML,
            {"/why_points/3": "unsupported"},
            editor_review_version=EDITOR_REVIEW_VERSION - 1,
        ),
        _receipt(
            HTML,
            {"/why_points/999": "unsupported", "/inne/1": "unsupported", "śmieci": "x"},
        ),
    ],
    ids=["inna-treść", "inna-wersja-podziału", "wskaźniki-spoza-treści"],
)
def test_findings_that_cannot_be_tied_to_this_text_are_left_out(receipt):
    assert review_findings(receipt, HTML) == {"status": "reviewed", "findings": []}


@pytest.mark.parametrize(
    "receipt",
    [
        None,
        "tekst",
        [],
        {},
        {"status": "dziwny"},
        {"status": "reviewed", "findings": "x"},
    ],
)
def test_broken_receipt_never_raises(receipt):
    result = review_findings(receipt, HTML)
    assert result["findings"] == []
    assert result["status"] in (None, "reviewed")


@pytest.mark.parametrize("status", [["reviewed"], {"a": 1}, 7, None])
def test_status_of_a_wrong_type_is_no_status(status):
    """Lista albo słownik w miejscu statusu nie da się sprawdzić w zbiorze."""
    receipt = {**_receipt(HTML, {"/why_points/0": "unsupported"}), "status": status}
    assert review_findings(receipt, HTML)["status"] is None


def test_absurd_line_index_is_ignored():
    """Indeks na tysiące cyfr nie zamienia się w liczbę (limit Pythona 3.11+)."""
    receipt = _receipt(HTML, {"/why_points/" + "9" * 5000: "unsupported"})
    assert review_findings(receipt, HTML)["findings"] == []


def test_review_without_content_keeps_only_the_status():
    assert review_findings(_receipt(HTML, {"/why_points/0": "unsupported"}), None) == {
        "status": "reviewed",
        "findings": [],
    }


def test_generator_warnings_are_plain_strings_only():
    assert generator_warnings(
        ["MUST-HAVE: Kafka — brak w CV", "  ", None, 7, {"a": 1}, "x" * 2000]
    ) == [
        "MUST-HAVE: Kafka — brak w CV",
        "x" * 500,
    ]
    assert generator_warnings(None) == []
    assert generator_warnings("tekst") == []
    assert len(generator_warnings([f"uwaga {i}" for i in range(500)])) == 100
