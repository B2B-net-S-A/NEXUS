"""Frozen copy of ``build_champion_section`` from 2bc6b14f (legacy v7).

The live version adds an "additional criteria" block and a fixed disclaimer to
the prompt. The DTO (``ChampionProfileForPrompt``) is the live one: it only
gained optional fields, which this function ignores.
"""

from __future__ import annotations

from app.services.cv_generator_b2b.champion_builder import ChampionProfileForPrompt


def build_champion_section(profile: ChampionProfileForPrompt, language: str) -> str:
    """Render the champion section appended to the Claude prompt.

    Mirrors ``buildChampionSection()`` in ``lib/cv-shared.ts``.
    """
    header = "CHAMPION PROFILE" if language == "en" else "PROFIL CHAMPIONA"
    section = f"\n\n{header}:\n"

    if profile.must_have:
        section += f"\nMUST-HAVE: {', '.join(profile.must_have)}"
    if profile.nice_to_have:
        section += f"\nNICE-TO-HAVE: {', '.join(profile.nice_to_have)}"
    if profile.project_context:
        label = "Project Context" if language == "en" else "Kontekst projektu"
        section += f"\n\n{label}: {profile.project_context}"
    if profile.responsibilities:
        label = (
            "Position Responsibilities"
            if language == "en"
            else "Obowiązki na stanowisku"
        )
        section += f"\n\n{label}: {profile.responsibilities}"
    if profile.screening_questions:
        label = "Screening Questions" if language == "en" else "Pytania screeningowe"
        section += f"\n\n{label}: {profile.screening_questions}"
    if profile.historical_questions:
        label = (
            "Historical Interview Questions"
            if language == "en"
            else "Historyczne pytania z interview"
        )
        section += f"\n\n{label}: {profile.historical_questions}"
    if profile.consultant_insight:
        label = "Consultant Insight" if language == "en" else "Insight konsultanta"
        section += f"\n\n{label}: {profile.consultant_insight}"

    return section
