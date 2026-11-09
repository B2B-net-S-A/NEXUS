"""Pomiar zmian ludzi w CV z generatora: linia bazowa i raport (same liczby)."""

from __future__ import annotations

import asyncio
import copy
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from zoneinfo import ZoneInfo

from lxml import html as lxml_html
import pytest

from app.services.cv_approval_provenance import capture_editor_origin
from app.services.cv_edit_summary import START_HTML_KEY
from app.services.cv_edit_measure import (
    SECTIONS,
    TOTAL,
    compare_cv,
    first_draft_is_reproduced,
    generator_first_draft_html,
    section_texts,
    words,
)
from scripts.cv_edit_report import (
    ALL_CLIENTS,
    CHANNEL_ALL,
    CHANNEL_AUTO,
    CHANNEL_MANUAL,
    OUTCOME_CHANGED_MACHINE,
    OUTCOME_CHANGED_MANUAL,
    OUTCOME_CHANGED_UNKNOWN,
    OUTCOME_OPEN_DRAFT,
    OUTCOME_APPROVED_NO_ENTRY,
    OUTCOME_OTHER,
    OUTCOME_REPLACED,
    OUTCOME_STALE_DRAFT,
    StartRow,
    format_starts,
    start_outcome,
    starts_table,
    FinishedCv,
    WeeklyRow,
    build_report,
    format_report,
    format_weekly,
    generator_model,
    period_bounds,
    weekly_table,
)

PAYLOAD = {
    "name": "Ewa Fikcyjna",
    "first_name": "Ewa",
    "position": "Analityk danych",
    "language": "pl",
    "blind_cv": False,
    "considered_for": "Starszy analityk",
    "why_points": ["Siedem lat w analizie danych", "Prowadziła migracje hurtowni"],
    "education": [
        {
            "dates": "2010-2015",
            "institution": "Uczelnia Testowa",
            "degree": "Informatyka",
            "location": "Gdańsk",
        }
    ],
    "skills": [{"label": "Języki", "content": "Python, SQL, C++"}],
    "certifications": ["Certyfikat chmurowy"],
    "languages": ["angielski C1"],
    "experience": [
        {
            "dates": "01.2020 - obecnie",
            "company": "Firma Przykładowa",
            "industry": "bankowość",
            "position": "Analityk",
            "responsibilities": ["Budowa raportów kwartalnych", "Analiza wymagań"],
            "technologies": ["Python", "Airflow"],
        },
        {
            "dates": "01.2016 - 12.2019",
            "company": "Inna Spółka",
            "industry": "",
            "position": "Młodszy analityk",
            "responsibilities": ["Czyszczenie danych wejściowych"],
            "technologies": ["SQL"],
        },
    ],
    "highlight_keywords": ["Python"],
    "editorial_provenance": {"pipeline": "legacy_v7", "prompt_version": 9},
}


def _payload(**changes) -> dict:
    return {**copy.deepcopy(PAYLOAD), **changes}


def _as_editor_saves(content: str) -> str:
    """Tak wraca treść po otwarciu w Tiptapie: płasko, `strong`, akapity w `li`."""
    root = lxml_html.fragment_fromstring(content, create_parent="div")
    for node in list(root.iter("article", "div")):
        if node is root:
            continue
        if node.get("class") == "edu":
            node.tag = "p"
        else:
            node.drop_tag()
    for node in root.iter("b"):
        node.tag = "strong"
    for node in root.iter():
        node.attrib.pop("class", None)
        node.attrib.pop("id", None)
    for item in root.iter("li"):
        paragraph = lxml_html.Element("p")
        paragraph.text, item.text = item.text, None
        for child in list(item):
            paragraph.append(child)
        item.append(paragraph)
    saved = "".join(lxml_html.tostring(c, encoding="unicode") for c in root)
    return saved.replace(" - obecnie", " - obecnie")


