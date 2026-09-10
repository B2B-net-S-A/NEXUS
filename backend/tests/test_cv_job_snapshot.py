"""Private queued input format preserves source bytes and rejects corruption."""

from datetime import date
import hashlib
import json

import pytest

from app.services.ai_quota import QuotaState
from app.services.cv_generator_b2b.job_snapshot import (
    deserialize_job_inputs,
    serialize_job_inputs,
)
from app.services.cv_generator_b2b.standalone_service import UploadGenerationInput


def test_upload_roundtrip_keeps_bytes_quota_and_literal_type_keys():
    inputs = {
        "payload": UploadGenerationInput(
            cv_bytes=b"\x00\xffDOCX",
            cv_filename="źródło.docx",
            champion_bytes=b"champion",
            screening_notes="Potwierdzone przez kandydata",
        ),
        "quota": QuotaState(used=2, limit=10, period_start=date(2026, 9, 1)),
        "user_data": {"type": "QuotaState", "value": {"used": 999}},
        "rules": (("Python", "Python"),),
    }
    raw, digest = serialize_job_inputs("upload", inputs)
    kind, restored = deserialize_job_inputs(raw, digest)
    assert kind == "upload"
    assert restored == inputs
    assert restored["payload"] is not inputs["payload"]


def _upload_snapshot(mutate) -> tuple[bytes, str]:
    """Serialize an upload job, then edit its UploadGenerationInput fields —
    the shape a job queued by an older (or newer) deploy would carry."""
    raw, _ = serialize_job_inputs(
        "upload",
        {
            "payload": UploadGenerationInput(
                cv_bytes=b"%PDF-1.4 source", cv_filename="cv.pdf", language="en"
            ),
            "user_id": 7,
        },
    )
    data = json.loads(raw)
    mutate(data["inputs"]["value"]["payload"]["value"])
    raw = json.dumps(
        data, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    ).encode()
    return raw, hashlib.sha256(raw).hexdigest()


def test_upload_queued_before_a_defaulted_field_was_added_still_decodes():
    # #1477 added `champion_profile` (default None); jobs queued earlier lack it.
    raw, digest = _upload_snapshot(lambda fields: fields.pop("champion_profile"))
    kind, restored = deserialize_job_inputs(raw, digest)
    assert kind == "upload"
    payload = restored["payload"]
    assert payload.champion_profile is None
    assert (payload.cv_bytes, payload.cv_filename, payload.language) == (
        b"%PDF-1.4 source",
        "cv.pdf",
        "en",
    )
    assert restored["user_id"] == 7


@pytest.mark.parametrize(
    "mutate",
    [
        # A field this code does not know: never guess what it meant.
        lambda fields: fields.update(unexpected={"type": "bytes", "value": ""}),
        # A required field is gone: the job cannot be run faithfully.
        lambda fields: fields.pop("cv_bytes"),
    ],
    ids=["unknown-field", "missing-required-field"],
)
def test_upload_snapshot_with_unknown_or_missing_required_field_is_rejected(mutate):
    raw, digest = _upload_snapshot(mutate)
    with pytest.raises(ValueError, match="fields changed"):
        deserialize_job_inputs(raw, digest)


def test_modified_source_is_rejected_before_decode():
    raw, digest = serialize_job_inputs("new", {"source": b"original"})
    with pytest.raises(ValueError, match="integrity"):
        deserialize_job_inputs(raw + b" ", digest)


@pytest.mark.parametrize(
    "raw",
    [
        b'{"version":1,"kind":[],"inputs":null}',
        b'{"version":true,"kind":"new","inputs":null}',
        b'{"version":1,"version":1,"kind":"new","inputs":null}',
        b'{"version":1,"kind":"new","inputs":NaN}',
        b'{"version":1,"kind":"new","inputs":{"type":"os.system","value":"echo x"}}',
        b'{"version":1,"kind":"new","inputs":{"type":"QuotaState","value":{}}}',
    ],
)
def test_malformed_or_unknown_snapshot_rejected(raw):
    with pytest.raises(ValueError):
        deserialize_job_inputs(raw, hashlib.sha256(raw).hexdigest())


@pytest.mark.parametrize(
    "inputs", [[], {"bad": object()}, {"nan": float("nan")}, {1: "key"}]
)
def test_unsupported_input_cannot_be_persisted(inputs):
    with pytest.raises(ValueError):
        serialize_job_inputs("new", inputs)


def test_deep_input_is_bounded():
    value = {}
    for _ in range(34):
        value = {"nested": value}
    with pytest.raises(ValueError, match="nesting"):
        serialize_job_inputs("new", value)
