"""Private queued input format preserves source bytes and rejects corruption."""

from datetime import date
import hashlib

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
