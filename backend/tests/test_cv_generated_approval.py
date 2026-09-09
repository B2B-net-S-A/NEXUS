import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.services.cv_generated_approval import approved_version_for_generation


@pytest.mark.parametrize(
    "case",
    ["valid", "missing", "corrupt_html", "corrupt_docx", "no_artifact", "unassigned"],
)
async def test_only_exact_associated_intact_version_can_be_selected(case):
    generated = SimpleNamespace(
        id=7, candidate_id=None if case == "unassigned" else 2, job_id=3
    )
    version = SimpleNamespace(
        content_html="<p>Approved</p>",
        docx_content=b"approved",
        content_sha256=hashlib.sha256(b"<p>Approved</p>").hexdigest(),
        docx_sha256=hashlib.sha256(b"approved").hexdigest(),
    )
    if case == "corrupt_html":
        version.content_html += "changed"
    if case == "corrupt_docx":
        version.docx_content += b"changed"
    if case == "no_artifact":
        version.docx_content = None
    db = SimpleNamespace(
        scalar=AsyncMock(return_value=None if case == "missing" else version)
    )
    if case == "valid":
        assert await approved_version_for_generation(db, generated, 12) is version
    else:
        with pytest.raises(HTTPException) as error:
            await approved_version_for_generation(db, generated, 12)
        assert error.value.status_code == (404 if case == "missing" else 409)
    if case == "unassigned":
        db.scalar.assert_not_awaited()
    else:
        sql = str(db.scalar.call_args.args[0].compile())
        assert "generated_document_id =" in sql
        assert "candidate_id =" in sql
        assert "job_id =" in sql
        assert "cv_document_versions.id =" in sql
