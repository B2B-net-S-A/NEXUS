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
  ``doc.new_start_clause`` z trybem daty; generator aneksów dokłada
  ``doc.paragraph_ref`` („§ 6 ust. 1”), ``doc.rate_single`` i
  ``doc.rate_lines`` (gotowe zdania o stawkach),
* ``document_date``, ``document_place``, ``language``.

Szablon nigdy nie formatuje sam — jedna reguła formatu na wszystkie dokumenty.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.services.b2b_contract_generator.formatting import (
    format_rate,
    pl_date,
    start_clause,
)
from app.services.b2b_contract_generator.company_variant import (
    representation_pl_fallback,
)
from app.services.b2b_contract_generator.gender import gender_forms
from app.services.b2b_contract_generator.number_words import (
    pln_words_with_fraction,
    rate_in_words,
)
from app.services.b2b_documents.company_party import company_party
from app.services.b2b_documents.contract_versions import (
    ContractVersionRefs,
    default_refs,
)
from app.services.b2b_documents.registry import DocumentType, parse_amount

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
    # Spółka (generator aneksów, komparycja z KRS jak w umowie spółki).
    "partner_seat_locative": "seat_locative",
    "partner_krs": "krs",
    "partner_registry_court": "registry_court",
    "partner_representative_name": "representative_name",
    "partner_representative_function": "representative_function",
}

