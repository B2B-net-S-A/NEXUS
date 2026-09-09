from app.services.cv_approval_provenance import (
    capture_editor_origin,
    approval_provenance,
)


def test_edited_claim_does_not_inherit_generation_verdict():
    original = "<p>3 lata doświadczenia</p>"
    metadata = capture_editor_origin(original, {"version": 2, "status": "verified"})
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
