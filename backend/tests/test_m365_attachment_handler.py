"""Unit tests for `app.services.m365.attachment_handler` pure helpers.

Scope: filename/MIME heuristic + a snapshot of the Graph `$select` URL we
build for attachment downloads (Phase 1 fix — no `@odata.type` in $select).
No DB, no network.
"""

from __future__ import annotations

import inspect

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


def test_attachment_select_does_not_request_odata_type() -> None:
    """Regression for Sentry NEXUS-BE-2.

    Graph rejects `@odata.type` in `$select`/`$expand` with HTTP 400
    ("Term '@odata.type' is not valid in a $select or $expand expression").
    The discriminator is returned in the response payload automatically, so
    we just snapshot the source to make sure nobody re-adds it to $select.
    """
    src = inspect.getsource(attachment_handler)
    # Find the $select line for attachments and assert no @odata.type.
    select_lines = [
        line.strip()
        for line in src.splitlines()
        if "$select" in line and "contentBytes" in line
    ]
    assert select_lines, "Expected at least one $select for attachment fields"
    for line in select_lines:
        assert "@odata.type" not in line, (
            f"Found @odata.type in $select — Graph will 400. Line: {line}"
        )
