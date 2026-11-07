"""Co człowiek zmienił w CV z generatora — wpis przy zatwierdzeniu (E3, 07.11.2026).

Start edytora jest zapisany w metadanych szkicu, a zatwierdzenie liczy różnice
per część CV. W wpisie są wyłącznie nazwy części i liczby: zapis nie może
zatrzymać zatwierdzenia ani wynieść treści CV.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
import json
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.services import cv_edit_summary
from app.services.cv_approval_provenance import capture_editor_origin
from app.services.cv_edit_summary import (
    ACTION,
    START_HTML_KEY,
    STATUS_BOLD_ONLY,
    STATUS_CHANGED,
    STATUS_UNCHANGED,
    cv_blocks,
    log_approved_edits,
    summarize_edits,
)

# Kształt jak z generatora (`html_export.render_interactive_html`).
GENERATED = (
    '<article class="cv"><h1>Analityk danych — Ewa Fikcyjna</h1>'
    '<p class="considered"><b>Rozważany na stanowisko:</b> Starszy analityk</p><hr>'
    '<h2 data-cv-section="why_points">Dlaczego ten kandydat</h2>'
    "<ul><li>Siedem lat w analizie danych</li><li>Prowadziła migracje hurtowni</li></ul>"
    '<h2 data-cv-section="skills">Umiejętności</h2>'
    '<p class="skill"><b>SQL</b>, Python, dbt</p>'
    '<h2 data-cv-section="languages">Języki</h2><p>Angielski - C1</p>'
    '<h2 data-cv-section="experience">Doświadczenie</h2>'
    '<div class="job" id="exp-0">'
    '<p class="job-head" data-cv-section="role"><b>Analityk</b> '
    '<span class="job-dates">01.2020 – obecnie</span></p>'
    '<p class="job-co" data-cv-section="employer">Fikcyjna Sp. z o.o.</p>'
    '<p class="lbl" data-cv-section="duties_label">Zakres zadań:</p>'
    "<ul><li>Modele danych w hurtowni</li><li>Raporty dla zarządu</li></ul>"
    '<p class="lbl" data-cv-section="technologies">Technologie: '
    '<span class="tech">SQL, dbt</span></p></div>'
    '<div class="job" id="exp-1">'
    '<p class="job-head" data-cv-section="role"><b>Młodszy analityk</b> '
    '<span class="job-dates">01.2018 – 12.2019</span></p>'
    '<p class="job-co" data-cv-section="employer">Inna Fikcyjna S.A.</p>'
    "<ul><li>Zestawienia sprzedaży</li></ul></div>"
    '<p class="rodo">Wyrażam zgodę na przetwarzanie moich danych osobowych</p>'
    "</article>"
)


def _editor(html: str) -> str:
    """To samo CV po przejściu przez Tiptapa: płaskie, bez klas i opakowań."""
    return (
        html.replace('<article class="cv">', "")
        .replace("</article>", "")
        .replace('<div class="job" id="exp-0">', "")
        .replace('<div class="job" id="exp-1">', "")
        .replace("</div>", "")
        .replace(' class="considered"', "")
        .replace(' class="skill"', "")
        .replace(' class="job-head"', "")
        .replace(' class="job-co"', "")
        .replace(' class="lbl"', "")
        .replace("<li>", "<li><p>")
        .replace("</li>", "</p></li>")
        .replace(
            '<p class="rodo">', '<p data-cv-section="rodo" contenteditable="false">'
        )
    )


def test_blocks_are_split_into_the_parts_of_the_measurement():
    parts = [part for part, _text, _bold in cv_blocks(GENERATED)]
    assert parts == [
        "title",
        "considered_for",
        "headings",
        "why_points",
        "why_points",
        "headings",
        "skills",
        "headings",
        "languages",
        "headings",
        "role",
        "employer",
        "headings",
        "duties",
        "duties",
        "technologies",
        "role",
        "employer",
        "duties",
    ]


def test_untouched_cv_is_unchanged_even_after_the_editor_rewrites_tags():
    summary = summarize_edits(GENERATED, _editor(GENERATED))
    assert summary["status"] == STATUS_UNCHANGED
    assert summary["parts"] == {} and summary["changed_parts"] == []
    assert summary["blocks_before"] == summary["blocks_after"] == 19
    assert summary["reordered"] is False


def test_bold_only_is_its_own_status():
    approved = _editor(GENERATED).replace(
        "<p>Modele danych w hurtowni</p>", "<p>Modele danych w <b>hurtowni</b></p>"
    )
    summary = summarize_edits(GENERATED, approved)
    assert summary["status"] == STATUS_BOLD_ONLY
    assert summary["parts"] == {
        "duties": {"added": 0, "removed": 0, "changed": 0, "bold": 1}
    }
    assert summary["changed_parts"] == [] and summary["bold_parts"] == ["duties"]


def test_text_changes_are_counted_per_part():
    approved = (
        _editor(GENERATED)
        # podsumowanie: jeden punkt przepisany, jeden dopisany
        .replace("Siedem lat w analizie danych", "Ponad siedem lat w analizie")
        .replace(
            "<li><p>Prowadziła migracje hurtowni</p></li>",
            "<li><p>Prowadziła migracje hurtowni</p></li><li><p>Nowy punkt</p></li>",
        )
        # obowiązki: jeden usunięty
        .replace("<li><p>Raporty dla zarządu</p></li>", "")
        # technologie i tytuł zmienione
        .replace("SQL, dbt</span>", "SQL, dbt, Airflow</span>")
        .replace("Analityk danych — Ewa", "Starszy analityk danych — Ewa")
    )
    summary = summarize_edits(GENERATED, approved)
    assert summary["status"] == STATUS_CHANGED
    assert summary["parts"] == {
        "why_points": {"added": 1, "removed": 0, "changed": 1, "bold": 0},
        "duties": {"added": 0, "removed": 1, "changed": 0, "bold": 0},
        "technologies": {"added": 0, "removed": 0, "changed": 1, "bold": 0},
        "title": {"added": 0, "removed": 0, "changed": 1, "bold": 0},
    }
    assert summary["changed_parts"] == ["duties", "technologies", "title", "why_points"]


def test_removed_role_counts_role_employer_and_duties():
    start = _editor(GENERATED)
    cut = start.index('<p data-cv-section="role"><b>Młodszy')
    approved = start[:cut] + start[start.index('<p data-cv-section="rodo"') :]
    summary = summarize_edits(GENERATED, approved)
    assert summary["status"] == STATUS_CHANGED
    assert summary["parts"] == {
        "role": {"added": 0, "removed": 1, "changed": 0, "bold": 0},
        "employer": {"added": 0, "removed": 1, "changed": 0, "bold": 0},
        "duties": {"added": 0, "removed": 1, "changed": 0, "bold": 0},
    }


def test_reordered_blocks_are_a_change_without_part_counts():
    approved = _editor(GENERATED).replace(
        "<li><p>Siedem lat w analizie danych</p></li>"
        "<li><p>Prowadziła migracje hurtowni</p></li>",
        "<li><p>Prowadziła migracje hurtowni</p></li>"
        "<li><p>Siedem lat w analizie danych</p></li>",
    )
    summary = summarize_edits(GENERATED, approved)
    assert summary["status"] == STATUS_CHANGED
    assert summary["reordered"] is True and summary["parts"] == {}


def test_consent_clause_is_not_counted():
    approved = _editor(GENERATED).replace(
        "Wyrażam zgodę na przetwarzanie moich danych osobowych",
        "Wyrażam zgodę na przetwarzanie danych osobowych przez firmę",
    )
    assert summarize_edits(GENERATED, approved)["status"] == STATUS_UNCHANGED


def test_summary_carries_no_cv_text():
    approved = _editor(GENERATED).replace("Raporty dla zarządu", "Tajny projekt X")
    dumped = json.dumps(summarize_edits(GENERATED, approved), ensure_ascii=False)
    for text in ("Ewa", "Fikcyjna", "Raporty", "Tajny", "hurtowni", "SQL"):
        assert text not in dumped


def test_cost_is_linear_on_the_largest_content():
    # ~500 KB: tyle mieści `content_html` (limity sanitizera).
    items = "".join(f"<li>Obowiązek numer {i} w projekcie</li>" for i in range(12000))
    start = f'<h2 data-cv-section="experience">Doświadczenie</h2><ul>{items}</ul>'
    approved = start.replace("numer 1 ", "numer jeden ")
    assert len(start) > 400_000
    began = time.perf_counter()
    summary = summarize_edits(start, approved)
    assert time.perf_counter() - began < 5
    assert summary["parts"]["duties"]["changed"] == 1


def test_editor_origin_keeps_the_start_content():
    metadata = capture_editor_origin(GENERATED, {"name": "Ewa Fikcyjna"})
    assert metadata[START_HTML_KEY] == GENERATED


# ── zapis wpisu ─────────────────────────────────────────────────────────────


def _session(*, fail: bool = False):
    @asynccontextmanager
    async def begin_nested():
        yield
        if fail:
            raise RuntimeError("insert failed")

    return SimpleNamespace(add=Mock(), begin_nested=begin_nested)


CSV = SimpleNamespace(id=5, candidate_stage_id=8, job_id=13, generated_document_id=21)


async def _log(db, *, metadata, approved=None):
    await log_approved_edits(
        db,
        csv=CSV,
        approved_html=approved if approved is not None else _editor(GENERATED),
        metadata=metadata,
        user_id=7,
        document_version_id=34,
        version=2,
    )


async def test_approval_writes_one_entry_with_numbers_only():
    db = _session()
    await _log(db, metadata={START_HTML_KEY: GENERATED})
    (entry,) = (call.args[0] for call in db.add.call_args_list)
    assert (entry.entity_type, entry.entity_id) == ("candidate_stage_cv", 5)
    assert (entry.action, entry.user_id) == (ACTION, 7)
    assert entry.details["status"] == STATUS_UNCHANGED
    assert {
        key: entry.details[key]
        for key in (
            "candidate_stage_id",
            "job_id",
            "document_version_id",
            "version",
            "generated_document_id",
            "origin",
        )
    } == {
        "candidate_stage_id": 8,
        "job_id": 13,
        "document_version_id": 34,
        "version": 2,
        "generated_document_id": 21,
        "origin": "generator",
    }


async def test_copy_from_another_recruitment_is_marked():
    db = _session()
    await _log(
        db, metadata={START_HTML_KEY: GENERATED, "source": "generated_other_job"}
    )
    assert db.add.call_args.args[0].details["origin"] == "generated_other_job"


@pytest.mark.parametrize(
    "metadata", [None, {}, {START_HTML_KEY: ""}, {START_HTML_KEY: 3}]
)
async def test_cv_without_a_recorded_start_writes_nothing(metadata):
    db = _session()
    await _log(db, metadata=metadata)
    db.add.assert_not_called()


async def test_failed_write_does_not_block_the_approval(caplog):
    db = _session(fail=True)
    await _log(db, metadata={START_HTML_KEY: GENERATED})
    assert "nie zapisano wpisu" in caplog.text


async def test_failed_comparison_does_not_block_the_approval(monkeypatch, caplog):
    monkeypatch.setattr(
        cv_edit_summary, "summarize_edits", Mock(side_effect=ValueError("broken"))
    )
    db = _session()
    await _log(db, metadata={START_HTML_KEY: GENERATED})
    db.add.assert_not_called()
    assert "nie zapisano wpisu" in caplog.text


def test_entry_is_not_counted_as_work_in_the_work_rhythm():
    # Ten sam klik zapisuje już `branded_cv_finalized`; pomiar nie jest drugą akcją.
    from app.services.work_rhythm import _SKIPPED_ACTIONS

    assert ACTION in _SKIPPED_ACTIONS


_SHORT = '<h1>Kandydat</h1><h2 data-cv-section="skills">S</h2><ul><li>Python</li></ul>'


@pytest.mark.parametrize(
    "added",
    [
        "<blockquote>Dodane</blockquote>",
        "<h4>Dodane</h4>",
        "<div>Dodane</div>",
        "<section>Dodane</section>",
        "<pre>Dodane</pre>",
        "<table><tr><td>Dodane</td></tr></table>",
        "<div><p>Akapit</p>Luźny tekst</div>",
    ],
)
def test_text_outside_the_editor_blocks_still_counts(added):
    # Wklejka z Worda albo strony: sanitizer to przepuszcza, Word to składa.
    summary = summarize_edits(_SHORT, _SHORT + added)
    assert summary["status"] == STATUS_CHANGED
    assert summary["parts"]["skills"]["added"] >= 1


def test_own_text_of_a_list_item_with_a_nested_list_counts():
    # Wcięcie w edytorze robi zagnieżdżoną listę; tekst punktu nad nią to obowiązek.
    start = (
        '<h2 data-cv-section="experience">E</h2>'
        "<ul><li><p>Tekst</p><ul><li><p>pod</p></li></ul></li></ul>"
    )
    raw = '<h2 data-cv-section="experience">E</h2><ul><li>Tekst<ul><li>pod</li></ul></li></ul>'
    for html in (start, raw):
        assert [part for part, _t, _b in cv_blocks(html)] == [
            "headings",
            "duties",
            "duties",
        ]
        summary = summarize_edits(html, html.replace("Tekst", "Zmieniony"))
        assert summary["parts"] == {
            "duties": {"added": 0, "removed": 0, "changed": 1, "bold": 0}
        }


def test_cost_is_linear_with_thousands_of_loose_lines_in_one_wrapper():
    lines = "".join(f"Wiersz {i}<br>" for i in range(20000))
    start = f'<h2 data-cv-section="skills">S</h2><div><p>Akapit</p>{lines}</div>'
    began = time.perf_counter()
    summary = summarize_edits(start, start.replace("Wiersz 7<br>", "Wiersz siedem<br>"))
    assert time.perf_counter() - began < 5
    assert summary["parts"]["skills"]["changed"] == 1


def test_pasted_consent_clause_as_loose_text_is_not_counted():
    start = '<h2 data-cv-section="skills">S</h2><div><p>Python</p></div>'
    approved = start.replace(
        "</p></div>",
        "</p>Wyrażam zgodę na przetwarzanie moich danych osobowych</div>",
    )
    assert summarize_edits(start, approved)["status"] == STATUS_UNCHANGED
