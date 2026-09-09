import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import pytest
from app.services.cv_document_assets import approved_assets, CvAssetsError
from app.services import cv_generated_editor


@pytest.mark.parametrize("changed", [False, True])
def test_generation_assets_reject_template_drift_before_editing(monkeypatch, changed):
    from app.services import cv_document_assets

    monkeypatch.setattr(
        cv_document_assets,
        "default_template",
        lambda: b"changed" if changed else b"original",
    )
    generated = SimpleNamespace(
        id=7,
        client_id=None,
        client_rule_version=None,
        render_payload={
            "artifact_provenance": {
                "template_sha256": hashlib.sha256(b"original").hexdigest(),
            }
        },
    )
    if changed:
        with pytest.raises(CvAssetsError, match="Szablon zmienił"):
            cv_document_assets.generated_assets(generated)
    else:
        template, consent, metadata = cv_document_assets.generated_assets(generated)
        assert template == b"original" and consent is None
        assert metadata["template_sha256"] == hashlib.sha256(template).hexdigest()


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


@pytest.mark.parametrize("corrupt", [False, True])
def test_saved_consent_is_verified_without_storage(monkeypatch, corrupt):
    from app.services import cv_document_assets, object_storage

    unavailable = Mock(side_effect=OSError("storage unavailable"))
    monkeypatch.setattr(object_storage, "download_cv", unavailable)
    generated = SimpleNamespace(
        id=7,
        client_id=None,
        client_rule_version=None,
        template_content=b"template",
        consent_content=b"changed" if corrupt else b"original image",
        render_payload={
            "consent_screenshot": {"storage_key": "deleted-key"},
            "artifact_provenance": {
                "template_sha256": hashlib.sha256(b"template").hexdigest(),
                "consent_sha256": hashlib.sha256(b"original image").hexdigest(),
            },
        },
    )
    if corrupt:
        with pytest.raises(CvAssetsError, match="załącznika zgody"):
            cv_document_assets.generated_assets(generated)
    else:
        assert cv_document_assets.generated_assets(generated)[1] == b"original image"
    unavailable.assert_not_called()


def test_saved_generation_template_survives_live_template_change(monkeypatch):
    from app.services import cv_document_assets

    live = Mock(side_effect=AssertionError("must use the saved template"))
    monkeypatch.setattr(cv_document_assets, "default_template", live)
    generated = SimpleNamespace(
        id=7,
        client_id=None,
        client_rule_version=None,
        template_content=b"original",
        render_payload={
            "artifact_provenance": {
                "template_sha256": hashlib.sha256(b"original").hexdigest(),
            }
        },
    )
    assert cv_document_assets.generated_assets(generated)[0] == b"original"
    live.assert_not_called()


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
