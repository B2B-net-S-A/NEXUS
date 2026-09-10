"""Frozen copy of the client-rule prompt/policy logic from 2bc6b14f (legacy v7).

Only the pieces whose behaviour changed after the baseline are copied here:
the prompt's structured rule lines (full client glossary) and
``apply_presentation_policy`` (shortens overlong bullets with "…" and applies
the glossary to all free-text fields). Data structures (``CvRuleSnapshot``)
and unchanged helpers are imported from the live module. Date reformatting is
NOT copied: the live ``apply_date_format`` carries a real bug fix.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from app.services.cv_generator_b2b.client_rules import (  # noqa: F401
    CvRuleSnapshot,
    SECTION_LABELS,
    GENERATOR_INSTRUCTIONS_MAX_LENGTH,
    _PRESENTATION_RULES_TAG,
    _NOTES_TAG,
    _neutralize,
    build_client_notes_block,
)


def _structured_rule_lines(rule: CvRuleSnapshot, language: str) -> list[str]:
    """Klocki polityki prezentacji jako zdania dla modelu (PL albo EN).

    Te same reguły renderer egzekwuje po odpowiedzi — zdania w prompcie są po
    to, żeby model nie pisał treści, którą kod zaraz utnie (ucięty punkt czyta
    się gorzej niż punkt napisany krótko).
    """
    en = language == "en"
    labels = SECTION_LABELS["en" if en else "pl"]
    lines: list[str] = []
    if rule.omit_sections:
        names = ", ".join(labels[key] for key in rule.omit_sections)
        lines.append(
            f"Omit these sections entirely (return empty lists): {names}."
            if en
            else f"Pomiń całkowicie sekcje (zwróć puste listy): {names}."
        )
    if rule.max_roles:
        lines.append(
            f"Include at most the {rule.max_roles} most recent roles in experience."
            if en
            else f"W doświadczeniu uwzględnij maksymalnie {rule.max_roles} "
            "ostatnich stanowisk."
        )
    if rule.max_bullets_per_role:
        lines.append(
            f"At most {rule.max_bullets_per_role} responsibility bullets per role."
            if en
            else f"Maksymalnie {rule.max_bullets_per_role} punktów obowiązków "
            "na stanowisko."
        )
    if rule.max_bullet_chars:
        lines.append(
            f"Each responsibility bullet at most {rule.max_bullet_chars} characters."
            if en
            else f"Każdy punkt obowiązków do {rule.max_bullet_chars} znaków."
        )
    if rule.why_points_max:
        lines.append(
            f'"why_points": at most {rule.why_points_max} items.'
            if en
            else f"Sekcja „dlaczego ten kandydat” (why_points): maksymalnie "
            f"{rule.why_points_max} punktów."
        )
    # Format dat CELOWO nie idzie do promptu: bezpieczniki lat i nakładania
    # się dat parsują daty w kształcie źródłowym (`MM.YYYY`), a model
    # posłuszny prośbie o `MM/YYYY` gubiłby im miesiące. Format nakłada kod
    # na końcu pipeline'u (`apply_date_format`) — deterministycznie.
    if rule.glossary:
        pairs = "; ".join(f"„{src}” → „{dst}”" for src, dst in rule.glossary)
        lines.append(
            f"Client vocabulary (wording only, never facts): {pairs}."
            if en
            else f"Słownictwo klienta (tylko nazewnictwo, nigdy fakty): {pairs}."
        )
    return lines


def build_client_presentation_rules_block(
    rule: Optional[CvRuleSnapshot], language: str = "pl"
) -> str:
    """Blok ``<client_presentation_rules>`` do wiadomości użytkownika.

    Pusty string, gdy klient nie ma ani klocków, ani instrukcji — wtedy
    prompt nie różni się niczym od dotychczasowego. Idzie do wiadomości
    UŻYTKOWNIKA, nie do systemowej: prompt systemowy jest jednym cache'owanym
    blokiem i musi zostać identyczny między generacjami, a reguły różnią się
    per klient.

    Dla CV angielskiego wolny tekst bierze się z wariantu EN, gdy DL go wpisał;
    inaczej z treści podstawowej. Klocki są renderowane w języku dokumentu.
    """
    if rule is None:
        return ""
    lines = _structured_rule_lines(rule, language)
    free_text = ""
    if language == "en" and (rule.generator_instructions_en or "").strip():
        free_text = rule.generator_instructions_en or ""
    else:
        free_text = rule.generator_instructions or ""
    free_text = free_text.strip()[:GENERATOR_INSTRUCTIONS_MAX_LENGTH]
    parts = [*lines]
    if free_text:
        parts.append(free_text)
    if not parts:
        return ""
    body = _neutralize("\n".join(parts))
    return f"<{_PRESENTATION_RULES_TAG}>\n{body}\n</{_PRESENTATION_RULES_TAG}>"


def build_prompt_blocks(rule: Optional[CvRuleSnapshot], language: str = "pl") -> str:
    """Wszystko, co z reguły klienta trafia do wiadomości użytkownika."""
    parts = [
        block
        for block in (
            build_client_presentation_rules_block(rule, language),
            build_client_notes_block(rule),
        )
        if block
    ]
    return "\n\n".join(parts)


def _shorten(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[: max(limit - 1, 1)]
    space = cut.rfind(" ")
    if space > limit // 2:
        cut = cut[:space]
    return cut.rstrip(" ,;:") + "…"


def _glossary_pattern(src: str) -> re.Pattern[str]:
    # Całe słowa (bez `\b`, który przy polskich znakach nie działa
    # przewidywalnie), bez rozróżniania wielkości liter.
    return re.compile(rf"(?<!\w){re.escape(src)}(?!\w)", re.IGNORECASE)


def _apply_glossary_text(text: str, glossary: tuple[tuple[str, str], ...]) -> str:
    out = text
    for src, dst in glossary:
        # Lambda, nie szablon: `dst` z backslashem albo `\g<0>` wywaliłby
        # `re.error` w threadpoolu — „failed" na każdej generacji u klienta.
        out = _glossary_pattern(src).sub(lambda _m, _dst=dst: _dst, out)
    return out


def apply_presentation_policy(
    candidate_data: dict[str, Any], rule: Optional[CvRuleSnapshot]
) -> list[str]:
    """Domknij klocki reguły PO odpowiedzi modelu, PRZED bezpiecznikami.

    Model dostał te same reguły jako instrukcje, ale prośba nie jest
    gwarancją — „maks. 3 punkty" wypełnione czterema wygląda dla klienta jak
    zignorowane wymaganie. Zwraca listę tego, co trzeba było domknąć (puste,
    gdy model był posłuszny) — rekruter widzi to jako uwagę do sprawdzenia.
    Format dat jest nakładany OSOBNO (`apply_date_format`), na końcu
    pipeline'u, bo bezpieczniki lat i nakładania się dat parsują daty w kształcie
    źródłowym.
    """
    if rule is None:
        return []
    notes: list[str] = []
    for key in rule.omit_sections:
        if candidate_data.get(key):
            candidate_data[key] = []
            notes.append(f"pominięto sekcję „{SECTION_LABELS['pl'][key]}”")
    experience = candidate_data.get("experience") or []
    if rule.max_roles and len(experience) > rule.max_roles:
        candidate_data["experience"] = experience[: rule.max_roles]
        notes.append(f"ucięto doświadczenie do {rule.max_roles} stanowisk")
    if rule.max_bullets_per_role:
        trimmed = 0
        for role in candidate_data.get("experience") or []:
            bullets = role.get("responsibilities") or []
            if len(bullets) > rule.max_bullets_per_role:
                role["responsibilities"] = bullets[: rule.max_bullets_per_role]
                trimmed += 1
        if trimmed:
            notes.append(
                f"ucięto punkty obowiązków do {rule.max_bullets_per_role} "
                f"na stanowisko ({trimmed} stanowisk)"
            )
    if rule.max_bullet_chars:
        shortened = 0
        for role in candidate_data.get("experience") or []:
            bullets = role.get("responsibilities") or []
            new_bullets = []
            for bullet in bullets:
                short = _shorten(str(bullet), rule.max_bullet_chars)
                if short != bullet:
                    shortened += 1
                new_bullets.append(short)
            role["responsibilities"] = new_bullets
        if shortened:
            notes.append(
                f"skrócono {shortened} punktów obowiązków do {rule.max_bullet_chars} znaków"
            )
    why_points = candidate_data.get("why_points") or []
    if rule.why_points_max and len(why_points) > rule.why_points_max:
        candidate_data["why_points"] = why_points[: rule.why_points_max]
        notes.append(f"ucięto „dlaczego ten kandydat” do {rule.why_points_max} punktów")
    if rule.glossary:
        glossary = rule.glossary
        candidate_data["position"] = _apply_glossary_text(
            str(candidate_data.get("position") or ""), glossary
        )
        candidate_data["why_points"] = [
            _apply_glossary_text(str(p), glossary)
            for p in candidate_data.get("why_points") or []
        ]
        for role in candidate_data.get("experience") or []:
            role["position"] = _apply_glossary_text(
                str(role.get("position") or ""), glossary
            )
            role["responsibilities"] = [
                _apply_glossary_text(str(b), glossary)
                for b in role.get("responsibilities") or []
            ]
        for cat in candidate_data.get("skills") or []:
            if isinstance(cat, dict):
                cat["content"] = _apply_glossary_text(
                    str(cat.get("content") or ""), glossary
                )
        candidate_data["certifications"] = [
            _apply_glossary_text(str(c), glossary)
            for c in candidate_data.get("certifications") or []
        ]
    return notes
