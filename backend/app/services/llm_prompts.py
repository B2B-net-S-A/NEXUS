"""Versioned LLM prompt templates (Phase D2).

Centralizes every LLM-facing prompt so:
  - Revisions are trivially diffable in git
  - A/B testing can flip a single `version` field
  - The same template is reused across services (recommendations, screenings,
    CV parser, interview prep)

Design
------
Each template is a frozen dataclass with:
  - `name`              stable identifier (used in logs)
  - `version`           monotonically increasing int; bump when the prompt
                        changes semantically
  - `system_prompt`     optional preamble for chat-style models
  - `template`          f-string-shaped body with named `{placeholders}`
  - `expected_format`   short hint for the caller (JSON schema, plaintext…)

Call `PromptTemplate.render(**kwargs)` to produce the final string. Missing
placeholders raise a KeyError — caller bugs surface loudly instead of sending
corrupt prompts to the model.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class PromptTemplate:
    name: str
    version: int
    template: str
    system_prompt: Optional[str] = None
    expected_format: str = "plaintext"

    def render(self, **kwargs) -> str:  # noqa: ANN003
        """Return the final prompt string, substituting {placeholders}."""
        try:
            return self.template.format(**kwargs)
        except KeyError as e:
            raise KeyError(
                f"Prompt {self.name!r} v{self.version} missing placeholder: {e.args[0]!r}"
            ) from e


# ── Job criteria extraction (was inline in recommendations.py) ──────────────

JOB_CRITERIA_FROM_DESCRIPTION = PromptTemplate(
    name="job_criteria_from_description",
    version=1,
    expected_format="json",
    system_prompt=(
        "You are a technical recruiter for a Polish IT staffing agency. "
        "Extract structured requirements from job descriptions."
    ),
    template=(
        "Based on the job title and description below, output a JSON object with two lists:\n"
        '  "must_skills": hard requirements mentioned explicitly (up to 8)\n'
        '  "nice_skills": preferred but optional skills (up to 6)\n\n'
        'Each item is an object {{"name": "<skill>", "level": null}}. '
        "Respond with ONLY the raw JSON, no prose.\n\n"
        "Title: {title}\n"
        "Description: {description}\n"
        "Requirements: {requirements}\n"
    ),
)


# ── CV enrichment (Phase D3) ────────────────────────────────────────────────

CV_ENRICHMENT = PromptTemplate(
    name="cv_enrichment",
    version=1,
    expected_format="json",
    system_prompt=(
        "You are a recruitment assistant. Extract structured facts from CVs "
        "for a Polish IT staffing ATS. Use canonical technology names "
        "(e.g. 'React' not 'ReactJS', 'Kubernetes' not 'K8s'). Never invent "
        "information that is not in the CV."
    ),
    template=(
        "From the CV below, produce a JSON object with these fields:\n"
        '  "years_it_experience": integer, best estimate of total IT experience\n'
        '  "current_position": short string (e.g. "Senior Python Developer") or null\n'
        '  "skills": list of {{"name": "<canonical>", "level": "expert|senior|mid|junior", "years": int|null}}\n'
        '  "education": list of {{"degree": str, "field": str|null, "school": str, "year": int|null}}\n'
        '  "languages": list of {{"name": "<language>", "level": "A1|A2|B1|B2|C1|C2|native"}}\n\n'
        "Respond with ONLY the raw JSON, no prose.\n\n"
        "CV:\n{cv_text}\n"
    ),
)


# ── Interview prep kit (already in prep_kit.py; here for version tracking) ──

INTERVIEW_PREP = PromptTemplate(
    name="interview_prep",
    version=1,
    expected_format="json",
    system_prompt=(
        "You are a senior technical recruiter preparing a client interview. "
        "Produce concise, actionable talking points in Polish."
    ),
    template=(
        "Candidate facts:\n{candidate_summary}\n\n"
        "Job facts:\n{job_summary}\n\n"
        "Produce a JSON object with:\n"
        '  "strengths": list of <= 5 strings — what to highlight\n'
        '  "risks": list of <= 5 strings — gaps or concerns\n'
        '  "questions": list of <= 8 strings — recruiter questions to ask\n\n'
        "Respond with ONLY the raw JSON, no prose."
    ),
)


# ── Registry (for logging + future A/B) ─────────────────────────────────────

ALL_TEMPLATES: dict[str, PromptTemplate] = {
    t.name: t
    for t in (
        JOB_CRITERIA_FROM_DESCRIPTION,
        CV_ENRICHMENT,
        INTERVIEW_PREP,
    )
}
