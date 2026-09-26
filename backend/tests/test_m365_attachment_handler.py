"""Unit tests for `app.services.m365.attachment_handler` pure helpers.

Scope: filename/MIME heuristic + a snapshot of the Graph `$select` URL we
build for attachment downloads (Phase 1 fix — no `@odata.type` in $select).
No DB, no network.
"""

from __future__ import annotations

import pytest

from app.services.m365 import attachment_handler
from app.services.m365.attachment_handler import is_cv_candidate_attachment


# ── is_cv_candidate_attachment ───────────────────────────────────────────────


@pytest.mark.parametrize(
    "filename,content_type,expected",
    [
        # Happy paths: CV-ish filenames with document MIME types.
        ("MyCV.pdf", "application/pdf", True),
        ("resume.pdf", "application/pdf", True),
        ("Życiorys_Jana.pdf", "application/pdf", True),
        ("zyciorys.pdf", "application/pdf", True),
        ("Lebenslauf.pdf", "application/pdf", True),
        (
            "Resume_2025.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            True,
        ),
        ("My_CV_final.doc", "application/msword", True),
        # Case-insensitive filename match.
        ("MY_RESUME.PDF", "application/pdf", True),
        # Negative: right MIME, wrong filename.
        ("invoice_2025.pdf", "application/pdf", False),
        ("contract.pdf", "application/pdf", False),
        # Negative: right filename, wrong MIME.
        ("cv.zip", "application/zip", False),
        ("resume.txt", "text/plain", False),
        # Edge: empty filename / None content type.
        ("", "application/pdf", False),
    ],
)
def test_is_cv_candidate_attachment(
    filename: str, content_type: str, expected: bool
) -> None:
    assert is_cv_candidate_attachment(filename, content_type) is expected


# ── Phase 1 regression: @odata.type out of $select ───────────────────────────


def test_attachment_listing_selects_only_base_type_fields() -> None:
    """Regression for Sentry NEXUS-BE-2 AND NEXUS-BE-C + runda 6 audytu.

    `/messages/{id}/attachments` is polymorphic; $select may only name fields
    of the BASE `microsoft.graph.attachment` type — `@odata.type`,
    `contentBytes`, `item`, `sourceUrl` → HTTP 400. Bez $select Graph oddawał
    `contentBytes` wszystkich załączników przy każdej zmianie maila, więc
    lista jest zawężona do pól bazowych, a treść idzie przez `$value`.
    """
    fields = set(attachment_handler._ATTACHMENT_LIST_FIELDS.split(","))
    assert fields <= {
        "id",
        "name",
        "contentType",
        "size",
        "isInline",
        "lastModifiedDateTime",
    }
    assert {"id", "name", "contentType", "size", "isInline"} <= fields
