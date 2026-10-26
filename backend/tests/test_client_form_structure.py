"""0521: odczyt pól formularza CV klienta z wzoru DOCX (bez bazy, bez AI)."""

from __future__ import annotations

import io
import zipfile

import pytest

from app.services import client_form_structure as form
from tests._client_form_docx import filled_table_docx, form_docx


def _fields() -> dict[str, dict]:
    structure = form.read_structure(form_docx()).to_json()
    return {item["id"]: item for item in structure["fields"]}


def test_header_labels_and_boxes_become_fields() -> None:
    fields = _fields()
    assert fields["p2"] == {
        "id": "p2",
        "kind": "line",
        "label": "Imię i nazwisko",
        "section": None,
        "row_label": None,
        "table": None,
    }
    assert fields["p3"]["label"] == "Łączna liczba lat doświadczenia zawodowego"
    assert fields["p4"]["label"] == "Miejsce zamieszkania"
    # Etykieta nad tabelą to tytuł tabeli, nie osobne pole.
    assert not any(
        item["kind"] == "line" and item["label"].startswith("Cel zawodowy")
        for item in fields.values()
    )
    boxes = [item for item in fields.values() if item["kind"] == "box"]
    assert [item["label"] for item in boxes] == ["Cel zawodowy", "Informacje dodatkowe"]


def test_numbered_rows_get_column_labels_and_ellipsis_marks_an_extendable_table() -> (
    None
):
    structure = form.read_structure(form_docx()).to_json()
    fields = {item["id"]: item for item in structure["fields"]}
    assert fields["t1.r1.c1"]["label"] == "Miejsce pracy"
    assert fields["t1.r3.c4"]["label"] == "Opis projektów"
    assert fields["t1.r2.c2"]["row_label"] == "Wiersz 2"
    # Kolumna „Lp.”, wiersz z „…” i pusty wiersz bez numeru nie są polami.
    assert "t1.r1.c0" not in fields
    assert not any(key.startswith(("t1.r4.", "t1.r5.")) for key in fields)
    experience = next(t for t in structure["tables"] if t["index"] == 1)
    assert experience == {
        "index": 1,
        "title": "Doświadczenie zawodowe",
        "rows": 3,
        "extendable": True,
    }


def test_competency_rows_keep_their_name_section_and_the_header_above_them() -> None:
    fields = _fields()
    sql = fields["t2.r2.c2"]
    assert sql["label"] == "Spełnienie kompetencji (TAK/NIE)"
    assert sql["row_label"] == "Znajomość języka SQL;"
    assert sql["section"] == "Kompetencje obligatoryjne"
    assert sql["table"] == "Kompetencje"
    # Drugi nagłówek w środku tabeli zmienia etykiety kolumn poniżej.
    selenium = fields["t2.r5.c3"]
    assert selenium["label"] == "Stopień zaawansowania w skali 1-10"
    assert selenium["row_label"] == "Długość doświadczenia z frameworkiem Selenium"
    assert selenium["section"].startswith("Kompetencje dodatkowe")
    # Nazwa kompetencji jest tekstem wzoru — nie pole do wypełnienia.
    assert "t2.r5.c1" not in fields and "t2.r2.c1" not in fields


def test_shifted_grid_takes_headers_in_order() -> None:
    fields = _fields()
    shifted = {
        key: item["label"] for key, item in fields.items() if key.startswith("t3.r1.")
    }
    assert shifted == {
        "t3.r1.c1": "Miejsce pracy",
        "t3.r1.c3": "Okres pracy",
        "t3.r1.c5": "Stanowisko",
        "t3.r1.c6": "Opis projektów",
    }


def test_certificate_row_named_by_the_form() -> None:
    fields = _fields()
    assert fields["t4.r1.c2"]["label"] == "Data wydania"
    assert fields["t4.r1.c2"]["row_label"] == "Certyfikat ISTQB na poziomie podstawowym"


def test_summary_counts_fields_in_polish() -> None:
    structure = form.read_structure(form_docx()).to_json()
    text = form.summary(structure)
    assert text.startswith(f"{len(structure['fields'])} pól do wypełnienia · ")
    assert "3 pola nagłówka" in text
    assert "2 ramki na opis" in text
    assert "„Doświadczenie zawodowe”: 3 wiersze (można dokładać)" in text
    assert "„Certyfikaty (jeśli posiada)”: 1 wiersz" in text
    assert form._plural(1, "pole", "pola", "pól") == "pole"
    assert form._plural(22, "pole", "pola", "pól") == "pola"
    assert form._plural(12, "pole", "pola", "pól") == "pól"


def test_document_without_empty_fields_is_not_a_form() -> None:
    with pytest.raises(form.FormRejected) as refused:
        form.read_structure(filled_table_docx())
    assert str(refused.value) == form.MSG_NO_FORM


def test_not_a_word_file_is_refused() -> None:
    with pytest.raises(form.FormRejected) as refused:
        form.read_structure(b"%PDF-1.4 to nie jest Word")
    assert str(refused.value) == form.MSG_NOT_DOCX


def _with_part(name: str, data: bytes = b"x") -> bytes:
    buffer = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(form_docx())) as source,
        zipfile.ZipFile(buffer, "w") as target,
    ):
        for entry in source.infolist():
            target.writestr(entry, source.read(entry))
        target.writestr(name, data)
    return buffer.getvalue()


def test_macros_and_oversized_packages_are_refused(monkeypatch) -> None:
    with pytest.raises(form.FormRejected) as macros:
        form.read_structure(_with_part("word/vbaProject.bin"))
    assert str(macros.value) == form.MSG_MACROS
    monkeypatch.setattr(form, "MAX_UNPACKED_BYTES", 1000)
    with pytest.raises(form.FormRejected) as big:
        form.read_structure(form_docx())
    assert str(big.value) == form.MSG_TOO_BIG


def test_huge_grid_span_from_the_file_does_not_hang_the_reader() -> None:
    import time

    from docx import Document
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    document = Document(io.BytesIO(form_docx()))
    tc = document.tables[1].rows[0]._tr.tc_lst[1]
    span = OxmlElement("w:gridSpan")
    span.set(qn("w:val"), "5000000")
    tc.get_or_add_tcPr().append(span)
    buffer = io.BytesIO()
    document.save(buffer)
    started = time.monotonic()
    form.read_structure(buffer.getvalue())
    assert time.monotonic() - started < 5
