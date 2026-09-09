from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api import requirement_verifications as api
from app.schemas.matching_requirements import MatchingRequirements, SkillRequirement
from app.schemas.requirement_verification import VerifyRequirementRequest
from app.services.requirement_verification import (
    criteria_fingerprint,
    group_key,
    source_fingerprint,
    verification_is_current,
)


def fixture():
    now = datetime.now(timezone.utc)
    contract = MatchingRequirements(
        reviewed=True, all_of=[SkillRequirement(any_of=["Python"])]
    )
    job = SimpleNamespace(
        id=7, client_id=8, matching_requirements=contract.model_dump()
    )
    candidate = SimpleNamespace(
        id=1,
        updated_at=now,
        raw_cv_text="X" * 9000 + "Python",
        skills=["Python"],
        cv_extracted_data={},
    )
    body = VerifyRequirementRequest(
        requirement_index=0,
        requirements_fingerprint=criteria_fingerprint(contract),
        candidate_version=str(now),
        status="not_met",
        evidence="Test praktyczny: brak rozwiązania zadania",
        usage_context="Wymagany samodzielny backend Python",
        verified_at=now - timedelta(minutes=1),
    )
    return contract, job, candidate, body


def test_provenance_requires_current_request_and_full_candidate_source():
    contract, job, candidate, body = fixture()
    row = SimpleNamespace(
        group_key=group_key(contract.all_of[0]),
        requirements_fingerprint=criteria_fingerprint(contract),
        source_fingerprint=source_fingerprint(candidate),
    )
    assert verification_is_current(row, contract, candidate)
    candidate.updated_at += timedelta(seconds=1)
    assert verification_is_current(row, contract, candidate), (
        "review-only version bump does not revoke other reviewed groups"
    )
    candidate.raw_cv_text += " Django"
    assert not verification_is_current(row, contract, candidate)
    candidate.raw_cv_text = "X" * 9000 + "Python"
    contract.all_of[0].any_of = ["Java"]
    assert not verification_is_current(row, contract, candidate)


@pytest.mark.parametrize(
    "changes",
    [
        {"verified_at": datetime.now(timezone.utc) + timedelta(days=1)},
        {"verified_at": datetime.now()},
        {"evidence": "   "},
        {"usage_context": ""},
        {"reviewer_id": 99},
    ],
)
def test_invalid_or_forged_review_request_rejected(changes):
    data = fixture()[-1].model_dump()
    with pytest.raises(ValidationError):
        VerifyRequirementRequest(**{**data, **changes})


@pytest.mark.asyncio
@pytest.mark.parametrize("stale", [False, True])
async def test_write_binds_author_and_rejects_concurrent_profile_edit(
    monkeypatch, stale
):
    contract, job, candidate, body = fixture()
    db = AsyncMock()
    db.scalar.side_effect = [job, candidate]
    saved = []

    def add(row):
        row.id = 123
        saved.append(row)

    db.add = add
    monkeypatch.setattr(api, "_authorized_job", AsyncMock(return_value=job))
    membership = AsyncMock()
    monkeypatch.setattr(api, "ensure_job_membership", membership)
    if stale:
        candidate.updated_at += timedelta(seconds=1)
        with pytest.raises(HTTPException) as error:
            await api.verify_requirement(7, 1, body, user=SimpleNamespace(id=42), db=db)
        assert error.value.status_code == 409
        assert not saved
        db.commit.assert_not_awaited()
    else:
        prior = candidate.updated_at
        result = await api.verify_requirement(
            7, 1, body, user=SimpleNamespace(id=42), db=db
        )
        assert result["id"] == 123
        assert saved[0].reviewer_id == 42 and saved[0].status == "not_met"
        assert verification_is_current(saved[0], contract, candidate)
        assert candidate.updated_at > prior
        db.commit.assert_awaited_once()
    membership.assert_awaited_once()


@pytest.mark.asyncio
async def test_job_scope_failure_prevents_review_write(monkeypatch):
    _, job, _, body = fixture()
    db = AsyncMock()
    monkeypatch.setattr(api, "_authorized_job", AsyncMock(return_value=job))
    monkeypatch.setattr(
        api,
        "ensure_job_membership",
        AsyncMock(side_effect=HTTPException(403, "No scope")),
    )
    with pytest.raises(HTTPException) as error:
        await api.verify_requirement(7, 1, body, user=SimpleNamespace(id=42), db=db)
    assert error.value.status_code == 403
    db.scalar.assert_not_awaited()
    db.commit.assert_not_awaited()
