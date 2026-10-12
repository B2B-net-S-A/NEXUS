import json

import pytest

from app.services.cv_editor_review import (
    editor_claims,
    EditorReviewInputError,
    verify_editor_content,
)
from app.services.cv_generator_b2b import factual_verification
from app.services.cv_generator_b2b.docx_renderer import TRANSLATIONS


def test_preserves_inline_negation_and_role_context_in_order():
    assert editor_claims(
        "<h2>Doświadczenie</h2><h3>Firma A — Junior</h3><p>Nie <strong>zarządzał</strong> zespołem.</p><p>3 lata w roli.</p>"
    ) == [
        "Firma A — Junior",
        "Nie zarządzał zespołem.",
        "3 lata w roli.",
    ]


def test_never_hides_excess_claims_or_unreviewed_image_content():
    for content in (
        "<p>fakt</p>" * 1001,
        '<img src="data:image/png;base64,AA=="><p>fakt</p>',
        "",
    ):
        with pytest.raises(EditorReviewInputError):
            editor_claims(content)


def test_table_cells_keep_a_boundary_and_do_not_join_numbers():
    assert editor_claims("<table><tr><td>3</td><td>lata</td></tr></table>") == [
        "3 | lata |"
    ]


# ── Recenzent dostaje twierdzenia ───────────────────────────────────────────
#
# Od 23.09 do 12.10.2026 kontrola po edycji nie sprawdzała niczego: linie
# edytora szły jako `why_points`, a recenzent (v4) nie traktuje tej sekcji
# jako twierdzeń, więc zatwierdzenie kończyło się
# `unverified/review_protocol_invalid_review` bez wywołania modelu (12 z 12 na
# produkcji). Żaden test tego nie widział, bo wszystkie podmieniały
# `verify_editor_content`. Te wołają je naprawdę, podmieniony jest tylko model.

# Kształt po zapisie w edytorze: bez klas, punkty jako `<li><p>`.
_EDITED_CV = (
    "<h1>Senior Java Developer – Anna Przykładowa</h1>"
    "<p><strong>Rozważany na stanowisko:</strong> Senior Java Developer</p><hr>"
    '<h2 data-cv-section="why_points">DLACZEGO NASZ KANDYDAT?</h2>'
    "<ul><li><p>Ponad 7 lat doświadczenia w Javie.</p></li></ul>"
    '<h2 data-cv-section="experience">DOŚWIADCZENIE</h2>'
    '<p data-cv-section="role"><strong>Senior Java Developer</strong> 03.2021 – 06.2024</p>'
    '<p data-cv-section="employer">Bank Przykładowy S.A.</p>'
    '<p data-cv-section="duties_label">Zakres zadań:</p>'
    "<ul><li><p>Rozwój mikroserwisów płatności w Java 17.</p></li></ul>"
    '<p data-cv-section="technologies">Technologie: Java 17, Spring Boot</p>'
    f'<p data-cv-section="rodo">{TRANSLATIONS["pl"]["rodo"]}</p>'
)


def _reviewer(monkeypatch) -> list[dict]:
    """Recenzent, który potwierdza każde podane twierdzenie pierwszą linią CV."""
    asked: list[dict] = []

    def review(content, request_id, system=None, **kwargs):
        payload = json.loads(content)
        asked.append(payload)
        return json.dumps(
            {
                "claims": [
                    {
                        "path": path,
                        "status": "supported",
                        "evidence": [{"source": "cv", "start_line": 1, "end_line": 1}],
                    }
                    for path in payload["claims"]
                ]
            }
        )

    monkeypatch.setattr(factual_verification, "analyze_with_ai", review)
    return asked


def _verify(content_html: str) -> dict:
    return verify_editor_content(
        content_html,
        cv_text="Źródłowe CV kandydatki\n",
        screening_notes="",
        identity="Anna Przykładowa",
        request_id="test",
    )


def test_edited_cv_reaches_the_reviewer_with_its_factual_lines(monkeypatch):
    asked = _reviewer(monkeypatch)

    report = _verify(_EDITED_CV)

    assert report["status"] == "verified"
    assert len(asked) == 1, "recenzent ma dostać dokładnie jedną paczkę twierdzeń"
    claims = asked[0]["claims"]
    assert list(claims.values()) == [
        "Senior Java Developer – Anna Przykładowa",
        "Senior Java Developer 03.2021 – 06.2024",
        "Bank Przykładowy S.A.",
        "Rozwój mikroserwisów płatności w Java 17.",
        "Technologie: Java 17, Spring Boot",
    ]
    # Cały dokument zostaje kontekstem: narracja nie jest twierdzeniem, ale
    # recenzent ją widzi, a ścieżka twierdzenia wskazuje linię dokumentu.
    document = asked[0]["final_document"]["why_points"]
    assert "Ponad 7 lat doświadczenia w Javie." in document
    for path, text in claims.items():
        assert document[int(path.rsplit("/", 1)[1])] == text


def test_headings_without_markers_still_separate_the_narrative(monkeypatch):
    """Starsze CV i import z Worda nie mają znaczników sekcji — tytuły z szablonu
    (PL/EN) i pierwsze słowa klauzuli wystarczą."""
    asked = _reviewer(monkeypatch)

    _verify(
        "<p><b>Considered for:</b> Developer</p>"
        "<h2>WHY OUR CANDIDATE?</h2><ul><li>Strong fit for the role.</li></ul>"
        "<h2>EXPERIENCE</h2><p><b>Developer</b> 2020 – 2022</p><p>Acme Ltd</p>"
        "<p>Tasks:</p><ul><li>Built payment APIs.</li></ul>"
        f"<p>{TRANSLATIONS['en']['rodo']}</p>"
    )

    assert list(asked[0]["claims"].values()) == [
        "Developer 2020 – 2022",
        "Acme Ltd",
        "Built payment APIs.",
    ]


def test_cv_with_nothing_to_verify_is_a_protocol_failure_not_a_pass(monkeypatch):
    asked = _reviewer(monkeypatch)

    with pytest.raises(factual_verification.FactualVerificationError) as error:
        _verify('<h2 data-cv-section="why_points">Podsumowanie</h2><p>Świetny.</p>')

    assert error.value.paths == [] and asked == []