@pytest.mark.parametrize(
    "payload",
    [
        _payload(),
        _payload(language="en"),
        _payload(blind_cv=True),
    ],
    ids=["pl", "en", "blind"],
)
def test_untouched_cv_scores_zero(payload):
    baseline = generator_first_draft_html(payload)

    edits = compare_cv(baseline, baseline)

    assert set(edits) == {*SECTIONS, TOTAL}
    for edit in edits.values():
        assert edit.changed is False
        assert edit.added == 0
        assert edit.removed == 0
    assert edits[TOTAL].base_words > 0
    assert edits[TOTAL].added_share == 0
    assert edits[TOTAL].removed_share == 0


def test_untouched_cv_saved_by_the_editor_scores_zero():
    baseline = generator_first_draft_html(_payload())

    edits = compare_cv(baseline, _as_editor_saves(baseline))

    for edit in edits.values():
        assert (edit.changed, edit.added, edit.removed) == (False, 0, 0)


@pytest.mark.parametrize("language", ["pl", "en"])
def test_template_text_is_not_counted(language):
    """Tytuły sekcji, etykiety i klauzula nie wchodzą ani do liczby, ani do mianownika."""
    texts = section_texts(generator_first_draft_html(_payload(language=language)))

    all_text = " ".join(" ".join(blocks) for blocks in texts.values()).casefold()
    for template in (
        "doświadczenie",
        "experience",
        "umiejętności",
        "skills",
        "edukacja",
        "education",
        "dlaczego nasz",
        "why our",
        "zakres zadań",
        "tasks",
        "responsibilities",
        "technologie:",
        "technologies:",
        "wyrażam zgodę",
        "i hereby",
        "rozważany",
        "considered",
    ):
        assert template not in all_text, template
    assert texts["summary"] == PAYLOAD["why_points"]
    assert "Airflow" in " ".join(texts["experience"])
    assert "Uczelnia" in " ".join(texts["education"])
    assert " ".join(texts["skills"]).startswith("Języki:")
    assert "Starszy analityk" in " ".join(texts["other"])


def test_rewording_the_template_changes_nothing():
    baseline = generator_first_draft_html(_payload())
    renamed = (
        baseline.replace("Zakres zadań:", "Zakres zadań")
        .replace("Wyrażam zgodę na przetwarzanie", "Zgadzam się na przetwarzanie")
        .replace("Technologie:", "Technologie: ")
    )
    assert renamed != baseline

    edits = compare_cv(baseline, renamed)

    assert (edits[TOTAL].changed, edits[TOTAL].added, edits[TOTAL].removed) == (
        False,
        0,
        0,
    )


def test_one_word_changed_counts_only_in_its_section():
    baseline = generator_first_draft_html(_payload())
    final = baseline.replace("Budowa raportów", "Tworzenie raportów")

    edits = compare_cv(baseline, final)

    experience = edits["experience"]
    assert (experience.changed, experience.added, experience.removed) == (True, 1, 1)
    assert experience.added_share == pytest.approx(1 / experience.base_words)
    assert experience.removed_share == pytest.approx(1 / experience.base_words)
    for section in ("summary", "skills", "education", "other"):
        assert edits[section].changed is False
    assert edits[TOTAL].added == 1
    assert edits[TOTAL].removed == 1
    assert edits[TOTAL].base_words > experience.base_words


def test_bold_only_is_not_a_text_change():
    """Pogrubienie zależy od taksonomii i od rekrutera, tekst zostaje ten sam."""
    baseline = generator_first_draft_html(_payload())
    final = baseline.replace("Analiza wymagań", "<strong>Analiza</strong> wymagań")

    assert compare_cv(baseline, final)[TOTAL].changed is False


def test_bold_inside_a_word_does_not_split_it():
    baseline = "<h2 data-cv-section='skills'>UMIEJĘTNOŚCI</h2><p>Linuxa</p>"
    final = "<h2 data-cv-section='skills'>UMIEJĘTNOŚCI</h2><p><b>Linux</b>a</p>"

    assert compare_cv(baseline, final)["skills"].changed is False


