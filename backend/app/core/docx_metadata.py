"""Właściwości pliku Word bez danych osób z szablonu.

Szablon (firmowy szablon CV, zamrożony szablon etapu, szablon z reguły
klienta) niesie w ``docProps/core.xml`` autora i osobę, która ostatnio go
zapisała — u nas login i imię i nazwisko pracownika. python-docx przepisuje
te pola do każdego pliku zrobionego z szablonu, więc plik u klienta (i PDF
z niego, bo LibreOffice bierze autora z Worda) pokazywał we „Właściwościach”
osobę z firmy (14.10.2026).

Pola zostają puste, nie dostają nazwy firmy: szablony bywają różnych marek,
a pusty autor niczego nie mówi o nikim. Język i daty dokumentu zostają.
"""

from __future__ import annotations

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
