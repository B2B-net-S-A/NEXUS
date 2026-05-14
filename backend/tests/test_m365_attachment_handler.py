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


def test_attachment_download_uses_no_select() -> None:
    """Regression for Sentry NEXUS-BE-2 AND NEXUS-BE-C.

    The `/messages/{id}/attachments` endpoint returns a polymorphic collection
    (fileAttachment / itemAttachment / referenceAttachment). Graph's $select
    only accepts fields that exist on the BASE `microsoft.graph.attachment`
    type, so any subtype-specific field (`@odata.type`, `contentBytes`, `item`,
    `sourceUrl`) triggers HTTP 400:
      • NEXUS-BE-2: `@odata.type` in $select.
      • NEXUS-BE-C: `contentBytes` in $select (only on fileAttachment).

    Cheapest robust fix: drop $select entirely. Graph returns each subtype's
    full payload including its discriminator and (for fileAttachment) the
    inline `contentBytes`. This test snapshots the source to make sure nobody
    re-introduces a $select with subtype-specific fields here.
    """
    src = inspect.getsource(attachment_handler.download_for_email)
    # Only catch actual usage — `"$select":` or `'$select':` as a dict key.
    # Plain mentions of "$select" in comments/docstrings (explaining WHY we
    # don't use it) are fine and would otherwise false-positive this check.
    assert '"$select":' not in src and "'$select':" not in src, (
        "download_for_email() must NOT use $select on the polymorphic "
        "attachments endpoint — Graph 400s on any subtype-specific field. "
        "If you need to limit the payload, fetch the list and project in Python."
    )
