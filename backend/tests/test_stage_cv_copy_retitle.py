"""Nagłówek CV kopiowanego z innej rekrutacji (bez bazy, bez AI).

12.10.2026: kopia CV etapu bierze treść PO poprawkach rekrutera, więc nie da
się jej wyrenderować od nowa z danych generatora — tytuł rekrutacji źródłowej
(bywa w nim numer zapytania innego klienta) trzeba podmienić w gotowym HTML.
Testy pilnują, że zmienia się wyłącznie nagłówek: pierwsze ``<h1>`` i linia
„Rozważany na stanowisko”, a reszta dokumentu wychodzi bez zmian.
"""

from __future__ import annotations

from app.services import dz_review as dz
from app.services.html_sanitizer import sanitize_cv_html
from app.services.stage_cv_copy import retitle_copied_html

BODY = (
    '<h2 data-cv-section="why_points">DLACZEGO NASZ KANDYDAT?</h2>'
    "<ul><li>5 lat w <strong>Python</strong></li><li>R&amp;D w banku</li></ul>"
    '<h2 data-cv-section="experience">DOŚWIADCZENIE</h2>'
    '<p data-cv-section="role">01.2020 - 06.2024</p>'
    '<p data-cv-section="employer">Nazwa firmy: <strong>Firma Testowa</strong></p>'
    '<p class="rodo">Wyrażam zgodę na przetwarzanie moich danych osobowych.</p>'
)
GENERATOR = (
    '<article class="cv"><h1>Tester QA (ZAP-1/2026) – Anna Testowa</h1>'
    '<p class="considered"><b>Rozważany na stanowisko:</b> Tester QA</p><hr>'
    f"{BODY}</article>"
)


def _body_blocks(html: str) -> list[tuple[str, str]]:
    return [(b.kind, b.text) for b in dz.html_blocks(html)[1:]]


def test_generator_header_gets_the_target_title_and_keeps_the_name():
    out = retitle_copied_html(GENERATOR, title="Python Developer", blind=False)

    assert "<h1>Python Developer – Anna Testowa</h1>" in out
    assert "ZAP-1/2026" not in out


def test_considered_for_line_is_removed_in_both_languages_even_without_its_class():
    polish = retitle_copied_html(GENERATOR, title="Python Developer", blind=False)
    english = retitle_copied_html(
        "<h1>QA Engineer – Anna Testowa</h1>"
        "<p><strong>Considered for:</strong> QA Engineer</p>" + BODY,
        title="Python Developer",
        blind=False,
    )

    assert "Rozważany na stanowisko" not in polish
    assert "Considered for" not in english
    assert "QA Engineer" not in english


def test_blind_header_is_replaced_whole_and_never_gains_a_name():
    out = retitle_copied_html(
        "<h1>Tester QA – automatyzacja</h1>" + BODY,
        title="Python Developer",
        blind=True,
        fallback_name="Anna Testowa",
    )

    assert "<h1>Python Developer</h1>" in out
    assert "Anna Testowa" not in out


def test_header_attributes_survive_and_inline_marks_are_flattened():
    # Treść szkicu jest już po sanitizerze (zapis edytora) — taka wchodzi.
    source = sanitize_cv_html(
        '<h1 style="text-align: center"><strong>Tester QA</strong> – Anna Testowa</h1>'
        + BODY
    )

    out = retitle_copied_html(source, title="Python Developer", blind=False)

    assert out.startswith(source[: source.index(">") + 1])
    assert ">Python Developer – Anna Testowa</h1>" in out
    assert "<strong>Tester QA</strong>" not in out


def test_title_is_escaped():
    out = retitle_copied_html(GENERATOR, title="R&D <Lead>", blind=False)

    assert "<h1>R&amp;D &lt;Lead&gt; – Anna Testowa</h1>" in out


def test_name_is_taken_after_the_last_separator_whatever_the_dash():
    for header in (
        "Developer - Java - Anna Testowa",
        "Developer – Java — Anna Testowa",
    ):
        out = retitle_copied_html(
            f"<h1>{header}</h1>" + BODY, title="Python Developer", blind=False
        )
        assert "<h1>Python Developer – Anna Testowa</h1>" in out


def test_header_without_a_separator_takes_the_fallback_name():
    html = "<h1>Anna T.</h1>" + BODY

    named = retitle_copied_html(
        html, title="Python Developer", blind=False, fallback_name="Anna Testowa"
    )
    bare = retitle_copied_html(html, title="Python Developer", blind=False)

    assert "<h1>Python Developer – Anna Testowa</h1>" in named
    assert "<h1>Python Developer</h1>" in bare


def test_document_without_h1_or_without_a_title_is_returned_unchanged():
    without_header = "<p><b>Rozważany na stanowisko:</b> Tester QA</p>" + BODY

    assert (
        retitle_copied_html(without_header, title="Python Developer", blind=False)
        == without_header
    )
    assert retitle_copied_html("<h1></h1>" + BODY, title="X", blind=False) == (
        "<h1></h1>" + BODY
    )
    assert retitle_copied_html(GENERATOR, title="  ", blind=False) == GENERATOR


def test_only_the_first_h1_and_only_the_header_zone_are_touched():
    html = (
        "<h1>Tester QA – Anna Testowa</h1>"
        '<h2 data-cv-section="experience">DOŚWIADCZENIE</h2>'
        "<p><b>Considered for:</b> a promotion in 2022</p>"
        "<h1>Drugi nagłówek – bez zmian</h1>"
    )

    out = retitle_copied_html(html, title="Python Developer", blind=False)

    assert "<h1>Python Developer – Anna Testowa</h1>" in out
    assert "<p><b>Considered for:</b> a promotion in 2022</p>" in out
    assert "<h1>Drugi nagłówek – bez zmian</h1>" in out


def test_body_survives_and_the_result_is_stable_under_the_sanitizer():
    source = sanitize_cv_html(GENERATOR)

    out = retitle_copied_html(source, title="Python Developer", blind=False)

    assert sanitize_cv_html(out) == out
    # Bez linii „Rozważany…” treść pod nagłówkiem jest ta sama, blok po bloku.
    assert _body_blocks(out) == _body_blocks(source)[1:]
    assert 'data-cv-section="employer"' in out
    assert 'class="rodo"' in out
    assert "R&amp;D w banku" in out
