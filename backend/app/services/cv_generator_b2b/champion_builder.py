"""Build the Champion Profile prompt section from NEXUS DB shape.

NEXUS stores the champion as a structured JSONB (``Job.champion_profile``)
plus ``Job.must_skills`` / ``Job.nice_skills`` columns. The external
CV-Generator expected a flat ``ChampionProfile`` shape; this module maps
between the two and renders the same prompt section format produced by
``buildChampionSection()`` in ``lib/cv-shared.ts``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.services.cv_generator_b2b.text_extractor import extract_text_from_file
from app.services.skill_normalize import iter_skill_names


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
    # iter_skill_names handles every legacy JSONB shape the column may hold —
    # list[dict], list[str], dict {"technologies": [...]}, a JSON-encoded
    # string, or a comma list — so a dict/string column no longer collapses to
    # the literal key "technologies" or gets iterated character-by-character.
    must = iter_skill_names(must_skills)
    nice = iter_skill_names(nice_skills)

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


# ── Regex parser for uploaded Champion DOCX (Old mode) ─────────────────────


_MUST_HAVE_RE = re.compile(
    r"MUST-HAVE:([\s\S]*?)(?=NICE-TO-HAVE:|3\.\s*KONTEKST|$)",
    re.IGNORECASE,
)
_NICE_TO_HAVE_RE = re.compile(
    r"NICE-TO-HAVE:([\s\S]*?)(?=3\.\s*KONTEKST|$)",
    re.IGNORECASE,
)
_PROJECT_RE = re.compile(
    r"O projekcie[^:]*:?\s*([\s\S]*?)(?=Obowi[aą]zki|$)",
    re.IGNORECASE,
)
_RESPONSIBILITIES_RE = re.compile(
    r"Obowi[aą]zki na stanowisku[^:]*:?\s*([\s\S]*?)(?=Co przekona|4\.\s*SCREENING|$)",
    re.IGNORECASE,
)
_SCREENING_RE = re.compile(
    r"Pytani[ae] od Delivery Lead[\s\S]*?(?=Historyczne pytania|INSIGHT|5\.\s*SUCCESS|$)",
    re.IGNORECASE,
)
_HISTORICAL_RE = re.compile(
    r"Historyczne pytania[^:]*:?\s*([\s\S]*?)(?=INSIGHT|5\.\s*SUCCESS|$)",
    re.IGNORECASE,
)
_INSIGHT_RE = re.compile(
    r"INSIGHT OD KONSULTANTA[^:]*:?\s*([\s\S]*?)(?=5\.\s*SUCCESS|$)",
    re.IGNORECASE,
)

# Strip leading bullet glyphs / dashes / numbering when normalizing list items.
_BULLET_STRIP_RE = re.compile(r"^[\s\-•·*]+|[\s\-•·*]+$")
_ONLY_BULLET_RE = re.compile(r"^[\s\-•·*]+$")


def _split_skills(raw: str) -> list[str]:
    r"""Split MUST-HAVE / NICE-TO-HAVE blob into discrete tech names.

    Splits on newline, and on comma/semicolon only OUTSIDE parentheses, so a
    chip like ``Java (Spring, Hibernate)`` or ``WCAG 2.1/2.2 (AA, AAA)`` stays
    whole instead of shattering at the inner comma. Trims bullets/whitespace,
    drops empty and pure-bullet fragments.

    (Deliberately diverges from the JS 1:1 port ``text.split(/[\n,;]/)`` in
    ``lib/cv-shared.ts``, which broke parenthesised list items.)
    """
    if not raw:
        return []
    parts: list[str] = []
    buf: list[str] = []
    depth = 0
    for ch in raw:
        if ch in "([{":
            depth += 1
            buf.append(ch)
        elif ch in ")]}":
            depth = max(0, depth - 1)
            buf.append(ch)
        elif ch == "\n" or (ch in ",;" and depth == 0):
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    out: list[str] = []
    for p in parts:
        s = _BULLET_STRIP_RE.sub("", p).strip()
        if not s or _ONLY_BULLET_RE.match(s):
            continue
        out.append(s)
    return out


def parse_champion_from_docx_bytes(
    data: bytes, filename: str
) -> ChampionProfileForPrompt:
    """Parse a Word-format Champion Profile into the flat prompt shape.

    1:1 port of ``extractChampionSections()`` from ``lib/cv-shared.ts`` —
    reads raw text from the DOCX and runs the same regex layout that the
    external CV-Generator uses on user-uploaded DOCX templates.

    Used by the "Old" mode (manual upload) path only. The "New" mode uses
    :func:`from_nexus_job` which reads structured JSONB from ``Job`` directly.
    """
    text = extract_text_from_file(data, filename)

    must_match = _MUST_HAVE_RE.search(text)
    must_have = _split_skills(must_match.group(1).strip()) if must_match else []

    nice_match = _NICE_TO_HAVE_RE.search(text)
    nice_to_have = _split_skills(nice_match.group(1).strip()) if nice_match else []

    project_match = _PROJECT_RE.search(text)
    project_context = project_match.group(1).strip() if project_match else ""

    resp_match = _RESPONSIBILITIES_RE.search(text)
    responsibilities = resp_match.group(1).strip() if resp_match else ""

    screening_match = _SCREENING_RE.search(text)
    screening_questions = screening_match.group(0).strip() if screening_match else ""

    historical_match = _HISTORICAL_RE.search(text)
    historical_questions = historical_match.group(1).strip() if historical_match else ""

    insight_match = _INSIGHT_RE.search(text)
    consultant_insight = insight_match.group(1).strip() if insight_match else ""

    return ChampionProfileForPrompt(
        must_have=must_have,
        nice_to_have=nice_to_have,
        project_context=project_context,
        responsibilities=responsibilities,
        screening_questions=screening_questions,
        historical_questions=historical_questions,
        consultant_insight=consultant_insight,
    )