def test_line_break_separates_words():
    baseline = "<h2 data-cv-section='skills'>UMIEJĘTNOŚCI</h2><p>Python SQL</p>"
    final = "<h2 data-cv-section='skills'>UMIEJĘTNOŚCI</h2><p>Python<br>SQL</p>"

    edit = compare_cv(baseline, final)["skills"]
    assert (edit.changed, edit.added, edit.removed) == (False, 0, 0)


def test_reordered_roles_change_text_but_no_words():
    payload = _payload()
    reordered = _payload(experience=list(reversed(payload["experience"])))

    edits = compare_cv(
        generator_first_draft_html(payload), generator_first_draft_html(reordered)
    )

    assert edits["experience"].changed is True
    assert edits["experience"].added == 0
    assert edits["experience"].removed == 0


def test_word_moved_between_sections_counts_in_sections_not_in_total():
    baseline = generator_first_draft_html(_payload())
    final = baseline.replace("Analiza wymagań", "Analiza").replace(
        "angielski C1", "angielski C1 wymagań"
    )

    edits = compare_cv(baseline, final)

    assert edits["experience"].removed == 1
    assert edits["other"].added == 1
    assert (edits[TOTAL].added, edits[TOTAL].removed) == (0, 0)
    assert edits[TOTAL].changed is True


def test_section_without_baseline_has_no_share():
    baseline = "<h1>Tytuł</h1>"
    final = "<h1>Tytuł</h1><h2 data-cv-section='skills'>UMIEJĘTNOŚCI</h2><p>Python</p>"

    edit = compare_cv(baseline, final)["skills"]

    assert (edit.base_words, edit.added) == (0, 1)
    assert edit.added_share is None
    assert edit.removed_share is None


def test_own_heading_is_content_and_starts_other_section():
    baseline = generator_first_draft_html(_payload())
    final = baseline.replace(
        '<p class="rodo">', '<h2>Projekty</h2><p>Projekt testowy</p><p class="rodo">'
    )

    edits = compare_cv(baseline, final)

    assert edits["other"].added == 3
    assert edits["experience"].changed is False


def test_words_keep_technology_names_and_ignore_punctuation_and_case():
    assert words("C++, C#, Node.js; CI/CD (Python) 2019-2021") == [
        "c++",
        "c#",
        "node.js",
        "ci/cd",
        "python",
        "2019-2021",
    ]


def test_first_draft_is_what_the_stage_draft_path_writes():
    """Ta sama droga co auto-CV i „Zastąp szkic”: baza musi być równa szkicowi co do bajtu."""
    from app.api.candidate_stage_cv import apply_generated_to_stage_cv

    payload = _payload()
    generated = SimpleNamespace(
        id=7,
        render_payload=payload,
        template_content=b"szablon",
        consent_content=None,
        filename="cv.docx",
        client_id=None,
        client_rule_version=None,
    )
    stage_cv = SimpleNamespace(
        id=3,
        candidate_stage_id=5,
        branded_status="none",
        branded_render_metadata=None,
        branded_draft_html=None,
        branded_version=1,
        edit_revision=0,
    )

    asyncio.run(
        apply_generated_to_stage_cv(
            Mock(), stage_cv, generated, user_id=None, activity_action="test"
        )
    )

    assert stage_cv.branded_draft_html == generator_first_draft_html(payload)
    assert first_draft_is_reproduced(payload, stage_cv.branded_render_metadata)


def test_first_draft_mismatch_is_detected():
    payload = _payload()
    metadata = capture_editor_origin("<p>inny szkic</p>", payload)

    assert first_draft_is_reproduced(payload, metadata) is False
    assert first_draft_is_reproduced(payload, {}) is False
    assert first_draft_is_reproduced(payload, None) is False


def _before_e3(metadata: dict) -> dict:
    """Metadane szkicu sprzed E3 (07.11.2026): skrót startu bez jego treści."""
    return {k: v for k, v in metadata.items() if k != START_HTML_KEY}


