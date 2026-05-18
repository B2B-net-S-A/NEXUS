"""Build the Champion Profile prompt section from NEXUS DB shape.

NEXUS stores the champion as a structured JSONB (``Job.champion_profile``)
plus ``Job.must_skills`` / ``Job.nice_skills`` columns. The external
CV-Generator expected a flat ``ChampionProfile`` shape; this module maps
between the two and renders the same prompt section format produced by
``buildChampionSection()`` in ``lib/cv-shared.ts``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ChampionProfileForPrompt:
    """Flat shape used by :func:`build_champion_section`."""

    must_have: list[str] = field(default_factory=list)
    nice_to_have: list[str] = field(default_factory=list)
    project_context: str = ""
    responsibilities: str = ""
    screening_questions: str = ""
    historical_questions: str = ""
    consultant_insight: str = ""

    def is_empty(self) -> bool:
        return not any(
            [
                self.must_have,
                self.nice_to_have,
                self.project_context.strip(),
                self.responsibilities.strip(),
                self.screening_questions.strip(),
                self.historical_questions.strip(),
                self.consultant_insight.strip(),
            ]
        )


def _skill_name(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("name") or "").strip()
    return str(item).strip()


def from_nexus_job(
    must_skills: list[dict] | None,
    nice_skills: list[dict] | None,
    champion_profile: dict | None,
    requirements: str | None = None,
) -> ChampionProfileForPrompt:
    """Map NEXUS Job columns to the flat ChampionProfile shape.

    Args:
        must_skills: Value of ``Job.must_skills``.
        nice_skills: Value of ``Job.nice_skills``.
        champion_profile: Value of ``Job.champion_profile`` (JSONB dict).
        requirements: Optional fallback for ``responsibilities`` when the
            champion profile lacks ``project_context.responsibilities``.
    """
    must = [s for s in (_skill_name(x) for x in (must_skills or [])) if s]
    nice = [s for s in (_skill_name(x) for x in (nice_skills or [])) if s]

    cp = champion_profile or {}
    proj = cp.get("project_context") or {}

    about = str(proj.get("about") or "").strip()
    selling = str(proj.get("selling_points") or "").strip()
    project_context_parts = [p for p in (about, selling) if p]
    project_context = "\n\n".join(project_context_parts)

    responsibilities = str(proj.get("responsibilities") or "").strip()
    if not responsibilities and requirements:
        responsibilities = requirements.strip()

    questions = cp.get("screening_questions") or []
    if isinstance(questions, list) and questions:
        lines: list[str] = []
        for q in questions:
            if not isinstance(q, dict):
                continue
            text = str(q.get("question") or "").strip()
            if not text:
                continue
            ideal = str(q.get("ideal_answer") or "").strip()
            dealbreaker = str(q.get("deal_breaker") or "").strip()
            line = f"- {text}"
            if ideal:
                line += f"\n  Idealna odpowiedź: {ideal}"
            if dealbreaker:
                line += f"\n  Deal-breaker: {dealbreaker}"
            lines.append(line)
        screening_str = "\n".join(lines)
    else:
        screening_str = ""

    historical = str(cp.get("historical_client_questions") or "").strip()
    insight = str(cp.get("internal_consultant_insight") or "").strip()

    return ChampionProfileForPrompt(
        must_have=must,
        nice_to_have=nice,
        project_context=project_context,
        responsibilities=responsibilities,
        screening_questions=screening_str,
        historical_questions=historical,
        consultant_insight=insight,
    )


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


def build_screening_notes_section(notes: str, language: str) -> str:
    """Render the SCREENING NOTES section appended to the Claude prompt."""
    if not notes.strip():
        return ""
    header = "SCREENING NOTES" if language == "en" else "NOTATKI ZE SCREENINGU"
    return f"\n\n{header}:\n{notes.strip()}"
