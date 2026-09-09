"""Check observable presentation outcomes; never certify free-text instructions."""

from app.services.cv_generator_b2b.client_rules import SECTION_LABELS, reformat_dates
from app.services.cv_generator_b2b.language_aliases import resolve_alias


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
        # Unchanged text is not proof: the formatter deliberately preserves
        # unknown formats rather than guessing dates or their precision.
        feedback.append(
            {
                "field": "date_format",
                "label": f"Format dat: {rule.date_format} — sprawdź daty w dokumencie",
                "status": "not_applicable"
                if not dates
                else "conflict"
                if any(
                    reformat_dates(value, rule.date_format) != value for value in dates
                )
                else "needs_review",
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
