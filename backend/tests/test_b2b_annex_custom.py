"""Aneks z własną nazwą („Aneks — inna zmiana”, 16.11.2026) — reguły bez bazy.

Zgłoszenie Finansów: aneks o zdjęciu zakazu konkurencji nie pasował do żadnego
z pięciu typów. Typ ``annex_custom`` ma nazwę wpisaną przez człowieka, listę
zmian w paragrafach i gotową klauzulę zwolnienia z zakazu konkurencji.
"""

from __future__ import annotations

from datetime import date

from app.api.b2b_documents import _filename
from app.services.b2b_documents.annex_summary import annex_change
from app.services.b2b_documents.constants import B2B_DOCUMENT_TYPES
from app.services.b2b_documents.context import annex_change_points
from app.services.b2b_documents.effects import annex_custom_title
from app.services.b2b_documents.registry import (
    MAX_ANNEX_CHANGES,
    annex_changes_problems,
    get_type,
    invalid_values,
    missing_required,
)
from app.services.b2b_documents.schema_sql import (
    AMENDMENT_ENUM_VALUES,
    TYPES_BEFORE_0503,
    TYPES_BEFORE_0722,
)


def test_type_is_an_annex_for_register_and_outside_contracts():
    doc_type = get_type("annex_custom")
    assert doc_type is not None
    assert doc_type.family == "annex"
    assert doc_type.allows_external is True
    assert doc_type.parent == "b2b"
    keys = {f.key for f in doc_type.fields}
    assert {"annex_title", "changes", "contract_number", "effective_date"} <= keys


def test_title_and_changes_are_required():
    doc_type = get_type("annex_custom")
    missing = missing_required(doc_type, {"annex_title": " ", "changes": []})
    assert "Czego dotyczy aneks" in missing
    assert "Zmiany w umowie" in missing


def test_paragraph_operations_need_a_paragraph_and_text():
    problems = annex_changes_problems(
        [
            {"op": "replace", "paragraph": "", "text": "x"},
            {"op": "add", "paragraph": "10", "section": "", "text": "x"},
            {"op": "replace", "paragraph": "10", "section": "1", "text": "  "},
            {"op": "delete", "paragraph": "7"},
            {"op": "free", "text": "Własny punkt."},
        ]
    )
    assert problems == [
        "Zmiana 1: podaj numer paragrafu (§).",
        "Zmiana 2: podaj numer dodawanego ustępu.",
        "Zmiana 3: wpisz treść.",
    ]


def test_clause_gap_left_by_the_form_is_refused():
    problems = annex_changes_problems(
        [{"op": "free", "text": "na rzecz: [uzupełnij], spółek macierzystych"}]
    )
    assert problems == ["Zmiana 1: uzupełnij miejsca oznaczone [uzupełnij]."]


def test_unknown_operation_and_unreadable_row_are_refused():
    problems = annex_changes_problems(["tekst", {"op": "rewrite", "text": "x"}])
    assert problems == [
        "Zmiana 1 jest nieczytelna.",
        "Zmiana 2: wybierz, co się dzieje z umową.",
    ]


def test_limits_on_rows_text_and_title():
    rows = [{"op": "free", "text": "x"}] * (MAX_ANNEX_CHANGES + 1)
    assert f"najwyżej {MAX_ANNEX_CHANGES} zmian" in annex_changes_problems(rows)[0]
    long_text = annex_changes_problems([{"op": "free", "text": "x" * 4001}])
    assert "więcej niż 4000 znaków" in long_text[0]
    doc_type = get_type("annex_custom")
    problems = invalid_values(
        doc_type,
        {"annex_title": "a" * 151, "changes": [{"op": "free", "text": "x"}]},
    )
    assert problems == ["„Czego dotyczy aneks” ma więcej niż 150 znaków."]


def test_change_points_use_one_wording_for_every_operation():
    points = annex_change_points(
        [
            {"op": "replace", "paragraph": "§ 10", "section": "1", "text": "A\n\nB"},
            {"op": "add", "paragraph": "10", "section": "2a", "text": "C"},
            {"op": "delete", "paragraph": "7", "section": ""},
            {"op": "free", "text": "Pierwsza linia\nDruga linia"},
        ]
    )
    assert points == [
        {
            "label": "a",
            "lead": "§ 10 ust. 1 Umowy otrzymuje brzmienie:",
            "lines": ["„A", "B”"],
        },
        {
            "label": "b",
            "lead": "w § 10 Umowy dodaje się ust. 2a w brzmieniu:",
            "lines": ["„C”"],
        },
        {"label": "c", "lead": "§ 7 Umowy skreśla się.", "lines": []},
        {"label": "d", "lead": "Pierwsza linia", "lines": ["Druga linia"]},
    ]


def test_change_points_ignore_garbage():
    assert annex_change_points(None) == []
    assert annex_change_points(["x", {"op": "free", "text": ""}]) == [
        {"label": "a", "lead": "…", "lines": []}
    ]


def test_non_compete_clause_reuses_the_termination_wording():
    clause = get_type("annex_custom").clauses[0]
    assert clause.key == "non_compete_release"
    assert clause.title == "zwolnienie z zakazu konkurencji"
    (row,) = clause.rows
    assert row.op == "free"
    # To samo zdanie co w porozumieniu o rozwiązaniu umowy (przyjęta treść),
    # z paragrafem z wersji wzoru umowy i klientem z umowy.
    with open(
        "app/templates/documents/termination_agreement_pl.html", encoding="utf-8"
    ) as fh:
        termination = fh.read()
    assert (
        "zwalnia Partnera z zakazu konkurencji określonego w "
        "{{ refs.non_compete_paragraph }} Umowy" in termination
    )
    assert row.text.startswith(
        "B2B.net S.A. zwalnia Partnera z zakazu konkurencji określonego w "
        "{non_compete_paragraph} Umowy i zgadza się na bezpośrednie zatrudnienie"
    )
    assert "{client_legal_name}, spółek macierzystych" in row.text


def test_clauses_reach_the_form_in_document_types():
    public = get_type("annex_custom").to_public()
    assert public["clauses"][0]["rows"][0]["op"] == "free"
    assert not get_type("annex_start_date").to_public()["clauses"]


def test_register_summary_carries_the_title():
    change = annex_change(
        "annex_custom",
        {"annex_title": " zwolnienie z zakazu konkurencji ", "changes": [{}, {}]},
        rates_visible=False,
    )
    assert change == {
        "kind": "custom",
        "title": "zwolnienie z zakazu konkurencji",
        "count": 2,
    }


def test_title_falls_back_when_empty():
    assert annex_custom_title({"annex_title": "  "}) == "inna zmiana"
    assert annex_custom_title({"annex_title": "zmiana adresu"}) == "zmiana adresu"


def test_file_name_uses_the_title():
    doc_type = get_type("annex_custom")
    name = _filename(
        doc_type,
        {"annex_title": "zwolnienie z zakazu konkurencji", "partner_name": "Jan"},
        date(2026, 11, 16),
    )
    assert name.endswith(".docx")
    assert "zwolnienie" in name and "konkurencji" in name


def test_schema_lists_include_the_new_type_for_upgrade_only():
    assert "annex_custom" in B2B_DOCUMENT_TYPES
    assert "annex_custom" not in TYPES_BEFORE_0722
    assert "annex_custom" not in TYPES_BEFORE_0503
    assert "custom_change" in AMENDMENT_ENUM_VALUES
