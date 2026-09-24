"""Kontekst renderu dokumentu pochodnego — kształt, który czytają szablony.

Szablony ``app/templates/documents/<typ>_<język>.{docx,html}`` widzą:

* ``company.*`` — strona B2B.net (``company_party``),
* ``partner.*`` — Partner: ``name``, ``name_instrumental``, ``legal_name``,
  ``business_address``, ``nip``, ``regon``, ``home_address``, ``id_document``,
  ``id_document_issuer``, ``pesel`` (trzy ostatnie tylko w chwili renderu —
  nigdy z bazy),
* ``base.*`` — umowa bazowa: ``contract_number``, ``signing_date`` (tekst
  DD.MM.RRRR), ``start_clause``, ``client_name``, ``client_legal_name``,
  ``currency``,
* ``refs.*`` — numery paragrafów umowy bazowej (``contract_versions``),
* ``g.*`` — formy rodzajowe Partnera (``gender_forms``); ``dg.*`` — osoby
  skierowanej,
* ``doc.*`` — pola formularza: daty jako tekst DD.MM.RRRR, kwoty jako
  „150”/„135,50” z parą ``<klucz>_words`` (słownie), bool jako bool,
  ``doc.new_start_clause`` z trybem daty,
* ``document_date``, ``document_place``, ``language``.

Szablon nigdy nie formatuje sam — jedna reguła formatu na wszystkie dokumenty.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.services.b2b_contract_generator.formatting import (
    format_rate,
    pl_date,
    start_clause,
)
from app.services.b2b_contract_generator.gender import gender_forms
from app.services.b2b_contract_generator.number_words import rate_in_words
from app.services.b2b_documents.company_party import company_party
from app.services.b2b_documents.contract_versions import (
    ContractVersionRefs,
    default_refs,
)
from app.services.b2b_documents.registry import DocumentType

PARTNER_KEYS = {
    "partner_name": "name",
    "partner_instrumental": "name_instrumental",
    "partner_legal_name": "legal_name",
    "partner_business_address": "business_address",
    "partner_nip": "nip",
    "partner_regon": "regon",
    "partner_home_address": "home_address",
    "id_document": "id_document",
    "id_document_issuer": "id_document_issuer",
    "pesel": "pesel",
}


@dataclass
class BaseContractInfo:
    """Dane umowy bazowej potrzebne dokumentowi (z wiersza rejestru)."""

    contract_number: str | None = None
    signing_date: date | None = None
    start_date: date | None = None
    start_date_mode: str | None = None
    client_name: str | None = None
    client_legal_name: str | None = None
    currency: str = "PLN"
    template_version: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def _as_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _format_doc_values(
    doc_type: DocumentType, values: dict[str, Any], language: str, currency: str
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for f in doc_type.fields:
        raw = values.get(f.key)
        if f.kind == "date":
            parsed = _as_date(raw)
            out[f.key] = pl_date(parsed) if parsed else pl_date(None)
            out[f"{f.key}_iso"] = parsed.isoformat() if parsed else None
        elif f.kind == "money":
            number = None
            try:
                number = float(raw) if raw not in (None, "") else None
            except (TypeError, ValueError):
                number = None
            out[f.key] = format_rate(number) or "…"
            out[f"{f.key}_words"] = (
                rate_in_words(number, language, currency) if number is not None else "…"
            )
        elif f.kind == "bool":
            out[f.key] = bool(raw)
        else:
            out[f.key] = raw if raw not in (None, "") else None
            if f.options:
                labels = dict(f.options)
                out[f"{f.key}_label"] = labels.get(raw)
    # Pochodne, których szablon nie powinien liczyć sam.
    if "new_start_date" in values:
        out["new_start_clause"] = start_clause(
            _as_date(values.get("new_start_date")),
            values.get("new_start_date_mode") or "exact",
            language,
        )
    extra_text = values.get("extra_provisions")
    out["extra_provisions_list"] = (
        [line.strip() for line in extra_text.splitlines() if line.strip()]
        if isinstance(extra_text, str)
        else []
    )
    return out


def build_document_context(
    doc_type: DocumentType,
    values: dict[str, Any],
    *,
    language: str,
    base: BaseContractInfo | None,
    refs: ContractVersionRefs | None,
    ref_overrides: dict[str, str] | None = None,
) -> dict[str, Any]:
    base = base or BaseContractInfo()
    currency = str(values.get("currency") or base.currency or "PLN")
    partner = {
        target: (values.get(source) or None) for source, target in PARTNER_KEYS.items()
    }
    partner["display_name"] = partner.get("legal_name") or partner.get("name")
    effective_refs = (refs or default_refs()).as_context()
    for key, value in (ref_overrides or {}).items():
        if value:
            effective_refs[key] = value
    return {
        "language": language,
        "company": company_party(language),
        "partner": partner,
        "base": {
            "contract_number": base.contract_number or "…",
            "signing_date": pl_date(base.signing_date),
            "start_clause": start_clause(
                base.start_date, base.start_date_mode or "exact", language
            ),
            "client_name": base.client_name,
            "client_legal_name": base.client_legal_name or base.client_name,
            "currency": base.currency,
            **base.extra,
        },
        "refs": effective_refs,
        "g": gender_forms(values.get("gender")),
        "dg": gender_forms(values.get("delegate_gender")),
        "doc": _format_doc_values(doc_type, values, language, currency),
        "document_date": pl_date(_as_date(values.get("document_date"))),
        "document_place": company_party(language)["place"],
    }
