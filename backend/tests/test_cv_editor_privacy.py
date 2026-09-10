from types import SimpleNamespace
from unittest.mock import Mock, AsyncMock
import pytest
from fastapi import HTTPException
from app.services.cv_approval_provenance import capture_editor_origin
from app.services.cv_editor_privacy import check_editor_privacy
from app.services import cv_approval_review


@pytest.mark.parametrize(
    "content",
    [
        "<p>Jan Kowalski</p>",
        "<p>Kowalski</p>",
        "<p>JAN <b>Kowalski</b></p>",
        "<p>Acme Consulting</p>",
    ],
)
async def test_blind_identity_is_rejected_before_fact_review_or_reuse(
    monkeypatch, content
):
    metadata = capture_editor_origin(
        content,
        {
            "blind_cv": True,
            "name": "Jan Kowalski",
            "first_name": "Jan",
            "experience": [{"company": "Acme Consulting"}],
        },
    )
    csv = SimpleNamespace(branded_render_metadata=metadata)
    quota = Mock(side_effect=AssertionError("must not charge"))
    monkeypatch.setattr(cv_approval_review, "ai_feature", quota)
    with pytest.raises(HTTPException) as error:
        await cv_approval_review.review_for_approval(AsyncMock(), csv, content, 7)
    assert error.value.status_code == 422
    assert "Kowalski" not in error.value.detail
    quota.assert_not_called()


def test_standard_identity_and_masked_blind_content_remain_valid():
    payload = {"name": "Jan Kowalski", "experience": [{"company": "Acme"}]}
    check_editor_privacy("<p>Jan Kowalski</p>", capture_editor_origin("", payload))
    payload["blind_cv"] = True
    check_editor_privacy(
        "<p>Kandydat · Firma z branży finansowej</p>",
        capture_editor_origin("", payload),
    )
