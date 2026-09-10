"""Check observable presentation outcomes; never certify free-text instructions."""

import re

from app.services.cv_generator_b2b.client_rules import SECTION_LABELS, reformat_dates
from app.services.cv_generator_b2b.language_aliases import resolve_alias
from app.services.cv_generator_b2b.docx_renderer import (
    compile_keyword_patterns,
    highlight_spans,
)


def _date_format_status(value: str, fmt: str) -> str:
    year = r"[12]\d{3}"
    month = r"(?:0[1-9]|1[0-2])"
    token = {
        "YYYY": year,
        "YYYY-MM": rf"{year}-{month}",
        "MM.YYYY": rf"{month}\.{year}",
        "MM/YYYY": rf"{month}/{year}",
    }.get(fmt)
    if token and re.fullmatch(
        rf"{token}(?:\s*(?:–|—|-|do|to)\s*(?:{token}|obecnie|present|current))?",
        value,
        flags=re.IGNORECASE,
    ):
        return "satisfied"
    return "conflict" if reformat_dates(value, fmt) != value else "needs_review"


def presentation_feedback(payload: dict, rule) -> list[dict]:
    if rule is None:
        return []
    feedback = []

    def check(field, label, satisfied, applicable=True):
        feedback.append(
            {
                "field": field,
                "label": label,
                "status": "not_applicable"
                if not applicable
                else "satisfied"
                if satisfied
                else "conflict",
            }
        )

    roles = payload.get("experience") or []
    for section in rule.omit_sections:
        check(
            "omit_sections",
            f"Pominięcie sekcji: {SECTION_LABELS['pl'].get(section, section)}",
            not payload.get(section),
        )
    if rule.max_roles:
        check("max_roles", "Limit stanowisk", len(roles) <= rule.max_roles, bool(roles))
    if rule.max_bullets_per_role:
        check(
            "max_bullets_per_role",
            "Limit punktów na stanowisko",
            all(
                len(role.get("responsibilities") or []) <= rule.max_bullets_per_role
                for role in roles
            ),
            bool(roles),
        )
    if rule.max_bullet_chars:
        bullets = [
            str(bullet)
            for role in roles
            for bullet in role.get("responsibilities") or []
        ]
        check(
            "max_bullet_chars",
            "Długość punktów obowiązków",
            all(len(bullet) <= rule.max_bullet_chars for bullet in bullets),
            bool(bullets),
        )
    if rule.why_points_max:
        check(
            "why_points_max",
            "Limit punktów podsumowania",
            len(payload.get("why_points") or []) <= rule.why_points_max,
            bool(payload.get("why_points")),
        )
    highlighting = payload.get("highlight_policy_result")
    if isinstance(highlighting, dict):
        check(
            "highlight_policy",
            "Wybór fraz do pogrubienia",
            highlighting.get("policy") == rule.highlight_policy,
            not highlighting.get("requires_champion"),
        )
        for term in highlighting.get("ignored") or []:
            feedback.append(
                {
                    "field": "highlight_terms",
                    "label": f"Fraza „{term}” nie występuje w źródle — pominięta",
                    "status": "skipped",
                }
            )
        # Check only fields rendered with keyword emphasis. Headings, dates,
        # private source facts and the keyword list itself are not evidence.
        highlightable = [
            *(payload.get("why_points") or []),
            *(payload.get("certifications") or []),
            *(payload.get("languages") or []),
            *[group.get("content") or "" for group in payload.get("skills") or []],
            *[text for role in roles for text in role.get("responsibilities") or []],
            *[", ".join(role.get("technologies") or []) for role in roles],
        ]
        for term in highlighting.get("selected") or []:
            patterns = compile_keyword_patterns([term])
            present = any(
                highlight_spans(str(text), patterns) for text in highlightable
            )
            registered = term in (payload.get("highlight_keywords") or [])
            feedback.append(
                {
                    "field": "highlight_terms",
                    "label": f"Fraza „{term}” — "
                    + (
                        "brak w końcowej treści objętej pogrubieniem"
                        if not present
                        else "dopasowana w końcowej treści"
                        if registered
                        else "brak na liście pogrubień dokumentu"
                    ),
                    "status": "skipped"
                    if not present
                    else "satisfied"
                    if registered
                    else "conflict",
                }
            )
        if highlighting.get("requires_champion"):
            feedback.append(
                {
                    "field": "highlight_policy",
                    "label": "Brak wymagań Profilu Championa do wyboru pogrubień",
                    "status": "not_applicable",
                }
            )
    else:
        feedback.append(
            {
                "field": "highlight_policy",
                "label": "Brak zapisanego wyniku wyboru pogrubień",
                "status": "needs_review",
            }
        )
    if rule.date_format:
        dates = [
            str(entry.get("dates") or "").strip()
            for section in ("experience", "education")
            for entry in payload.get(section) or []
            if isinstance(entry, dict) and entry.get("dates")
        ]
        # Certify only the complete recognized shape. Unchanged unknown text
        # and year-only precision under a month policy still require review.
        statuses = [_date_format_status(value, rule.date_format) for value in dates]
        feedback.append(
            {
                "field": "date_format",
                "label": f"Format dat: {rule.date_format}",
                "status": "not_applicable"
                if not dates
                else "conflict"
                if "conflict" in statuses
                else "needs_review"
                if "needs_review" in statuses
                else "satisfied",
            }
        )
    titles = [
        str(payload.get("position") or ""),
        *[str(role.get("position") or "") for role in roles],
    ]
    for source, target in rule.glossary:
        alias = resolve_alias(source, target)
        if alias is None:
            status = "skipped"
            detail = "niedozwolona zamiana — pominięta"
        elif alias["target_language"] != (payload.get("language") or "pl"):
            status = "not_applicable"
            detail = "inny język docelowy — pominięta"
        elif any(
            title.strip().casefold() == source.strip().casefold() for title in titles
        ):
            status = "conflict"
            detail = "stanowisko nadal zawiera nazwę przed tłumaczeniem"
        else:
            status = "needs_review"
            detail = "sprawdź tłumaczenie stanowiska w dokumencie"
        feedback.append(
            {
                "field": "glossary",
                "label": f"Słownik: {source} → {target} — {detail}",
                "status": status,
            }
        )
    if rule.generator_instructions or rule.generator_instructions_en or rule.notes:
        feedback.append(
            {
                "field": "instructions",
                "label": "Instrukcje opisowe — wymagają oceny obu dokumentów",
                "status": "needs_review",
            }
        )
    return feedback
