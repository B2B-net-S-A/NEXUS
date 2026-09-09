"""Bind generation review provenance to exact editor content, not a document ID."""

import hashlib
import json

from app.services.cv_generator_b2b.factual_verification import factual_projection


def capture_editor_origin(html: str, generated_payload: dict | None) -> dict:
    generated_payload = generated_payload or {}
    generation_review = generated_payload.get("factual_verification")
    digest = hashlib.sha256(
        json.dumps(
            factual_projection(generated_payload), sort_keys=True, ensure_ascii=False
        ).encode()
    ).hexdigest()
    return {
        "generated_editor_html_sha256": hashlib.sha256(html.encode()).hexdigest(),
        "generation_review_available": isinstance(generation_review, dict)
        and generation_review.get("status") == "verified"
        and generation_review.get("document_sha256") == digest,
        "generated_factual_payload_sha256": digest,
    }


def approval_provenance(html: str, metadata: dict | None) -> dict:
    metadata = metadata or {}
    current = hashlib.sha256(html.encode()).hexdigest()
    original = metadata.get("generated_editor_html_sha256")
    unchanged = isinstance(original, str) and original == current
    # An existing model verdict can only describe its original content. This
    # metadata does not itself approve edited facts or replace the review gate.
    return {
        "approved_editor_html_sha256": current,
        "matches_generated_editor_content": unchanged,
        "generation_review_covers_content": unchanged
        and metadata.get("generation_review_available") is True,
        "requires_content_review": not (
            unchanged and metadata.get("generation_review_available") is True
        ),
    }
