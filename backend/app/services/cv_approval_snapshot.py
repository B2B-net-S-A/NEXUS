"""Versioned, integrity-checked transport for captured approval review inputs."""

from dataclasses import asdict
import hashlib
import json

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from app.services.cv_approval_review import PreparedApprovalReview
from app.services.cv_editor_review import EDITOR_REVIEW_VERSION
from app.services.cv_generator_b2b.factual_verification import (
    VERIFIER_VERSION,
    VERIFICATION_PROMPT,
    REVIEW_RESPONSE_SCHEMA_SHA256,
)

MAX_SNAPSHOT_BYTES = 16_000_000


class ReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    content_html: str = Field(min_length=1, max_length=2_000_000)
    cv_text: str = Field(min_length=1, max_length=4_000_000)
    screening_notes: str = Field(max_length=1_000_000)
    identity: str = Field(max_length=10_000)
    generated_id: int = Field(gt=0)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    request_id: str = Field(min_length=1, max_length=200)
    presentation_json: str = Field(max_length=1_000_000)


def protocol():
    return {
        "version": 1,
        "editor_review_version": EDITOR_REVIEW_VERSION,
        "verifier_version": VERIFIER_VERSION,
        "prompt_sha256": hashlib.sha256(VERIFICATION_PROMPT.encode()).hexdigest(),
        "response_schema_sha256": REVIEW_RESPONSE_SCHEMA_SHA256,
    }


def serialize_review(prepared: PreparedApprovalReview) -> tuple[bytes, str]:
    data = ReviewInput.model_validate(asdict(prepared)).model_dump()
    raw = json.dumps(
        {"protocol": protocol(), "input": data},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    if len(raw) > MAX_SNAPSHOT_BYTES:
        raise ValueError("Approval snapshot exceeds size limit")
    return raw, hashlib.sha256(raw).hexdigest()


def deserialize_review(raw: bytes, digest: str) -> PreparedApprovalReview:
    if len(raw) > MAX_SNAPSHOT_BYTES or hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError("Invalid approval snapshot integrity")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate approval snapshot key")
            result[key] = value
        return result

    try:
        envelope = json.loads(raw, object_pairs_hook=unique)
        if (
            not isinstance(envelope, dict)
            or set(envelope) != {"protocol", "input"}
            or envelope["protocol"] != protocol()
        ):
            raise ValueError("Approval snapshot protocol changed")
        values = ReviewInput.model_validate(envelope["input"]).model_dump()
        if not isinstance(json.loads(values["presentation_json"]), dict):
            raise ValueError("Invalid presentation evidence")
        return PreparedApprovalReview(**values)
    except (ValidationError, UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("Invalid approval snapshot") from exc