def _finished(
    final: str | None = None,
    *,
    payload: dict | None = None,
    model: str = "model-a",
    metadata: dict | None = None,
    source: str | None = None,
    generated_document_id: int | None = 1,
) -> FinishedCv:
    payload = _payload() if payload is None else payload
    baseline = generator_first_draft_html(payload)
    return FinishedCv(
        content_html=baseline if final is None else final,
        metadata=_before_e3(capture_editor_origin(baseline, payload))
        if metadata is None
        else metadata,
        render_payload=payload,
        generated_document_id=generated_document_id,
        source=source,
        model=model,
    )


def test_report_shares_and_medians():
    baseline = generator_first_draft_html(_payload())
    edited = baseline.replace("Budowa raportów", "Tworzenie raportów")
    cvs = [
        _finished(),
        _finished(_as_editor_saves(baseline)),
        _finished(edited),
        _finished(edited, model="model-b"),
    ]

    report = build_report(cvs)

    assert report.finished == 4
    assert report.counted == 4
    assert report.excluded == {}
    assert report.byte_identical == 1
    everyone = report.groups["wszystkie"]
    assert everyone.n == 4
    assert everyone.sections[TOTAL].unchanged_share == pytest.approx(0.5)
    base = compare_cv(baseline, edited)["experience"].base_words
    experience = everyone.sections["experience"]
    assert experience.median_added == pytest.approx(0.5 / base)
    assert experience.median_removed == pytest.approx(0.5 / base)
    assert experience.median_added_changed == pytest.approx(1 / base)
    assert everyone.sections["summary"].unchanged_share == 1
    assert everyone.sections["summary"].median_added == 0
    assert everyone.sections["summary"].median_added_changed is None
    assert report.groups["model-a"].n == 3
    assert report.groups["model-b"].n == 1
    assert report.groups["model-b"].sections[TOTAL].unchanged_share == 0


def test_report_excludes_what_has_no_reliable_baseline():
    other_payload = _payload(why_points=["Inne podsumowanie"])
    cvs = [
        _finished(),
        _finished(source="document", generated_document_id=None, metadata={}),
        _finished(source="generated_other_job", generated_document_id=None),
        _finished(generated_document_id=None, metadata={}),
        _finished(metadata={}),
        _finished(
            metadata=_before_e3(
                capture_editor_origin("<p>inny szkic</p>", other_payload)
            )
        ),
        FinishedCv(
            content_html="<p>treść</p>",
            metadata={"generated_editor_html_sha256": "x"},
            render_payload=None,
            generated_document_id=1,
            source=None,
            model="model-a",
        ),
    ]

    report = build_report(cvs)

    assert report.finished == 7
    assert report.counted == 1
    assert report.excluded == {
        "plik Word": 1,
        "kopia z innej rekrutacji": 1,
        "bez dokumentu generatora": 2,
        "brak skrótu pierwszego szkicu": 1,
        "baza nie odtwarza pierwszego szkicu": 1,
    }


def test_stored_start_is_the_baseline_without_reproducing_the_renderer():
    # Renderer zmienił się po generacji: odtworzenie nie daje startu, ale start
    # zapisany przy podpięciu (E3) jest bazą wprost — także dla kopii.
    start = (
        '<h2 data-cv-section="why_points">Dlaczego</h2><ul><li>Stary układ</li></ul>'
    )
    stored = capture_editor_origin(start, _payload())
    cvs = [
        _finished(start, metadata=stored),
        _finished(
            start.replace("Stary", "Nowy"),
            metadata={**stored, "source": "generated_other_job"},
            generated_document_id=None,
            source="generated_other_job",
        ),
    ]

    report = build_report(cvs)

    assert report.counted == 2 and report.excluded == {}
    assert report.byte_identical == 1
    assert report.groups["wszystkie"].sections["summary"].unchanged_share == 0.5


