"""Validate supported presentation limits against typed editor structure."""

import hashlib
import json
from lxml import html
from fastapi import HTTPException

SECTIONS = {
    "why_points",
    "experience",
    "education",
    "skills",
    "certifications",
    "languages",
}


def check_editor_rules(content_html, metadata):
    metadata = metadata or {}
    if metadata.get("client_rule_snapshot_status") != "verified":
        return {"status": "needs_review", "reason": "rule_snapshot_unavailable"}
    rule = metadata.get("client_rule_snapshot")
    digest = hashlib.sha256(
        json.dumps(
            rule, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    if digest != metadata.get("client_rule_snapshot_sha256"):
        raise HTTPException(409, "Nie można potwierdzić zapisanych reguł klienta.")
    if rule is None:
        return {"status": "not_applicable"}
    limits = {
        field: rule.get(field)
        for field in (
            "max_roles",
            "max_bullets_per_role",
            "max_bullet_chars",
            "why_points_max",
        )
    }
    active = any(limits.values()) or bool(rule.get("omit_sections"))
    checked = []
    if active:
        root = html.fragment_fromstring(content_html, create_parent="div")
        section, role = None, None
        sections, roles, summary = set(), [], []
        for node in root.iter():
            if node.tag == "h2":
                section = node.get("data-cv-section")
                if section not in SECTIONS:
                    raise HTTPException(
                        422,
                        "Przywróć nagłówki sekcji CV przed sprawdzeniem reguł klienta.",
                    )
                sections.add(section)
                role = None
            elif node.get("data-cv-section") == "role":
                if section != "experience":
                    raise HTTPException(
                        422, "Stanowisko musi znajdować się w sekcji doświadczenia."
                    )
                role = []
                roles.append(role)
            elif node.tag == "li":
                text = " ".join(node.text_content().split())
                if section == "why_points":
                    summary.append(text)
                elif section == "experience":
                    if role is None:
                        raise HTTPException(
                            422,
                            "Przywróć oznaczenie stanowiska przed punktami obowiązków.",
                        )
                    role.append(text)
        if not sections:
            raise HTTPException(
                422, "Brak oznaczonych sekcji do sprawdzenia reguł klienta."
            )
        checks = [
            (
                "omit_sections",
                not (sections & set(rule.get("omit_sections") or [])),
                "CV zawiera sekcję wyłączoną przez klienta.",
            ),
            (
                "max_roles",
                not limits["max_roles"] or len(roles) <= limits["max_roles"],
                "Przekroczono limit stanowisk klienta.",
            ),
            (
                "max_bullets_per_role",
                not limits["max_bullets_per_role"]
                or all(len(r) <= limits["max_bullets_per_role"] for r in roles),
                "Przekroczono limit punktów obowiązków klienta.",
            ),
            (
                "max_bullet_chars",
                not limits["max_bullet_chars"]
                or all(len(t) <= limits["max_bullet_chars"] for r in roles for t in r),
                "Punkt obowiązków przekracza limit znaków klienta.",
            ),
            (
                "why_points_max",
                not limits["why_points_max"]
                or len(summary) <= limits["why_points_max"],
                "Podsumowanie przekracza limit punktów klienta.",
            ),
        ]
        for field, passed, message in checks:
            if not passed:
                raise HTTPException(422, message)
            if rule.get(field):
                checked.append(field)
    manual = [
        field
        for field in (
            "generator_instructions",
            "generator_instructions_en",
            "notes",
            "date_format",
            "glossary",
            "highlight_policy",
            "highlight_terms",
        )
        if rule.get(field)
    ]
    return {
        "status": "needs_review" if manual else "checked",
        "checked_fields": checked,
        "manual_fields": manual,
    }


def editor_rule_feedback(content_html, metadata):
    """Drafts must remain loadable/editable even when they violate a rule."""
    try:
        return check_editor_rules(content_html or "", metadata)
    except HTTPException as exc:
        return {"status": "conflict", "message": exc.detail}
