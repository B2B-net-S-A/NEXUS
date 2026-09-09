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


def requirements_for_job(job) -> MatchingRequirements:
    """The editor and worker consume precisely the same effective criteria."""
    from app.services.scoring_service import job_skill_requirements

    stored = stored_contract(job)
    if stored is not None:
        return stored
    labels = job_skill_requirements(job)
    groups = [
        SkillRequirement(any_of=alternatives(label), level=level, source="request")
        for level in ("must", "nice", "excluded", "uncertain")
        for label in labels.get(level, [])
    ]
    return MatchingRequirements(
        reviewed=bool(getattr(job, "requirements_reviewed", False)),
        all_of=groups,
    )


def search_dealbreaker_inputs(job, *, exclude_missing_must: bool | None = None):
    """Shared default policy; an explicit request filter may override it.

    Clearing the gate changes no scoring requirement or evidence. Missing
    proof stays reviewable unless exclusion was selected explicitly.
    """
    from dataclasses import replace
    from app.services.dealbreaker_filters import dealbreaker_inputs_for_job

    from app.services.requirement_verification import criteria_fingerprint

    contract = requirements_for_job(job)
    inputs = replace(
        dealbreaker_inputs_for_job(job),
        verification_job_id=getattr(job, "id", None),
        verification_fingerprint=criteria_fingerprint(contract),
    )
    exclude = (
        requirements_for_job(job).missing_evidence_policy == "exclude"
        if exclude_missing_must is None
        else exclude_missing_must
    )
    return (
        replace(inputs, exclude_unknown_skill_evidence=True)
        if exclude
        else replace(inputs, must_skills=())
    )


def invalidate_changed_requirements(job, updates: dict) -> None:
    """An edited source must not remain masked by previously reviewed criteria."""
    if "matching_requirements" in updates:
        contract = updates["matching_requirements"]
        updates["requirements_reviewed"] = bool(contract and contract.get("reviewed"))
        return
    sources = {
        "title",
        "description",
        "requirements",
        "must_skills",
        "nice_skills",
        "champion_profile",
    }

    def source_value(field, value):
        if field == "champion_profile" and isinstance(value, dict):
            # Approval/search workflow state does not change role requirements.
            return {
                k: v
                for k, v in value.items()
                if k not in {"verification", "recommended_searches"}
            }
        return value

    if any(
        source_value(field, getattr(job, field, None))
        != source_value(field, updates[field])
        for field in sources & updates.keys()
    ):
        updates["matching_requirements"] = None
        updates["requirements_reviewed"] = False


def evaluate_requirements(
    contract: MatchingRequirements, candidate, *, job_id=None
) -> list[dict]:
    from app.services.scoring_service import candidate_skill_names, skill_present

    from app.services.requirement_verification import reviewed_group

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
                # Imported/extracted profile signals do not establish current
                # proficiency, a verification date or project usage context.
                "evidence_basis": "profile_signal" if found else "no_evidence",
                "verified_at": None,
                "usage_context": None,
                "source": group.source,
                "requirement_evidence": group.evidence,
                "candidate_updated_at": str(getattr(candidate, "updated_at", "")),
            }
        )
        review = reviewed_group(candidate, contract, group, job_id=job_id)
        if review:
            results[-1].update(
                **review,
                evidence_basis="reviewed",
                matched=found if review["status"] == "met" else [],
            )
    return results


def apply_requirement_source_update(job, field: str, value) -> None:
    updates = {field: value}
    invalidate_changed_requirements(job, updates)
    for key, item in updates.items():
        setattr(job, key, item)