def test_report_output_has_numbers_only_no_names_and_no_cv_text():
    baseline = generator_first_draft_html(_payload())
    report = build_report(
        [
            _finished(baseline.replace("Budowa raportów", "Tworzenie raportów")),
            _finished(source="document", generated_document_id=None, metadata={}),
        ]
    )

    output = format_report(report, date(2026, 10, 1), date(2026, 10, 31))

    assert "2026-10-01" in output
    assert "model-a" in output
    assert "n=1" in output
    for forbidden in (
        "Ewa",
        "Fikcyjna",
        "Firma Przykładowa",
        "Analityk",
        "raportów",
        "Tworzenie",
        "Uczelnia",
        "Airflow",
    ):
        assert forbidden not in output


def test_report_with_no_cvs_says_so():
    output = format_report(build_report([]), date(2026, 10, 1), date(2026, 10, 31))

    assert "0" in output
    assert "Brak CV" in output


def test_generator_model_names_only_one_model():
    assert generator_model(set()) == "nieznany"
    assert generator_model({"gpt-6.1-sol"}) == "gpt-6.1-sol"
    assert generator_model({"gpt-6.1-sol", "claude-sonnet-5"}) == "niejednoznaczny"


def test_period_is_a_business_calendar_range_across_dst():
    warsaw = ZoneInfo("Europe/Warsaw")

    start, end = period_bounds(date(2026, 10, 1), date(2026, 10, 31))

    assert start == datetime(2026, 10, 1, tzinfo=warsaw)
    assert end == datetime(2026, 11, 1, tzinfo=warsaw)
    assert start.utcoffset().total_seconds() == 7200
    assert end.utcoffset().total_seconds() == 3600


# ── --weekly: CV bez poprawek per klient i tydzień (wpisy E3) ──────────────


def _week_rows() -> list[WeeklyRow]:
    w1, w2 = date(2026, 11, 2), date(2026, 11, 9)
    return [
        WeeklyRow(w1, "Bank A", "unchanged", ()),
        WeeklyRow(w1, "Bank A", "changed", ("why_points", "duties")),
        WeeklyRow(w1, "Bank A", "bold_only", ()),
        WeeklyRow(w1, "Ubezpieczyciel B", "changed", ("why_points",)),
        WeeklyRow(w2, "Bank A", "unchanged", ()),
    ]


def test_weekly_table_counts_unchanged_share_per_client_and_week():
    table = weekly_table(_week_rows())

    assert list(table) == [ALL_CLIENTS, "Bank A", "Ubezpieczyciel B"]
    everyone = table[ALL_CLIENTS][date(2026, 11, 2)]
    assert (everyone.n, everyone.unchanged, everyone.bold_only, everyone.changed) == (
        4,
        1,
        1,
        2,
    )
    assert everyone.unchanged_share == 0.25
    assert everyone.top_parts == (("why_points", 2), ("duties", 1))
    assert table["Bank A"][date(2026, 11, 9)].unchanged_share == 1
    assert table["Ubezpieczyciel B"][date(2026, 11, 2)].unchanged_share == 0


def test_weekly_output_has_shares_and_no_cv_text():
    output = format_weekly(
        weekly_table(_week_rows()), date(2026, 11, 2), date(2026, 11, 15)
    )

    assert "2026-11-02" in output and "2026-11-09" in output
    assert "25.0%" in output and "why_points 2" in output
    assert "Bank A" in output


def test_weekly_without_entries_says_why():
    output = format_weekly({}, date(2026, 11, 2), date(2026, 11, 15))

    assert "Brak wpisów" in output


_NOW = datetime(2026, 11, 8, 12, tzinfo=ZoneInfo("UTC"))
_AT = datetime(2026, 11, 1, 12, tzinfo=ZoneInfo("UTC"))


def _outcome(**kw) -> str:
    defaults = {
        "entry": None,
        "entry_at": None,
        "replace_at": None,
        "undo_at": None,
        "branded_status": "draft",
        "branded_updated_at": _NOW,
        "now": _NOW,
    }
    return start_outcome(**{**defaults, **kw})


