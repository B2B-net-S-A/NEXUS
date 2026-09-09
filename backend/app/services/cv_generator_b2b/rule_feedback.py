"""Check observable presentation outcomes; never certify free-text instructions."""

from app.services.cv_generator_b2b.client_rules import SECTION_LABELS


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
        check("max_roles", "Limit stanowisk", len(roles) <= rule.max_roles)
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
    if rule.generator_instructions or rule.generator_instructions_en or rule.notes:
        feedback.append(
            {
                "field": "instructions",
                "label": "Instrukcje opisowe — wymagają oceny obu dokumentów",
                "status": "needs_review",
            }
        )
    return feedback
