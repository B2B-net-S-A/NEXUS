"""Render dokumentu pochodnego do DOCX (plik do podpisu) i HTML (podgląd).

Szablony: ``app/templates/documents/<typ>_<język>.docx`` i ``.html`` —
budowane skryptem ``scripts/build_b2b_document_templates.py`` ze wzorów działu.
Warianty (JDG/spółka, zakaz konkurencji zachowany/zwolniony) są warunkami
wewnątrz jednego szablonu, nie osobnymi plikami.

Rejestr klauzul klienta (``clause_overrides``) celowo NIE jest tu stosowany:
jego kotwice to paragrafy UMOWY, a dokument pochodny ich nie ma — aneks
dostałby klauzule umowy albo ``ClauseOverrideError``.
"""

from __future__ import annotations

import io
import re
from pathlib import Path

from docxtpl import DocxTemplate
from jinja2 import Environment, StrictUndefined
from jinja2.sandbox import SandboxedEnvironment

from app.core.docx_metadata import clear_app_properties, clear_author_metadata
from app.services.b2b_contract_generator.formatting import pl_date

TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "templates" / "documents"


def template_key(doc_type_key: str, language: str, revision: str = "") -> str:
    """Klucz pliku szablonu: ``<typ>[_<rewizja>]_<język>``.

    Rewizja (``DocumentType.template_revision``) zmienia się razem z treścią
    wzoru — wydany dokument zapisuje swój klucz i pobiera się tym samym
    tekstem (``stored_or_current_key``)."""
    if revision:
        return f"{doc_type_key}_{revision}_{language}"
    return f"{doc_type_key}_{language}"


#: Klucz zapisany w wierszu idzie do ścieżki pliku — tylko nazwa, bez ścieżek.
_SAFE_KEY = re.compile(r"[a-z0-9_]{1,80}")


def stored_or_current_key(stored: str | None, current: str) -> str:
    """Szablon wydanego dokumentu: zapisany klucz, gdy jego plik jest w repo;
    inaczej bieżący (plik sprzed rewizji usunięty albo klucz nieczytelny)."""
    if (
        stored
        and stored != current
        and _SAFE_KEY.fullmatch(stored)
        and docx_path(stored).is_file()
        and html_path(stored).is_file()
    ):
        return stored
    return current


def docx_path(key: str) -> Path:
    return TEMPLATE_DIR / f"{key}.docx"


def html_path(key: str) -> Path:
    return TEMPLATE_DIR / f"{key}.html"


def _docx_env() -> Environment:
    # StrictUndefined: literówka w szablonie ma paść w teście renderu, a nie
    # wyjść do Partnera jako puste miejsce w dokumencie.
    env = Environment(
        autoescape=True,
        undefined=StrictUndefined,
        # `None` w kontekście = brak danych, nie napis „None” w dokumencie.
        finalize=lambda v: "" if v is None else v,
    )
    env.filters["pl_date"] = pl_date
    return env


def _html_env() -> SandboxedEnvironment:
    env = SandboxedEnvironment(
        autoescape=True,
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        finalize=lambda v: "" if v is None else v,
    )
    env.filters["pl_date"] = pl_date
    return env


def render_docx(key: str, context: dict) -> bytes:
    tpl = DocxTemplate(str(docx_path(key)))
    tpl.render(context, jinja_env=_docx_env())
    # Plik idzie do Partnera: bez autora i kancelarii z szablonu.
    clear_author_metadata(tpl.docx)
    buf = io.BytesIO()
    tpl.save(buf)
    return clear_app_properties(buf.getvalue())


def render_html(key: str, context: dict) -> str:
    source = html_path(key).read_text(encoding="utf-8")
    return _html_env().from_string(source).render(**context)
