"""Akademia — komplet dokumentów uczestnika (szablony od działu, 24.09.2026)."""

from __future__ import annotations

import io
import re
import zipfile
from datetime import date

import docx
import pytest

from app.services import academy_documents as docs


def _data(**overrides) -> docs.DocumentInput:
    start, end = docs.program_dates(date(2026, 11, 1))
    base = dict(
        participant_name="Anna Przykładowa",
        phone="600100200",
        email="anna@example.com",
        address=None,
        pesel=None,
        signing_date=date(2026, 10, 20),
        program_start=start,
        program_end=end,
        handover_name="Jan Rekruter",
        protocol_date=None,
    )
    base.update(overrides)
    return docs.DocumentInput(**base)


def _texts(package: bytes) -> dict[str, str]:
    archive = zipfile.ZipFile(io.BytesIO(package))
    out = {}
    for name in archive.namelist():
        document = docx.Document(io.BytesIO(archive.read(name)))
        out[name] = "\n".join(p.text for p in document.paragraphs)
    return out


def test_program_is_ten_workdays_skipping_holidays():
    # 1.11.2026 niedziela, 11.11 święto → 02.11–16.11.
    assert docs.program_dates(date(2026, 11, 1)) == (date(2026, 11, 2), date(2026, 11, 16))
    assert docs.program_dates(date(2026, 10, 1)) == (date(2026, 10, 1), date(2026, 10, 14))
    # 1.01 i 6.01 święta.
    assert docs.program_dates(date(2027, 1, 1)) == (date(2027, 1, 4), date(2027, 1, 18))


@pytest.mark.parametrize(
    "value,ok",
    [("44051401359", True), ("44051401358", False), ("4405140135", False), ("4405140135a", False)],
)
def test_pesel_checksum(value, ok):
    assert docs.pesel_valid(value) is ok


def test_package_has_five_documents_with_fields_filled():
    texts = _texts(docs.render_package(_data()))
    assert sorted(texts) == [
        "1_Umowa_uczestnictwa_Anna_Przykladowa.docx",
        "2_Zalacznik_1_Harmonogram_Anna_Przykladowa.docx",
        "3_Oswiadczenie_uczestnika_Anna_Przykladowa.docx",
        "4_Regulamin_Programu_Anna_Przykladowa.docx",
        "5_Protokol_przekazania_Manuala_Anna_Przykladowa.docx",
    ]
    umowa = texts["1_Umowa_uczestnictwa_Anna_Przykladowa.docx"]
    assert "zawarta w dniu 20.10.2026" in umowa
    assert "Panią/Panem Anna Przykładowa" in umowa
    assert "Tel: 600100200, e-mail anna@example.com" in umowa
    harmonogram = texts["2_Zalacznik_1_Harmonogram_Anna_Przykladowa.docx"]
    assert "od 02.11.2026 r. do 16.11.2026 r." in harmonogram
    assert "Jan Rekruter" in texts["5_Protokol_przekazania_Manuala_Anna_Przykladowa.docx"]
    for text in texts.values():
        assert "{{" not in text and "{%" not in text


def test_missing_pesel_and_address_leave_dotted_lines_to_fill_by_hand():
    umowa = _texts(docs.render_package(_data()))["1_Umowa_uczestnictwa_Anna_Przykladowa.docx"]
    assert f"Pesel: {docs.DOTS}" in umowa
    assert f"pod adresem: {docs.DOTS}" in umowa


def test_pesel_and_address_go_into_the_contract_when_given():
    umowa = _texts(
        docs.render_package(_data(pesel="44051401359", address="ul. Przykładowa 1, Warszawa"))
    )["1_Umowa_uczestnictwa_Anna_Przykladowa.docx"]
    assert "Pesel: 44051401359" in umowa
    assert "ul. Przykładowa 1, Warszawa" in umowa


def test_templates_carry_no_names_from_the_sample_documents():
    """Repo jest publiczne — przykładowe osoby z wzorów działu to pola."""
    for path in docs.TEMPLATE_DIR.glob("*.docx"):
        raw = zipfile.ZipFile(path).read("word/document.xml").decode("utf-8")
        assert not re.search(r"Cichosz|Trzeciak", raw), path.name


def test_file_stem_is_ascii():
    assert docs.file_stem("Łucja Żółć-Nowak") == "Lucja_Zolc-Nowak"
    assert docs.file_stem("   ") == "Uczestnik"
