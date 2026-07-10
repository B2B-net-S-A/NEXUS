"""Budowa kontekstu szablonu B2B z surowych pól (tryb standalone / ręczny).

Produkuje tę samą strukturę co `_contract_vars` (candidate/client/contract/b2b/
job), więc oba szablony (DOCX docxtpl + HTML Jinja) renderują się bez zmian —
ale dane pochodzą wprost z formularza, bez rekordu `Contract`.
"""

from __future__ import annotations

from typing import Optional

from app.models.b2b_contract_role import B2BContractRole
from app.services.b2b_contract_generator.formatting import format_rate, start_clause
from app.services.b2b_contract_generator.gender import gender_forms
from app.services.b2b_contract_generator.number_words import rate_in_words
from app.services.b2b_contract_generator.rate_clause import (
    RateStage,
    build_rate_clause,
)


def build_render_context(req, role: Optional[B2BContractRole]) -> dict:
    """Zbuduj kontekst szablonu z pól `B2BRenderRequest` + wybranej roli."""
    lang = "en" if (req.language or "pl").lower().startswith("en") else "pl"

    # Znormalizowany adres do korespondencji — szablon renderuje etykietę pod
    # `{% if %}`, więc wartość whitespace-only musi zejść do None (inaczej w
    # umowie wyląduje etykieta z pustym adresem).
    correspondence = (req.partner_correspondence_address or "").strip() or None

    if role is not None:
        area_label = role.area_label_en if lang == "en" else role.area_label_pl
        role_name = role.name_en if lang == "en" else role.name_pl
        default_scope = role.scope_en if lang == "en" else role.scope_pl
    else:
        area_label = role_name = None
        default_scope = []
    scope_items = req.scope_items_override or default_scope or []

    words = req.rate_in_words or rate_in_words(
        req.rate_candidate, lang, req.currency or "PLN"
    )

    # Zdanie o stawce (§5): pojedyncza kwota lub „stawka progresywna" z okresami
    # obowiązywania. Stare payloady bez `rate_stages` → jeden etap z
    # `rate_candidate` (render identyczny z historycznym).
    stages = [
        RateStage(
            rate=s.rate, effective_from=s.effective_from, effective_to=s.effective_to
        )
        for s in (getattr(req, "rate_stages", None) or [])
    ] or [RateStage(rate=req.rate_candidate)]
    rate_clause = build_rate_clause(
        stages,
        language=lang,
        currency=req.currency or "PLN",
        words_override=req.rate_in_words if len(stages) == 1 else None,
    )

    return {
        "candidate": {
            "id": None,
            "name": req.partner_name,
            "lastname": None,
            "full_name": req.partner_name,
            "email": req.partner_email,
            "phone": req.partner_phone,
            "address": correspondence or req.partner_business_address,
            "legal_name": req.partner_legal_name,
            "nip": req.partner_nip,
            "regon": req.partner_regon,
            "business_address": req.partner_business_address,
            "business_form": None,
        },
        "client": {
            "id": None,
            "name": req.client_name,
            "address": None,
            "legal_name": req.client_name,
            "nip": None,
            "regon": None,
        },
        "contract": {
            "id": None,
            "start_date": req.start_date,
            "end_date": None,
            # Postać wyświetlana w umowie („135,50" / „150"); słownie liczone
            # niżej z wartości liczbowej `req.rate_candidate`.
            "rate_candidate": format_rate(req.rate_candidate),
            "rate_client": None,
            "currency": req.currency or "PLN",
            "rate_unit": "hourly",
            "billing_hours_per_month": 160,
            "contract_type": "b2b",
            "project_name": None,
            "team_name": None,
            "office_location": req.project_city,
            "work_mode": None,
            "client_pm_name": None,
            "client_pm_email": None,
        },
        "job": {"id": None, "title": None},
        "b2b": {
            "contract_number": req.contract_number,
            "signing_date": req.signing_date,
            "project_city": req.project_city,
            "project_description": req.project_description,
            "correspondence_address": correspondence,
            "rate_in_words": words,
            "rate_clause": rate_clause,
            "language": lang,
            "area_label": area_label,
            "role_name": role_name,
            "scope_items": scope_items,
            "start_clause": start_clause(
                req.start_date, getattr(req, "start_date_mode", None), lang
            ),
            # Forma narzędnika do komparycji (liczona w FE); pusty → mianownik.
            "partner_instrumental": (
                getattr(req, "partner_instrumental", None) or req.partner_name
            ),
            **gender_forms(getattr(req, "gender", None)),
        },
    }
