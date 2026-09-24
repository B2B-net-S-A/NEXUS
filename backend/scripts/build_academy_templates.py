"""Buduje szablony dokumentów Akademii ze wzorów działu (24.09.2026).

Wzory (DOCX od Artura) mają pola do wypełnienia zapisane kropkami
(„……………”) albo podkreśleniami. Skrypt zamienia KOLEJNE grupy kropek na pola
Jinja (``docxtpl``) w stałej kolejności per dokument, a linie podpisów na
końcu zostawia. Protokół przekazania miał wpisane przykładowe osoby —
zamieniamy je na pola, żeby do publicznego repo nie trafiły nazwiska.

Użycie (wzory leżą poza repo)::

    python scripts/build_academy_templates.py \\
        --umowa "Umowa_wzór.docx" --harmonogram "Zalacznik_1.docx" \\
        --oswiadczenie "Oswiadczenie_wzór.docx" --regulamin "Regulamin.docx" \\
        --protokol "protokol.docx"

Protokół przyszedł jako ``.doc`` — przed uruchomieniem przekonwertuj go do
``.docx`` (macOS: ``textutil -convert docx``).

Zmieniasz wzór = uruchamiasz skrypt ponownie; szablony w
``app/templates/academy`` są wynikiem, nie źródłem.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import docx

OUT_DIR = Path(__file__).resolve().parents[1] / "app" / "templates" / "academy"

# Kolejność pól = kolejność grup kropek w dokumencie.
FIELDS = {
    "umowa": [
        "signing_date",
        "participant_name",
        "address",
        "pesel",
        "phone",
        "email",
    ],
    "harmonogram": ["program_start", "program_end"],
    "oswiadczenie": ["participant_name"],
}

# Stałe napisy z przykładowego protokołu → pola.
PROTOKOL_REPLACEMENTS = {
    "02.03.2026": "{{ protocol_date }}",
    "Kacper Cichosz": "{{ participant_name }}",
    "Katarzyna Trzeciak": "{{ handover_name }}",
}

_FILL = re.compile(r"[…\.]{2,}|_{3,}")


def _clear_metadata(document: docx.document.Document) -> None:
    props = document.core_properties
    props.author = "B2B.net S.A."
    props.last_modified_by = "B2B.net S.A."
    props.comments = ""
    props.title = props.title or ""


def fill_placeholders(document: docx.document.Document, fields: list[str]) -> int:
    """Zamienia kolejne grupy kropek na ``{{ pole }}``. Zwraca liczbę pól."""
    queue = list(fields)
    for paragraph in document.paragraphs:
        continuing = False
        for run in paragraph.runs:
            text = run.text
            if continuing:
                stripped = text.lstrip("…._")
                if stripped != text:
                    text = stripped
                continuing = False
            if queue and _FILL.search(text):

                def _swap(match: re.Match[str]) -> str:
                    return "{{ %s }}" % queue.pop(0) if queue else match.group(0)

                new_text = _FILL.sub(_swap, text, count=1)
                # Grupa kropek na końcu przebiegu może ciągnąć się w następnym.
                match = _FILL.search(text)
                continuing = bool(match and match.end() == len(text))
                text = new_text
            run.text = text
        if not queue:
            break
    return len(fields) - len(queue)


def replace_literals(document: docx.document.Document, mapping: dict[str, str]) -> None:
    for paragraph in document.paragraphs:
        for run in paragraph.runs:
            for old, new in mapping.items():
                if old in run.text:
                    run.text = run.text.replace(old, new)


def build(args: argparse.Namespace) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for key, source in (
        ("umowa", args.umowa),
        ("harmonogram", args.harmonogram),
        ("oswiadczenie", args.oswiadczenie),
    ):
        document = docx.Document(source)
        placed = fill_placeholders(document, FIELDS[key])
        if placed != len(FIELDS[key]):
            raise SystemExit(f"{key}: wstawiono {placed} z {len(FIELDS[key])} pól")
        _clear_metadata(document)
        document.save(OUT_DIR / f"{key}.docx")

    protokol = docx.Document(args.protokol)
    replace_literals(protokol, PROTOKOL_REPLACEMENTS)
    _clear_metadata(protokol)
    protokol.save(OUT_DIR / "protokol.docx")

    regulamin = docx.Document(args.regulamin)
    _clear_metadata(regulamin)
    regulamin.save(OUT_DIR / "regulamin.docx")
    print(f"Zapisano szablony w {OUT_DIR}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("umowa", "harmonogram", "oswiadczenie", "regulamin", "protokol"):
        parser.add_argument(f"--{name}", required=True)
    build(parser.parse_args())


if __name__ == "__main__":
    main()
