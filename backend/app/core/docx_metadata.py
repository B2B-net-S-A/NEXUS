"""Właściwości pliku Word bez danych osób z szablonu.

Szablon (firmowy szablon CV, zamrożony szablon etapu, szablon z reguły
klienta) niesie w ``docProps/core.xml`` autora i osobę, która ostatnio go
zapisała — u nas login i imię i nazwisko pracownika. python-docx przepisuje
te pola do każdego pliku zrobionego z szablonu, więc plik u klienta (i PDF
z niego, bo LibreOffice bierze autora z Worda) pokazywał we „Właściwościach”
osobę z firmy (14.10.2026).

Pola zostają puste, nie dostają nazwy firmy: szablony bywają różnych marek,
a pusty autor niczego nie mówi o nikim. Język i daty dokumentu zostają.

Umowy i dokumenty B2B (14.10.2026): szablony mają też w ``docProps/app.xml``
firmę (kancelarię, która je przygotowała) i kierownika — tych pól
python-docx nie obsługuje, więc czyści je ``clear_app_properties`` na
gotowym pliku.
"""

from __future__ import annotations

import io
import re
import zipfile

from docx.document import Document

TEXT_FIELDS = (
    "author",
    "last_modified_by",
    "title",
    "subject",
    "comments",
    "keywords",
    "category",
    "content_status",
    "identifier",
    "version",
)


def clear_author_metadata(document: Document) -> None:
    """Czyści tekstowe właściwości dokumentu (autor, ostatnio zapisał, opis)."""
    properties = document.core_properties
    for name in TEXT_FIELDS:
        setattr(properties, name, "")


_APP_PART = "docProps/app.xml"
# Z prefiksem przestrzeni nazw też (`<ap:Company>` — wzór umowy zlecenia, 26.10.2026).
_APP_FIELDS = re.compile(rb"<((?:\w+:)?(?:Company|Manager))>[^<]+</\1>")


def clear_app_properties(docx: bytes) -> bytes:
    """Plik bez firmy i kierownika w ``docProps/app.xml``; reszta archiwum bez zmian.

    Plik bez tych pól (albo bez ``app.xml``) wraca ten sam, bez przepakowania.
    """
    with zipfile.ZipFile(io.BytesIO(docx)) as source:
        if _APP_PART not in source.namelist():
            return docx
        app = source.read(_APP_PART)
        cleaned = _APP_FIELDS.sub(rb"<\1/>", app)
        if cleaned == app:
            return docx
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as target:
            for item in source.infolist():
                data = cleaned if item.filename == _APP_PART else source.read(item)
                # `ZipInfo` niesie sposób kompresji i kolejność części.
                target.writestr(item, data)
    return out.getvalue()
