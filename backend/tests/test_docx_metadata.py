"""Właściwości pliku Word bez danych z szablonu (`app/core/docx_metadata.py`)."""

from __future__ import annotations

import io
import zipfile

from app.core.docx_metadata import clear_app_properties

APP_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">'
    "<Template>Normal.dotm</Template><Manager>Jan Przykładowy</Manager>"
    "<Company>Kancelaria Przykładowa &amp; Wspólnicy</Company><Pages>2</Pages></Properties>"
)


def _docx(app_xml: str | None) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "<w:document/>")
        if app_xml is not None:
            archive.writestr("docProps/app.xml", app_xml)
    return out.getvalue()


def _read(data: bytes, name: str) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return archive.read(name).decode("utf-8")


def test_company_and_manager_are_emptied_and_the_rest_stays() -> None:
    cleaned = clear_app_properties(_docx(APP_XML))
    app = _read(cleaned, "docProps/app.xml")
    assert "Kancelaria" not in app and "Przykładowy" not in app
    assert "<Company/>" in app and "<Manager/>" in app
    assert "<Template>Normal.dotm</Template>" in app and "<Pages>2</Pages>" in app
    assert _read(cleaned, "word/document.xml") == "<w:document/>"
    with zipfile.ZipFile(io.BytesIO(cleaned)) as archive:
        assert archive.namelist() == [
            "[Content_Types].xml",
            "word/document.xml",
            "docProps/app.xml",
        ]


def test_prefixed_company_and_manager_are_emptied_too() -> None:
    """Word zapisuje czasem pola z prefiksem przestrzeni nazw (``<ap:Company>``,
    wzór umowy zlecenia z 26.10.2026) — nazwa kancelarii nie może przejść."""
    prefixed = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<ap:Properties xmlns:ap="http://schemas.openxmlformats.org/officeDocument/'
        '2006/extended-properties"><ap:Manager>Jan Przykładowy</ap:Manager>'
        "<ap:Company>Kancelaria Przykładowa</ap:Company><ap:Pages>2</ap:Pages>"
        "</ap:Properties>"
    )
    app = _read(clear_app_properties(_docx(prefixed)), "docProps/app.xml")
    assert "Kancelaria" not in app and "Przykładowy" not in app
    assert "<ap:Company/>" in app and "<ap:Manager/>" in app
    assert "<ap:Pages>2</ap:Pages>" in app


def test_file_without_app_properties_or_names_is_returned_as_is() -> None:
    plain = _docx(None)
    assert clear_app_properties(plain) is plain
    empty = _docx(
        APP_XML.replace("Jan Przykładowy", "").replace(
            "Kancelaria Przykładowa &amp; Wspólnicy", ""
        )
    )
    assert clear_app_properties(empty) is empty
