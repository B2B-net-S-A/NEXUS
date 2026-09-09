"""Bind generation review provenance to exact editor content, not a document ID."""

import hashlib


def capture_editor_origin(html: str, generation_review: dict | None) -> dict:
    return {
        "generated_editor_html_sha256": hashlib.sha256(html.encode()).hexdigest(),
        "generation_review_available": isinstance(generation_review, dict)
        and generation_review.get("status") == "verified",
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
