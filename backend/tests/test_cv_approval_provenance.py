import hashlib
import json

from app.services.cv_generator_b2b.factual_verification import factual_projection
from app.services.cv_approval_provenance import (
    capture_editor_origin,
    approval_provenance,
)


def test_edited_claim_does_not_inherit_generation_verdict():
    original = "<p>3 lata doświadczenia</p>"
    payload = {"why_points": ["3 lata doświadczenia"]}
    payload["factual_verification"] = {
        "version": 2,
        "status": "verified",
        "document_sha256": hashlib.sha256(
            json.dumps(
                factual_projection(payload), sort_keys=True, ensure_ascii=False
            ).encode()
        ).hexdigest(),
    }
    metadata = capture_editor_origin(original, payload)
    assert approval_provenance(original, metadata)["generation_review_covers_content"]
    edited = approval_provenance("<p>8 lat doświadczenia</p>", metadata)
    assert not edited["generation_review_covers_content"]
    assert edited["requires_content_review"]


def test_legacy_or_unreviewed_source_requires_review_even_when_unchanged():
    html = "<p>Python</p>"
    for metadata in (
        None,
        {},
        capture_editor_origin(html, None),
        capture_editor_origin(html, {"status": "failed"}),
    ):
        assert approval_provenance(html, metadata)["requires_content_review"]


def test_stale_verified_payload_is_not_accepted_after_fact_change():
    payload = {"why_points": ["3 lata doświadczenia"]}
    payload["factual_verification"] = {
        "status": "verified",
        "document_sha256": hashlib.sha256(
            json.dumps(
                factual_projection(payload), sort_keys=True, ensure_ascii=False
            ).encode()
        ).hexdigest(),
    }
    payload["why_points"] = ["8 lat doświadczenia"]
    metadata = capture_editor_origin("<p>8 lat doświadczenia</p>", payload)
    assert not metadata["generation_review_available"]
