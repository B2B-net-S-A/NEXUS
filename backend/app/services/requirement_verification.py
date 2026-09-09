"""Provenance checks for explicit reviewed evidence, never inferred AI verdicts."""

import hashlib
import json

from sqlalchemy import select

from app.models.requirement_verification import RequirementVerification


def _hash(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()


def criteria_fingerprint(contract):
    return _hash(contract.model_dump())


def group_key(group):
    return _hash({"level": group.level, "any_of": sorted(group.any_of)})


def source_fingerprint(candidate):
    return _hash(
        {
            key: getattr(candidate, key, None)
            for key in (
                "raw_cv_text",
                "skills",
                "cv_extracted_data",
                "skills_manually_curated",
                "tags",
                "verified_tech",
            )
        }
    )


def verification_is_current(row, contract, candidate):
    return (
        row.requirements_fingerprint == criteria_fingerprint(contract)
        and row.source_fingerprint == source_fingerprint(candidate)
        and row.group_key in {group_key(group) for group in contract.all_of}
    )


async def latest_verifications(db, job_id, candidate_ids):
    if not candidate_ids:
        return []
    result = await db.execute(
        select(RequirementVerification)
        .where(
            RequirementVerification.job_id == job_id,
            RequirementVerification.candidate_id.in_(candidate_ids),
        )
        .distinct(
            RequirementVerification.candidate_id, RequirementVerification.group_key
        )
        .order_by(
            RequirementVerification.candidate_id,
            RequirementVerification.group_key,
            RequirementVerification.id.desc(),
        )
    )
    return list(result.scalars().all())


async def load_verified_requirements(db, job, candidates):
    """Attach only database-backed, current evidence for this exact request."""
    from app.services.requirement_contract import requirements_for_job

    contract = requirements_for_job(job)
    fingerprint = criteria_fingerprint(contract)
    job_id = getattr(job, "id", None)
    for candidate in candidates:
        candidate._reviewed_requirements = {
            "job_id": job_id,
            "fingerprint": fingerprint,
            "groups": {},
        }
    if db is None or not isinstance(job_id, int) or job_id <= 0 or not candidates:
        return
    by_id = {candidate.id: candidate for candidate in candidates}
    for row in await latest_verifications(db, job_id, list(by_id)):
        candidate = by_id.get(row.candidate_id)
        if candidate is None or not verification_is_current(row, contract, candidate):
            continue
        candidate._reviewed_requirements["groups"][row.group_key] = {
            "status": row.status,
            "verification_id": row.id,
            "verified_at": row.verified_at.isoformat(),
            "candidate_evidence": row.evidence,
            "usage_context": row.usage_context,
        }


def reviewed_group(candidate, contract, group, *, job_id):
    state = getattr(candidate, "_reviewed_requirements", None)
    if not isinstance(state, dict) or job_id is None:
        return None
    if state.get("job_id") != job_id or state.get(
        "fingerprint"
    ) != criteria_fingerprint(contract):
        return None
    return state.get("groups", {}).get(group_key(group))


def reviewed_label_status(candidate, job, label, level):
    if not getattr(candidate, "_reviewed_requirements", {}).get("groups"):
        return None
    from app.schemas.matching_requirements import SkillRequirement
    from app.services.requirement_contract import alternatives, requirements_for_job

    group = SkillRequirement(any_of=alternatives(label), level=level)
    review = reviewed_group(
        candidate, requirements_for_job(job), group, job_id=getattr(job, "id", None)
    )
    return review["status"] if review else None


def reviewed_gate_status(candidate, label, *, job_id, fingerprint):
    from app.schemas.matching_requirements import SkillRequirement
    from app.services.requirement_contract import alternatives

    state = getattr(candidate, "_reviewed_requirements", {})
    if (
        not job_id
        or not fingerprint
        or state.get("job_id") != job_id
        or state.get("fingerprint") != fingerprint
    ):
        return None
    key = group_key(SkillRequirement(any_of=alternatives(label), level="must"))
    review = state.get("groups", {}).get(key)
    return review["status"] if review else None
