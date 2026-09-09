import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import pytest
from fastapi import HTTPException
from app.services.cv_approval_provenance import capture_editor_origin
from app.services.cv_standalone_approval import approve_unchanged_generation


@pytest.mark.parametrize(
    "case", ["verified", "blind", "unverified", "corrupt", "retry"]
)
async def test_standalone_approval_freezes_verified_artifact(case):
    payload = {
        "name": "Jan Secret",
        "position": "Engineer",
        "language": "pl",
        "blind_cv": case == "blind",
    }
    digest = capture_editor_origin("", payload)["generated_factual_payload_sha256"]
    if case != "unverified":
        payload["factual_verification"] = {
            "status": "verified",
            "document_sha256": digest,
        }
    doc = SimpleNamespace(
        id=7,
        status="ready",
        render_payload=payload,
        docx_content=b"exact docx",
        docx_sha256=hashlib.sha256(b"exact docx").hexdigest(),
        filename="cv.docx",
    )
    if case == "corrupt":
        doc.docx_content += b"changed"
    existing = object() if case == "retry" else None
    db = SimpleNamespace(
        scalar=AsyncMock(return_value=existing), add=Mock(), flush=AsyncMock()
    )
    if case in ("corrupt", "unverified"):
        with pytest.raises(HTTPException) as exc:
            await approve_unchanged_generation(db, doc, 9)
        assert exc.value.status_code == 409
        db.add.assert_not_called()
        return
    version = await approve_unchanged_generation(db, doc, 9)
    if case == "retry":
        assert version is existing
        db.add.assert_not_called()
        return
    assert version.generated_owner_id == 7
    assert version.candidate_stage_cv_id is None
    assert version.docx_content == b"exact docx"
    assert (
        version.content_sha256
        == hashlib.sha256(version.content_html.encode()).hexdigest()
    )
    if case == "blind":
        assert "Secret" not in version.content_html
        assert "Jan" not in version.candidate_first_name