def test_start_outcome_splits_changed_by_applied_machine_edits() -> None:
    assert (
        _outcome(entry={"status": "changed", "assisted": {"qc_fixes": 1}})
        == OUTCOME_CHANGED_MACHINE
    )
    assert (
        _outcome(entry={"status": "changed", "assisted": {"assistant_applied": 2}})
        == OUTCOME_CHANGED_MACHINE
    )
    # Samo pytanie asystenta niczego w CV nie zmienia.
    assert (
        _outcome(entry={"status": "changed", "assisted": {"assistant_commands": 3}})
        == OUTCOME_CHANGED_MANUAL
    )
    assert _outcome(entry={"status": "changed"}) == OUTCOME_CHANGED_UNKNOWN


def test_start_outcome_replaced_entry_and_legacy_upload_count_as_replaced() -> None:
    assert _outcome(entry={"status": "replaced"}, entry_at=_AT) == OUTCOME_REPLACED
    assert _outcome(replace_at=_AT) == OUTCOME_REPLACED


def test_start_outcome_undone_replacement_falls_back_to_the_draft_state() -> None:
    later = _AT + timedelta(minutes=2)
    assert (
        _outcome(entry={"status": "replaced"}, entry_at=_AT, undo_at=later)
        == OUTCOME_OPEN_DRAFT
    )
    assert _outcome(replace_at=_AT, undo_at=later) == OUTCOME_OPEN_DRAFT


def test_start_outcome_draft_age_and_unknown_state() -> None:
    assert _outcome(branded_updated_at=_NOW - timedelta(days=8)) == OUTCOME_STALE_DRAFT
    assert _outcome(branded_updated_at=_NOW - timedelta(days=6)) == OUTCOME_OPEN_DRAFT
    assert _outcome(branded_status="finalized") == OUTCOME_APPROVED_NO_ENTRY
    assert _outcome(branded_status="none") == OUTCOME_OTHER


def _start_rows() -> list[StartRow]:
    week = date(2026, 11, 2)
    return [
        StartRow(week, "Bank", CHANNEL_MANUAL, "unchanged"),
        StartRow(week, "Bank", CHANNEL_MANUAL, OUTCOME_REPLACED, "newer_cv", "upload"),
        StartRow(week, "Bank", CHANNEL_AUTO, OUTCOME_REPLACED, None, "discard"),
        StartRow(week, "Ubezpieczenia", CHANNEL_AUTO, OUTCOME_STALE_DRAFT),
    ]


def test_starts_table_counts_from_starts_per_channel_with_period_total() -> None:
    table = starts_table(_start_rows())
    everyone = table[ALL_CLIENTS]
    assert list(everyone)[0] == CHANNEL_ALL
    assert set(everyone) == {CHANNEL_ALL, CHANNEL_AUTO, CHANNEL_MANUAL}
    total = everyone[CHANNEL_ALL][None]
    assert total.n == 4 and total.of(OUTCOME_REPLACED) == 2
    assert everyone[CHANNEL_AUTO][date(2026, 11, 2)].of(OUTCOME_STALE_DRAFT) == 1
    assert table["Bank"][CHANNEL_MANUAL][None].n == 2


def test_starts_output_has_shares_kinds_reasons_and_no_cv_text() -> None:
    rows = _start_rows()
    output = format_starts(
        starts_table(rows), rows, date(2026, 11, 2), date(2026, 11, 8)
    )
    assert "2 (50%)" in output
    assert "wgrany plik 1" in output and "odrzucone 1" in output
    assert "nowsze CV od kandydata 1" in output
    assert "bez powódu" not in output and "bez powodu: 1" in output


def test_starts_output_without_starts_says_so() -> None:
    assert "Brak startów" in format_starts({}, [], date(2026, 11, 2), date(2026, 11, 8))
