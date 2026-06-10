"""Render umowy B2B do DOCX (docxtpl na oryginalnym szablonie prawnym).

Zachowuje dokładne formatowanie umowy (token-replacement, nie odbudowa).
`autoescape=True` w środowisku Jinja zapewnia poprawne escapowanie wartości
do XML (& < >), a `RichText` (scope) jest wstawiany przez docxtpl z pominięciem
escapowania.
"""

from __future__ import annotations

import io
from pathlib import Path

from docxtpl import DocxTemplate
from jinja2 import Environment

from app.models.contract import Contract
from app.services.b2b_contract_generator.clause_overrides import (
    apply_ops_docx,
    overrides_for_client,
)
from app.services.b2b_contract_generator.field_mapping import build_docx_context
from app.services.b2b_contract_generator.formatting import pl_date

TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "templates" / "contract"


def normalize_language(language: str | None) -> str:
    return "en" if (language or "pl").lower().startswith("en") else "pl"


def template_path(language: str | None) -> Path:
    return TEMPLATE_DIR / f"umowa_b2b_{normalize_language(language)}.docx"


def _jinja_env() -> Environment:
    env = Environment(autoescape=True)
    env.filters["pl_date"] = pl_date
    return env


def render_from_context(context: dict, *, language: str | None = "pl") -> bytes:
    """Render gotowego kontekstu (do testów bez DB)."""
    path = template_path(language)
    if not path.is_file():
        raise FileNotFoundError(f"Brak szablonu DOCX: {path}")
    tpl = DocxTemplate(str(path))
    tpl.render(context, jinja_env=_jinja_env())
    # Per-klient modyfikacje umowy (np. § 10 Centrum e-Zdrowia/PFRON, § 4 BNP,
    # Załączniki CA/BIK) — podmiana w już wyrenderowanym dokumencie; brak
    # operacji = render bez zmian.
    client = context.get("client") or {}
    ops = overrides_for_client(
        client.get("name") or client.get("legal_name"),
        normalize_language(language),
    )
    if ops:
        apply_ops_docx(tpl.docx, ops)
    buf = io.BytesIO()
    tpl.save(buf)
    return buf.getvalue()


def render_contract_docx(contract: Contract, *, language: str | None = "pl") -> bytes:
    """Wyrenderuj DOCX umowy B2B dla danego kontraktu."""
    return render_from_context(build_docx_context(contract), language=language)
