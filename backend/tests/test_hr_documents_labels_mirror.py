"""Słownik e-teczki jest JEDEN — serwer i front mówią o rodzajach i kręgu tak samo.

Źródło: ``services/hr/documents_rules`` (``KIND_LABELS``, ``DEFAULT_AUDIENCE``);
front ma lustro słowo w słowo w ``frontend/src/lib/api/hr-documents.ts``.
Rozjazd = Kadry wybierają rodzaj, który serwer nazywa inaczej, albo okno
podpowiada inny krąg widzących niż ten, który serwer zapisze bez znaczników.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.services.hr.documents_rules import DEFAULT_AUDIENCE, KIND_LABELS
from app.services.hr_documents_schema import DOCUMENT_KINDS

_FRONT = (
    Path(__file__).resolve().parents[2]
    / "frontend"
    / "src"
    / "lib"
    / "api"
    / "hr-documents.ts"
)
_LABELS = re.compile(
    r"export const DOCUMENT_KIND_LABELS: Record<DocumentKind, string> = \{(.*?)\n\};",
    re.S,
)
_AUDIENCE = re.compile(
    r"export const DEFAULT_AUDIENCE: Record<DocumentKind, DocumentAudience> = \{(.*?)\n\};",
    re.S,
)
_KINDS = re.compile(r"export const DOCUMENT_KINDS: DocumentKind\[\] = \[(.*?)\];", re.S)
_LABEL_ENTRY = re.compile(r'^\s+(\w+): "([^"]*)",$', re.M)
_AUDIENCE_ENTRY = re.compile(
    r"^\s+(\w+): \{ person: (true|false), payroll: (true|false), "
    r"equipment: (true|false) \},$",
    re.M,
)


def _source() -> str:
    return _FRONT.read_text(encoding="utf-8")


def test_frontend_kind_labels_are_the_backend_labels_word_for_word() -> None:
    match = _LABELS.search(_source())
    assert match, "Nie znaleziono DOCUMENT_KIND_LABELS w hr-documents.ts"
    assert dict(_LABEL_ENTRY.findall(match.group(1))) == KIND_LABELS


def test_frontend_kind_order_is_the_schema_order() -> None:
    match = _KINDS.search(_source())
    assert match, "Nie znaleziono DOCUMENT_KINDS w hr-documents.ts"
    assert tuple(re.findall(r'"(\w+)"', match.group(1))) == DOCUMENT_KINDS


def test_frontend_default_audience_is_the_backend_default() -> None:
    match = _AUDIENCE.search(_source())
    assert match, "Nie znaleziono DEFAULT_AUDIENCE w hr-documents.ts"
    front = {
        kind: (person == "true", payroll == "true", equipment == "true")
        for kind, person, payroll, equipment in _AUDIENCE_ENTRY.findall(match.group(1))
    }
    assert front == DEFAULT_AUDIENCE
