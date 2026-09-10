"""Bind generation review provenance to exact editor content, not a document ID."""

import copy
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
    blind = generated_payload.get("blind_cv") is True
    identity_terms = [
        generated_payload.get("name"),
        generated_payload.get("first_name"),
    ]
    full_name = generated_payload.get("name")
    if isinstance(full_name, str):
        identity_terms.extend(part for part in full_name.split()[1:] if len(part) >= 3)
    identity_terms.extend(
        role.get("company")
        for role in generated_payload.get("experience", [])
        if isinstance(role, dict)
    )
    rule_present = "client_rule_snapshot" in generated_payload
    rule_snapshot = copy.deepcopy(generated_payload.get("client_rule_snapshot"))
    rule_sha256 = hashlib.sha256(
        json.dumps(
            rule_snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    recorded_rule_sha256 = (generated_payload.get("editorial_provenance") or {}).get(
        "rule_sha256"
    )
    return {
        "client_rule_snapshot": rule_snapshot,
        "client_rule_snapshot_status": "verified"
        if rule_present and recorded_rule_sha256 == rule_sha256
        else "unavailable",
        "client_rule_snapshot_sha256": rule_sha256
        if rule_present and recorded_rule_sha256 == rule_sha256
        else None,
        "blind_identity_guard": blind,
        "blind_identity_terms": list(
            dict.fromkeys(
                term.strip()
                for term in identity_terms
                if blind
                and isinstance(term, str)
                and term.strip()
                and term.strip().casefold() not in {"kandydat", "candidate"}
            )
        ),
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
