"""Consent cannot move to another operator, candidate, client or uploaded CV."""

import hashlib
from types import SimpleNamespace
from typing import get_args
from unittest.mock import AsyncMock

from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from jose import jwt
import pytest

from app.api import cv_generator_b2b as api
from app.services.cv_generator_b2b import consent_binding as binding


CONTEXT = binding.subject(candidate_id=1, stage_id=2, client_id=3)


@pytest.mark.parametrize(
    "change", [dict(candidate_id=9), dict(stage_id=9), dict(client_id=9)]
)
def test_receipt_cannot_move_between_subjects_and_recruitments(change):
    token = binding.issue("cv/synthetic-consent.png", 7, CONTEXT)
    with pytest.raises(ValueError):
        binding.verify(token, 7, {**CONTEXT, **change})


def test_receipt_cannot_move_to_another_operator_or_cv_file():
    source = binding.subject(
        cv_sha256=hashlib.sha256(b"person A").hexdigest(), client_id=3
    )
    token = binding.issue("cv/synthetic-consent.png", 7, source)
    with pytest.raises(ValueError):
        binding.verify(token, 8, source)
    with pytest.raises(ValueError):
        binding.verify(
            token,
            7,
            binding.subject(
                cv_sha256=hashlib.sha256(b"person B").hexdigest(), client_id=3
            ),
        )
    assert binding.verify(token, 7, source)["binding"]["subject"] == source


@pytest.mark.parametrize(
    "kind", ["expired", "tampered", "access_token", "bare_storage_key"]
)
def test_expired_forged_or_other_purpose_receipts_are_rejected(kind):
    token = binding.issue("cv/synthetic-consent.png", 7, CONTEXT)
    if kind == "expired":
        payload = jwt.get_unverified_claims(token)
        payload["exp"] = 1
        token = jwt.encode(payload, binding._key(), algorithm="HS256")
    elif kind == "tampered":
        payload = jwt.get_unverified_claims(token)
        payload["owner"] = 8
        token = jwt.encode(payload, "wrong-key", algorithm="HS256")
    elif kind == "access_token":
        from app.core.security import create_access_token

        token = create_access_token(7, "recruiter")
    else:
        token = "cv/synthetic-consent.png"
    with pytest.raises(ValueError):
        binding.verify(token, 7, CONTEXT)


def test_stored_metadata_contains_binding_without_reusable_token():
    token = binding.issue("cv/synthetic-consent.png", 7, CONTEXT)
    receipt = api._verified_consent(None, token, "", 7, CONTEXT)
    assert receipt["storage_key"] == "cv/synthetic-consent.png"
    assert receipt["binding"]["uploaded_by"] == 7
    assert receipt["binding"]["subject"] == CONTEXT
    assert token not in str(receipt)


def test_open_legacy_form_receives_refresh_instruction_instead_of_reusing_its_key():
    with pytest.raises(HTTPException) as error:
        api._verified_consent(
            SimpleNamespace(requires_rodo_consent_block=True),
            "",
            "cv/old.png",
            7,
            CONTEXT,
        )
    assert error.value.status_code == 422
    assert "Odśwież formularz" in error.value.detail


@pytest.mark.parametrize("mode", ["new", "upload"])
async def test_generation_rejects_foreign_attachment_before_quota_and_background_job(
    monkeypatch, mode
):
    app = FastAPI()
    app.include_router(api.router)
    app.state.limiter = api.limiter
    db = AsyncMock()
    db.get.return_value = SimpleNamespace(
        id=1, candidate_id=1, job_id=8, cv_content_mode_cap=None
    )
    db.execute.return_value = SimpleNamespace(scalar_one_or_none=lambda: 3)
    app.dependency_overrides[api.get_db] = lambda: db
    app.dependency_overrides[get_args(api.CandidateWriteAccess)[1].dependency] = (
        lambda: SimpleNamespace(id=7)
    )
    monkeypatch.setattr(api, "resolve_client_rule", AsyncMock(return_value=None))
    charge = AsyncMock(
        side_effect=AssertionError("Consent mismatch cannot charge quota")
    )
    pending = AsyncMock(
        side_effect=AssertionError("Consent mismatch cannot create a job")
    )
    monkeypatch.setattr(api, "_charge_cv_generation_quota", charge)
    monkeypatch.setattr(api, "_create_pending_row", pending)
    token = binding.issue("cv/person-a.png", 99, CONTEXT)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        if mode == "new":
            response = await client.post(
                "/cv-generator/generate",
                json={
                    "candidate_id": 1,
                    "stage_id": 2,
                    "consent_screenshot_token": token,
                },
            )
        else:
            response = await client.post(
                "/cv-generator/generate-upload",
                files={"cv_file": ("person-b.pdf", b"person B", "application/pdf")},
                data={"consent_screenshot_token": token},
            )
    assert response.status_code == 422, response.text
    assert "Zrzut zgody" in response.json()["detail"]
    charge.assert_not_called()
    pending.assert_not_called()


async def test_upload_issues_receipt_for_declared_cv_bytes_and_real_operator(
    monkeypatch,
):
    app = FastAPI()
    app.include_router(api.router)
    app.state.limiter = api.limiter
    app.dependency_overrides[api.get_db] = lambda: AsyncMock()
    app.dependency_overrides[get_args(api.CandidateWriteAccess)[1].dependency] = (
        lambda: SimpleNamespace(id=7)
    )
    monkeypatch.setattr(api.object_storage, "is_available", lambda: True)
    monkeypatch.setattr(
        api.object_storage, "upload_cv", lambda *args: "cv/synthetic-consent.png"
    )
    fingerprint = hashlib.sha256(b"synthetic CV bytes").hexdigest()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/cv-generator/consent-screenshot",
            files={"file": ("consent.png", b"\x89PNG\r\n\x1a\nsynthetic", "image/png")},
            data={"cv_sha256": fingerprint},
        )
    assert response.status_code == 200, response.text
    receipt = binding.verify(
        response.json()["consent_token"], 7, binding.subject(cv_sha256=fingerprint)
    )
    assert receipt["storage_key"] == response.json()["storage_key"]
    assert receipt["binding"]["uploaded_by"] == 7
