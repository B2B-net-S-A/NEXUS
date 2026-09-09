import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import pytest
from app.services.cv_document_assets import approved_assets, CvAssetsError
from app.services import cv_generated_editor


def version():
    return SimpleNamespace(
        version=2,
        content_html="<p>Approved</p>",
        language="en",
        template="blind",
        template_content=b"saved template",
        consent_content=b"saved consent",
        render_metadata={
            "template_sha256": hashlib.sha256(b"saved template").hexdigest(),
            "consent_sha256": hashlib.sha256(b"saved consent").hexdigest(),
        },
    )


@pytest.mark.parametrize("field", [None, "template_content", "consent_content"])
def test_only_intact_saved_assets_are_accepted(field):
    approved = version()
    if field:
        setattr(approved, field, b"changed")
        with pytest.raises(CvAssetsError):
            approved_assets(approved)
    else:
        template, consent, metadata = approved_assets(approved)
        assert template == b"saved template" and consent == b"saved consent"
        metadata["extra"] = True
        assert "extra" not in approved.render_metadata


async def test_reopening_approval_does_not_load_live_assets(monkeypatch):
    live = Mock(side_effect=AssertionError("live storage/template must not be read"))
    monkeypatch.setattr(cv_generated_editor, "generated_assets", live)
    db = SimpleNamespace(
        scalar=AsyncMock(side_effect=[None, version()]), add=Mock(), flush=AsyncMock()
    )
    generated = SimpleNamespace(
        id=7, status="ready", render_payload={"language": "pl"}, filename="cv.docx"
    )
    draft = await cv_generated_editor.load_draft(db, generated)
    assert draft.branded_status == "finalized"
    assert draft.branded_version == 2
    assert draft.branded_draft_html == "<p>Approved</p>"
    assert draft.branded_template_content == b"saved template"
    assert draft.branded_consent_content == b"saved consent"
    assert draft.branded_language == "en" and draft.branded_template == "blind"
    live.assert_not_called()
