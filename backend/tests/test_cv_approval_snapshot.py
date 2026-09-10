import hashlib
import json
from dataclasses import replace

import pytest
from app.services.cv_approval_review import PreparedApprovalReview
from app.services.cv_approval_snapshot import serialize_review, deserialize_review


def prepared():
    return PreparedApprovalReview(
        content_html="<p>Claim</p>",
        cv_text="Source",
        screening_notes="Notes",
        identity="Person",
        generated_id=11,
        source_sha256="a" * 64,
        request_id="cv-approval:1:2",
        presentation_json='{"status":"checked"}',
    )


def test_snapshot_roundtrip_and_source_bytes_tampering():
    original = prepared()
    raw, digest = serialize_review(original)
    assert deserialize_review(raw, digest) == original
    with pytest.raises(ValueError, match="integrity"):
        deserialize_review(raw + b" ", digest)


@pytest.mark.parametrize(
    "change", ["protocol", "unknown_field", "bad_id", "duplicate_key", "presentation"]
)
def test_invalid_snapshot_rejected_before_execution(change):
    raw, _ = serialize_review(prepared())
    data = json.loads(raw)
    if change == "protocol":
        data["protocol"]["version"] += 1
    elif change == "unknown_field":
        data["input"]["arbitrary"] = "instruction"
    elif change == "bad_id":
        data["input"]["generated_id"] = True
    elif change == "presentation":
        data["input"]["presentation_json"] = "[]"
    raw = json.dumps(data).encode()
    if change == "duplicate_key":
        raw = raw.replace(
            b'"generated_id": 11', b'"generated_id": 11, "generated_id": 12'
        )
    with pytest.raises(ValueError):
        deserialize_review(raw, hashlib.sha256(raw).hexdigest())


def test_invalid_prepared_input_cannot_be_persisted():
    with pytest.raises(ValueError):
        serialize_review(replace(prepared(), source_sha256="invalid"))
