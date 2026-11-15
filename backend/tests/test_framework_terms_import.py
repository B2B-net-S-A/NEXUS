"""Cennik umowy ramowej z załącznika .docx (F1). Dokument i stawki fikcyjne."""

import io
from decimal import Decimal

from docx import Document

from app.services.framework_terms_import import parse_terms_docx


def appendix() -> bytes:
    doc = Document()
    doc.add_paragraph("Appendix: Charges")
    head = doc.add_table(rows=1, cols=2)
    head.rows[0].cells[0].text = "Supplier"
    head.rows[0].cells[1].text = "Agreement number: X1"
    rates = doc.add_table(rows=0, cols=3)
    for group, label, rate in [
        ("", "", "PLN/h"),
        ("IT", "IT Developer - Expert", "120"),
        ("", "IT Developer - Senior", "100"),
        ("", "IT Developer", "90"),
        ("", "IT Architect - Expert", "130"),
        ("I&O", "I&O - Oracle DBA", "80"),
    ]:
        cells = rates.add_row().cells
        cells[0].text, cells[1].text, cells[2].text = group, label, rate
    matrix = doc.add_table(rows=0, cols=4)
    top = matrix.add_row().cells
    top[1].merge(top[3]).text = "Competences categories"
    for values in [
        ("Technology skills", "IT Developer - Expert", "IT Developer - Senior", "IT Developer"),
        ("Kafka", "20%", "20%", "20%"),
        ("PEGA", "10%", "10%", ""),
    ]:
        cells = matrix.add_row().cells
        for cell, value in zip(cells, values):
            cell.text = value
    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def test_rates_and_adders_are_read_from_appendix_tables():
    out = parse_terms_docx(appendix())
    assert [(r.label, r.rate) for r in out.rates] == [
        ("IT Developer - Expert", Decimal("120")),
        ("IT Developer - Senior", Decimal("100")),
        ("IT Developer", Decimal("90")),
        ("IT Architect - Expert", Decimal("130")),
        ("I&O - Oracle DBA", Decimal("80")),
    ]
    kafka, pega = out.adders
    assert (kafka.technology, kafka.percent) == ("Kafka", Decimal("20"))
    assert kafka.eligible == [
        {"role": "IT Developer", "seniority": "Expert"},
        {"role": "IT Developer", "seniority": "Senior"},
        {"role": "IT Developer", "seniority": None},
    ]
    # Pusta komórka = brak dopłaty dla tej kategorii.
    assert pega.eligible == [
        {"role": "IT Developer", "seniority": "Expert"},
        {"role": "IT Developer", "seniority": "Senior"},
    ]
    assert out.warnings == []


def test_document_without_rate_table_says_so():
    doc = Document()
    doc.add_paragraph("Brak tabel")
    buffer = io.BytesIO()
    doc.save(buffer)
    out = parse_terms_docx(buffer.getvalue())
    assert out.rates == [] and out.adders == []
    assert "Nie znaleziono tabeli stawek" in out.warnings[0]


def test_rate_inside_content_control_is_read():
    # Załącznik klienta trzyma stawki w kontrolkach zawartości (``w:sdt``),
    # których ``cell.text`` z python-docx nie widzi.
    from docx.oxml import parse_xml
    from docx.oxml.ns import nsdecls

    doc = Document()
    table = doc.add_table(rows=1, cols=2)
    table.rows[0].cells[0].text = "IT Developer - Senior"
    paragraph = table.rows[0].cells[1].paragraphs[0]._p
    paragraph.append(
        parse_xml(
            f"<w:sdt {nsdecls('w')}><w:sdtContent><w:r><w:t>1</w:t></w:r>"
            "<w:r><w:t>00</w:t></w:r></w:sdtContent></w:sdt>"
        )
    )
    buffer = io.BytesIO()
    doc.save(buffer)
    out = parse_terms_docx(buffer.getvalue())
    assert [(r.label, r.rate) for r in out.rates] == [("IT Developer - Senior", Decimal("100"))]
