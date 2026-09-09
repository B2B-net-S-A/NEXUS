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