#: Pola typów sprzed generatora aneksów (29.09.2026), których rejestr już nie
#: deklaruje. Zapisane wtedy dokumenty pobiera się ponownie starym payloadem
#: (także wersje EN), więc kontekst dalej je formatuje.
_LEGACY_PASSTHROUGH: dict[str, tuple[str, ...]] = {
    "annex_rate_change": ("new_rate", "currency"),
    "annex_start_date": ("new_start_date_mode",),
    "annex_party_data": ("entity_type", "company_krs", "company_representative"),
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
            if number is not None and not math.isfinite(number):
                number = None
            out[f.key] = format_rate(number) or "…"
            try:
                words = (
                    rate_in_words(number, language, currency)
                    if number is not None
                    else "…"
                )
            except ValueError:
                # Kwota poza słownikiem liczb — podgląd pokazuje „…”, a zapis
                # i tak odrzuca ją walidacją (`registry.invalid_values`).
                words = "…"
            out[f"{f.key}_words"] = words
        elif f.kind == "bool":
            out[f.key] = bool(raw)
        else:
            out[f.key] = raw if raw not in (None, "") else None
            if f.options:
                labels = dict(f.options)
                out[f"{f.key}_label"] = labels.get(raw)
    # Pochodne, których szablon nie powinien liczyć sam. Runda 10
    # (R10-N14-4): fraza powstaje zawsze, gdy typ ma pole daty startu — także
    # przy pustej dacie („…”). Podgląd świeżego formularza kończył się 500
    # (`StrictUndefined` na `doc.new_start_clause`).
    if "new_start_date" in values or any(
        f.key == "new_start_date" for f in doc_type.fields
    ):
        out["new_start_clause"] = start_clause(
            _as_date(values.get("new_start_date")),
            values.get("new_start_date_mode") or "exact",
            language,
        )
    _legacy_values(doc_type, values, language, currency, out)
    extra_text = values.get("extra_provisions")
    out["extra_provisions_list"] = (
        [line.strip() for line in extra_text.splitlines() if line.strip()]
        if isinstance(extra_text, str)
        else []
    )
    return out


def _legacy_values(
    doc_type: DocumentType,
    values: dict[str, Any],
    language: str,
    currency: str,
    out: dict[str, Any],
) -> None:
    for key in _LEGACY_PASSTHROUGH.get(doc_type.key, ()):
        if key in out:
            continue
        raw = values.get(key)
        if key == "new_rate":
            number = parse_amount(raw)
            out[key] = format_rate(number) or "…"
            try:
                out["new_rate_words"] = (
                    rate_in_words(number, language, currency)
                    if number is not None
                    else "…"
                )
            except ValueError:
                out["new_rate_words"] = "…"
        elif key == "currency":
            out[key] = raw or currency
        elif key == "entity_type":
            out[key] = raw or "sole_trader"
        else:
            out[key] = raw if raw not in (None, "") else None


def _rate_phrase(item: dict[str, Any], *, bullet: bool) -> str:
    """Jedna pozycja stawki: „[Od …] wynagrodzenie w wysokości … [w okresie
    do …] [dla Klienta B2BNET – …]”. Elementy opcjonalne tylko, gdy wypełnione
    (ticket 29.09.2026, pkt 6.8)."""
    amount = parse_amount(item.get("rate"))
    words = pln_words_with_fraction(amount) if amount is not None else "…"
    shown = format_rate(amount) if amount is not None else "…"
    parts: list[str] = []
    start = _as_date(item.get("from"))
    if start is not None:
        parts.append(f"{'Od' if bullet else 'od'} {pl_date(start)} roku")
    parts.append(
        f"wynagrodzenie w wysokości {shown} zł (słownie: {words}) netto + VAT "
        "za każdą roboczogodzinę"
    )
    end = _as_date(item.get("to"))
    if end is not None:
        parts.append(f"w okresie do {pl_date(end)} roku")
    client = (item.get("client_name") or "").strip()
    if client:
        parts.append(f"dla Klienta B2BNET – {client}")
    phrase = " ".join(parts)
    # Zdanie kończy kropka — nazwa klienta „… S.A.” niesie ją już sama.
    return phrase if phrase.endswith(".") else f"{phrase}."


def _rate_items(values: dict[str, Any]) -> list[dict[str, Any]]:
    items = values.get("rate_items")
    if isinstance(items, list) and items:
        return [i for i in items if isinstance(i, dict)]
    # Dokument sprzed generatora aneksów: jedna stawka od daty wejścia w życie.
    legacy = values.get("new_rate")
    if legacy not in (None, ""):
        return [{"rate": legacy}]
    return []


def _annex_values(
    doc_type: DocumentType,
    values: dict[str, Any],
    refs: dict[str, str],
    out: dict[str, Any],
) -> None:
    """Pochodne generatora aneksów — liczone tu, nie w szablonie."""
    paragraph = str(values.get("paragraph") or "").strip()
    section = str(values.get("paragraph_section") or "").strip()
    if paragraph:
        paragraph = paragraph.lstrip("§").strip()
        out["paragraph_ref"] = (
            f"§ {paragraph} ust. {section}" if section else f"§ {paragraph}"
        )
    elif doc_type.key == "annex_rate_change":
        out["paragraph_ref"] = refs.get("rate_paragraph") or "§ …"
    elif doc_type.key == "annex_start_date":
        out["paragraph_ref"] = refs.get("start_paragraph") or "§ …"
    else:
        out["paragraph_ref"] = "§ …"
    effective = _as_date(values.get("effective_date"))
    out["effective_clause"] = (
        f"Ustalone zmiany wchodzą w życie z dniem {pl_date(effective)} r."
        if effective is not None
        # Aneks daty startu sprzed generatora nie miał tej daty — obowiązywał
        # z dniem podpisania i tak ma się pobrać ponownie.
        else "Ustalone zmiany wchodzą w życie z dniem podpisania niniejszego aneksu."
    )
    items = _rate_items(values)
    single = len(items) <= 1
    out["rate_single"] = single
    out["rate_sentence"] = (
        _rate_phrase(items[0], bullet=False)
        if items
        else _rate_phrase({}, bullet=False)
    )
    out["rate_lines"] = [_rate_phrase(i, bullet=True) for i in items]


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
    partner["is_company"] = values.get("partner_variant") == "company"
    capital = str(values.get("partner_share_capital") or "").strip()
    if capital and not any(u in capital.lower() for u in ("zł", "pln")):
        capital = f"{capital} zł"
    partner["share_capital"] = capital or None
    partner["representation"] = str(
        values.get("partner_representation") or ""
    ).strip() or representation_pl_fallback(
        values.get("partner_representative_name"),
        values.get("partner_representative_function"),
        values.get("gender"),
    )
    forms = gender_forms(values.get("gender"))
    if partner["is_company"]:
        # Partnerem jest spółka — „zwaną dalej Partnerem” (jak w umowie spółki).
        forms["g_zwanym"] = "zwaną"
        forms["g_zwany"] = "zwana"
    contract_number = str(values.get("contract_number") or "").strip()
    signing_date = _as_date(values.get("contract_signing_date"))
    effective_refs = (refs or default_refs()).as_context()
    for key, value in (ref_overrides or {}).items():
        if value:
            effective_refs[key] = value
    doc_values = _format_doc_values(doc_type, values, language, currency)
    _annex_values(doc_type, values, effective_refs, doc_values)
    if doc_type.key == "annex_start_date" and not values.get("current_start_date"):
        # Dokument sprzed generatora aneksów: obecna data z umowy bazowej.
        doc_values["current_start_date"] = pl_date(base.start_date)
    return {
        "language": language,
        "company": company_party(language),
        "partner": partner,
        "base": {
            "contract_number": contract_number or base.contract_number or "…",
            "signing_date": pl_date(signing_date or base.signing_date),
            "start_clause": start_clause(
                base.start_date, base.start_date_mode or "exact", language
            ),
            "client_name": base.client_name,
            "client_legal_name": base.client_legal_name or base.client_name,
            "currency": base.currency,
            **base.extra,
        },
        "refs": effective_refs,
        "g": forms,
        "dg": gender_forms(values.get("delegate_gender")),
        "doc": doc_values,
        "document_date": pl_date(_as_date(values.get("document_date"))),
        "document_place": company_party(language)["place"],
    }
