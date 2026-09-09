"""Canonical requirements, preserving alternatives and unknown evidence."""

from __future__ import annotations

import re

from app.schemas.matching_requirements import MatchingRequirements, SkillRequirement

_ALTERNATIVE = re.compile(r"\s+(?:lub|albo|or)\s+", re.IGNORECASE)


def alternatives(label: str) -> list[str]:
    return [part.strip() for part in _ALTERNATIVE.split(label) if part.strip()]


def requirement_label(group: SkillRequirement) -> str:
    return " lub ".join(group.any_of)


def requirement_labels(contract: MatchingRequirements) -> dict[str, list[str]]:
    return {
        level: [requirement_label(g) for g in contract.all_of if g.level == level]
        for level in ("must", "nice", "excluded", "uncertain")
    }


def explicit_contract(must, nice, *, reviewed=False) -> MatchingRequirements:
    from app.services.scoring_service import canonical_skill_names

    groups = []
    for level, names in (("must", must), ("nice", nice)):
        for label in canonical_skill_names(names):
            groups.append(
                SkillRequirement(
                    any_of=canonical_skill_names(alternatives(label)), level=level
                )
            )
    return MatchingRequirements(reviewed=reviewed, all_of=groups)


def stored_contract(job) -> MatchingRequirements | None:
    value = getattr(job, "matching_requirements", None)
    return MatchingRequirements.model_validate(value) if value is not None else None


def evaluate_requirements(contract: MatchingRequirements, candidate) -> list[dict]:
    from app.services.scoring_service import candidate_skill_names, skill_present

    skills = candidate_skill_names(candidate)
    results = []
    for group in contract.all_of:
        found = [name for name in group.any_of if skill_present(name, skills)]
        # Absence in imported/extracted skills is not proof of inability.
        results.append(
            {
                "any_of": group.any_of,
                "level": group.level,
                "status": "met" if found else "unknown",
                "matched": found,
                "source": group.source,
                "requirement_evidence": group.evidence,
                "candidate_updated_at": str(getattr(candidate, "updated_at", "")),
            }
        )
    return results
