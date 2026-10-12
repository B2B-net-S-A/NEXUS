"""Klauzula zgody RODO jest stała także po stronie serwera (D3, 12.10.2026).

Edytor blokuje ją w przeglądarce, ale zapis przychodzi też ze starych kart
i z API — ``keep_rodo_clause`` przywraca klauzulę z zapisanego CV, zanim
treść trafi do szkicu albo do zatwierdzonej wersji.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.schemas.candidate_stage_cv import CVBrandedReview
from app.services import cv_approval_queue as queue
from app.services import cv_generated_editor as editor
from app.services.cv_generator_b2b.docx_renderer import TRANSLATIONS
from app.services.cv_rodo_clause import keep_rodo_clause

CLAUSE = TRANSLATIONS["pl"]["rodo"]
BODY = "<h1>Dev</h1><p>Opis.</p>"
# Zapisane CV jest po sanitizerze — stąd średnik w stylu.
SAVED = f'{BODY}<p data-cv-section="rodo" style="font-size: 8pt;">{CLAUSE}</p>'


def _draft(html: str = SAVED):
    return SimpleNamespace(
        id=5,
        generated_document_id=7,
        edit_revision=2,
        branded_version=1,
        branded_status="draft",
        branded_draft_html=html,
        branded_template_content=b"template",
        branded_consent_content=None,
        branded_render_metadata={},
        branded_language="pl",
        branded_template="standard",
        branded_docx_filename="cv.docx",
    )


def test_untouched_clause_returns_the_submitted_html_byte_for_byte():
    incoming = f'<h1>Dev</h1><p>Nowy  opis &amp; więcej.</p><p data-cv-section="rodo">{CLAUSE}</p>'
    assert keep_rodo_clause(SAVED, incoming) is incoming


def test_deleted_clause_comes_back_at_the_end():
    result = keep_rodo_clause(SAVED, "<h1>Dev</h1><p>Nowy opis.</p>")
    assert result.startswith("<h1>Dev</h1><p>Nowy opis.</p>")
    assert result.endswith(
        f'<p data-cv-section="rodo" style="font-size: 8pt;">{CLAUSE}</p>'
    )


@pytest.mark.parametrize(
    "edited",
    [
        CLAUSE.replace("B2B.net S.A.", "Inną Firmę"),
        CLAUSE[:80],
        CLAUSE + " Dopisek rekrutera.",
    ],
)
def test_edited_clause_is_replaced_by_the_saved_one(edited):
    result = keep_rodo_clause(SAVED, f'{BODY}<p data-cv-section="rodo">{edited}</p>')
    assert result.count("Wyrażam zgodę") == 1
    assert result.endswith(
        f'<p data-cv-section="rodo" style="font-size: 8pt;">{CLAUSE}</p>'
    )


def test_other_text_carrying_the_marker_stays_in_the_body_without_it():
    # Enter pod klauzulą w starym edytorze kopiował znacznik na nowy akapit;
    # generator DOCX przypiąłby wtedy na dole pierwszy oznaczony akapit.
    incoming = (
        f'{BODY}<p data-cv-section="rodo" class="rodo x">Dostępna od listopada.</p>'
    )
    result = keep_rodo_clause(SAVED, incoming)
    assert '<p class="x">Dostępna od listopada.</p>' in result
    assert result.count('data-cv-section="rodo"') == 1
    assert result.endswith(f"{CLAUSE}</p>")


def test_marked_text_above_an_intact_clause_loses_the_marker_only():
    incoming = (
        f'{BODY}<p data-cv-section="rodo">Notatka.</p>'
        f'<p data-cv-section="rodo">{CLAUSE}</p>'
    )
    result = keep_rodo_clause(SAVED, incoming)
    assert result == f'{BODY}<p>Notatka.</p><p data-cv-section="rodo">{CLAUSE}</p>'


def test_generator_clause_without_marker_is_recognised_and_kept():
    saved = f'{BODY}<p class="rodo">{CLAUSE}</p>'
    assert keep_rodo_clause(saved, f"{BODY}<p>{CLAUSE}</p>") == f"{BODY}<p>{CLAUSE}</p>"
    assert keep_rodo_clause(saved, BODY) == f'{BODY}<p class="rodo">{CLAUSE}</p>'


@pytest.mark.parametrize("saved", [None, "", "<h1>Dev</h1><p>CV bez klauzuli.</p>"])
def test_cv_saved_without_a_clause_accepts_any_content(saved):
    incoming = "<p>Treść</p>"
    assert keep_rodo_clause(saved, incoming) is incoming


@pytest.mark.parametrize("blank", ["", "  \n"])
def test_blank_content_stays_blank_so_the_caller_can_refuse_it(blank):
    assert keep_rodo_clause(SAVED, blank) is blank
    with pytest.raises(HTTPException) as refused:
        editor.save(_draft(), 2, blank)
    assert refused.value.status_code == 422


def test_clause_text_inside_a_list_is_not_the_clause():
    incoming = f"{BODY}<ul><li><p>{CLAUSE}</p></li></ul>"
    result = keep_rodo_clause(SAVED, incoming)
    assert result.startswith(incoming)
    assert result.endswith(
        f'<p data-cv-section="rodo" style="font-size: 8pt;">{CLAUSE}</p>'
    )


def test_generated_editor_save_keeps_the_clause():
    item = _draft()
    editor.save(item, 2, "<h1>Dev</h1><p>Po edycji.</p>")
    assert item.branded_draft_html.startswith("<h1>Dev</h1><p>Po edycji.</p>")
    assert CLAUSE in item.branded_draft_html
    assert item.edit_revision == 3


async def test_generated_editor_approves_and_reviews_content_with_the_clause(
    monkeypatch,
):
    item = _draft()
    db = SimpleNamespace(
        add=Mock(), flush=AsyncMock(), get=AsyncMock(return_value=None)
    )
    render = AsyncMock(return_value=b"docx")
    review = AsyncMock(return_value={"status": "verified"})
    monkeypatch.setattr(editor, "render", render)
    monkeypatch.setattr(editor, "review_for_approval", review)
    edited = CLAUSE.replace("B2B.net S.A.", "Inną Firmę")
    version = await editor.finalize(
        db, item, 2, f'{BODY}<p data-cv-section="rodo">{edited}</p>', 9
    )
    assert "Inną Firmę" not in version.content_html
    assert CLAUSE in version.content_html
    # Word i kontrola treści dostają to samo, co zostaje zatwierdzone.
    assert render.await_args.args[1] == version.content_html
    assert review.await_args.args[2] == version.content_html
    assert item.branded_draft_html == version.content_html


def test_clause_rewritten_as_a_div_is_replaced_too():
    # Generator Worda bierze `div` bez bloków w środku za akapit i przypiąłby
    # go na dole jako klauzulę.
    tampered = "<div>Wyrażam zgodę na przetwarzanie moich danych — ZMIENIONE</div>"
    result = keep_rodo_clause(SAVED, BODY + tampered)
    assert "ZMIENIONE" not in result
    assert result.count("Wyrażam zgodę") == 1
    assert result.endswith(f"{CLAUSE}</p>")


def test_other_text_in_a_div_with_the_clause_class_loses_the_class():
    result = keep_rodo_clause(
        SAVED, f'{BODY}<div class="rodo">Dostępna od zaraz.</div>'
    )
    assert "<div>Dostępna od zaraz.</div>" in result
    assert result.count("rodo") == 1
    assert result.endswith(f"{CLAUSE}</p>")


def test_text_before_the_first_block_stays_text_when_the_clause_is_restored():
    incoming = '&lt;a href="https://example.com/x"&gt;klik&lt;/a&gt; opis<p>Treść</p>'
    result = keep_rodo_clause(SAVED, incoming)
    assert "<a " not in result
    assert result.startswith("&lt;a href=")
    assert result.endswith(f"{CLAUSE}</p>")


async def test_ai_review_checks_the_content_that_approval_will_store(monkeypatch):
    """Kontrola liczona z treści bez klauzuli, a zatwierdzenie z przywróconą,
    nigdy by się nie spotkały: zatwierdzenie szuka wyniku kontroli po skrócie
    treści i odpowiadało 409 „Uruchom kontrolę” bez końca."""
    prepare = AsyncMock(return_value={"status": "verified"})
    monkeypatch.setattr(queue, "prepare_approval_review", prepare)
    db = AsyncMock()
    db.scalar.return_value = None
    db.add = Mock()
    payload = CVBrandedReview(
        expected_revision=2, content_html=BODY, request_key=uuid4()
    )
    await queue.enqueue_review(db, _draft(), payload, 7)
    reviewed = prepare.await_args.args[2]

    monkeypatch.setattr(editor, "render", AsyncMock(return_value=b"docx"))
    monkeypatch.setattr(
        editor, "review_for_approval", AsyncMock(return_value={"status": "verified"})
    )
    store = SimpleNamespace(
        add=Mock(), flush=AsyncMock(), get=AsyncMock(return_value=None)
    )
    version = await editor.finalize(store, _draft(), 2, BODY, 9)
    assert reviewed == version.content_html
    assert CLAUSE in reviewed


async def test_word_preview_renders_the_content_that_approval_will_store(monkeypatch):
    from app.services import candidate_stage_cv_service as stage_service
    from app.services import cv_approved_docx

    rendered = []

    def fake_render(content_html, *_args, **_kwargs):
        rendered.append(content_html)
        return b"docx"

    monkeypatch.setattr(editor, "render_approved_docx", fake_render)
    monkeypatch.setattr(cv_approved_docx, "render_approved_docx", fake_render)
    await editor.render(_draft(), BODY)
    await stage_service.render_stage_editor_docx(_draft(), BODY)
    expected = keep_rodo_clause(SAVED, BODY)
    assert rendered == [expected, expected]


def _pinned_in_word(content_html: str) -> str:
    """Tekst, który generator Worda przypina na dole strony jako klauzulę."""
    import re
    import zipfile
    from io import BytesIO

    from app.services.cv_approved_docx import render_approved_docx
    from app.services.cv_document_assets import default_template

    docx = render_approved_docx(content_html, default_template())
    xml = zipfile.ZipFile(BytesIO(docx)).read("word/document.xml").decode()
    boxes = re.findall(r"<w:txbxContent>(.*?)</w:txbxContent>", xml, re.S)
    return " | ".join(
        "".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", box)) for box in boxes
    )


_PIXEL = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="


@pytest.mark.parametrize(
    "decoy",
    [
        # Prawdziwa klauzula schowana tam, skąd Word jej nie przypina…
        f'<blockquote><p data-cv-section="rodo">{CLAUSE}</p></blockquote><p class="rodo">INNA KLAUZULA</p>',
        f'<table><tbody><tr><td><p data-cv-section="rodo">{CLAUSE}</p></td></tr></tbody></table>'
        '<p class="rodo">INNA KLAUZULA</p>',
        f'<p data-cv-section="rodo">{CLAUSE}<img src="{_PIXEL}"></p><p class="rodo">INNA KLAUZULA</p>',
        # …pusty albo zagnieżdżony blok z klasą klauzuli przed prawdziwą (Word
        # przypina pierwszy taki blok — pusty zostawiał stronę bez klauzuli)…
        f'<div class="rodo"></div><p data-cv-section="rodo">{CLAUSE}</p>',
        '<div class="rodo"><div class="rodo">Wyrażam zgodę na przetwarzanie moich danych — INNA KLAUZULA</div></div>'
        f'<p data-cv-section="rodo">{CLAUSE}</p>',
        # …albo cudza jako luźny tekst przed prawdziwą.
        f"Wyrażam zgodę na przetwarzanie moich danych — INNA KLAUZULA<p>{CLAUSE}</p>",
        f'<p>x</p>Wyrażam zgodę na przetwarzanie moich danych — INNA KLAUZULA<p data-cv-section="rodo">{CLAUSE}</p>',
    ],
)
def test_word_pins_the_saved_clause_whatever_the_request_hides_or_adds(decoy):
    from app.services.html_sanitizer import sanitize_cv_html

    guarded = keep_rodo_clause(SAVED, sanitize_cv_html(BODY + decoy))
    pinned = _pinned_in_word(guarded)
    assert CLAUSE[:60] in pinned
    assert "INNA KLAUZULA" not in pinned
    assert pinned.count("Wyrażam zgodę") == 1


def test_saved_clause_the_word_renderer_would_not_pin_is_not_protected():
    # Stare CV z klauzulą w cytacie: Word jej nie przypina, więc nie ma czego
    # przywracać — treść przechodzi bez zmian.
    saved = f"{BODY}<blockquote><p>{CLAUSE}</p></blockquote>"
    incoming = "<p>Nowa treść</p>"
    assert keep_rodo_clause(saved, incoming) is incoming


@pytest.mark.parametrize(
    "hostile",
    [
        "\x0cabc<p>x</p>",
        f"<p>{CLAUSE[:50]} xx</p>\x0cabc<p>b</p>",
        "<p>b</p>\x0cogon",
        # Odwołania liczbowe bleach zostawia jako tekst — dekoduje je dopiero lxml.
        "&#12;abc<p>x</p>",
        "&#x0B;abc<p>x</p>",
        "<p>a</p>&#xFFFE;b&#0;c",
    ],
)
def test_characters_lxml_rejects_do_not_break_saving(hostile):
    from app.services.html_sanitizer import sanitize_cv_html

    cleaned = sanitize_cv_html(hostile)
    assert "\x0c" not in cleaned and "&#" not in cleaned
    assert keep_rodo_clause(SAVED, cleaned).endswith(f"{CLAUSE}</p>")
    # Zapisana, nie może zablokować następnego zapisu (500 przed tą zmianą).
    assert keep_rodo_clause(cleaned, "<p>Nowa treść</p>").startswith("<p>Nowa treść</p>")


def test_ordinary_numeric_references_survive_sanitizing():
    from app.services.html_sanitizer import sanitize_cv_html

    assert (
        sanitize_cv_html("<p>Krak&#243;w &#x2013; &#9;tab</p>")
        == "<p>Krak&#243;w &#x2013; &#9;tab</p>"
    )


@pytest.mark.parametrize(
    "stored",
    [
        "\x0cabc<p>x</p>",
        "<html></html>",
        "<!DOCTYPE html>",
        "<html><head></head></html>",
    ],
)
def test_unreadable_saved_cv_can_still_be_overwritten(stored):
    # Treść zapisana przed tą zmianą nie może zablokować CV na zawsze.
    incoming = f"<p>Nowa treść</p><p>{CLAUSE}</p>"
    assert keep_rodo_clause(stored, incoming) is incoming
