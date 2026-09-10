from types import SimpleNamespace

import pytest

from app.services.cv_editor_review import EditorReviewInputError
from app.services.cv_generator_b2b.interactive_chat import approved_chat_context


def test_chat_projection_uses_only_approved_paragraphs():
    version = SimpleNamespace(
        language="pl",
        content_html="<h2>Doświadczenie</h2><p>Testy <b>AWS</b> tylko szkoleniowo.</p><p>Bez produkcji.</p>",
        job_title="Removed role",
        render_metadata={"source": "Private notes"},
    )
    result = approved_chat_context(version)
    assert result == {
        "language": "pl",
        "approved_content": ["Testy AWS tylko szkoleniowo.", "Bez produkcji."],
    }
    assert "Removed" not in str(result)
    assert "Private" not in str(result)


@pytest.mark.parametrize("html", ["", '<img src="source.png">'])
def test_unprojectable_approval_cannot_fall_back_to_original_cv(html):
    with pytest.raises(EditorReviewInputError):
        approved_chat_context(SimpleNamespace(language="pl", content_html=html))


async def test_model_prompt_cannot_read_original_payload_for_approved_link(monkeypatch):
    from unittest.mock import AsyncMock
    from app.services.cv_generator_b2b import interactive_chat as chat

    class OriginalMustNotBeRead:
        @property
        def render_payload(self):
            raise AssertionError("superseded CV leaked")

        @property
        def requirement_map(self):
            raise AssertionError("superseded requirements leaked")

    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-test-key")
    monkeypatch.setattr(chat, "_history", AsyncMock(return_value=[]))
    monkeypatch.setattr(chat, "_persist_exchange", AsyncMock())
    provider = AsyncMock(
        return_value=SimpleNamespace(
            content=[SimpleNamespace(text="Tylko szkoleniowo.")]
        )
    )
    monkeypatch.setattr(chat, "run_in_threadpool", provider)
    context = approved_chat_context(
        SimpleNamespace(language="pl", content_html="<p>AWS wyłącznie szkoleniowo.</p>")
    )
    answer = await chat._answer_with_model(
        object(),
        SimpleNamespace(token="synthetic-link"),
        OriginalMustNotBeRead(),
        "Jakie doświadczenie AWS?",
        approved_context=context,
    )
    assert answer == "Tylko szkoleniowo."
    assert "AWS wyłącznie szkoleniowo." in provider.call_args.kwargs["system"]


async def test_pinned_link_requires_approved_context_before_quota():
    from app.services.cv_generator_b2b import interactive_chat as chat

    with pytest.raises(chat.CvChatLLMError, match="approved context required"):
        await chat.answer_question(
            object(),
            token_row=SimpleNamespace(document_version_id=12),
            doc_row=object(),
            question="Doświadczenie?",
        )


@pytest.mark.parametrize("case", ["approved", "corrupt", "image", "disabled", "legacy"])
async def test_public_question_uses_exact_approval_before_calling_chat(
    monkeypatch, case
):
    from unittest.mock import AsyncMock
    from fastapi import HTTPException, Request, Response
    from app.api import public_share as api
    from app.services import cv_generated_approval as approval
    from app.services.cv_generator_b2b import interactive_chat as chat

    doc = SimpleNamespace(
        status="ready", mode="upload", render_payload={"name": "Old content"}
    )
    row = SimpleNamespace(
        document_version_id=None if case == "legacy" else 71, generated_document=doc
    )
    monkeypatch.setattr(api, "_load_generated_share", AsyncMock(return_value=row))
    monkeypatch.setattr(
        api, "_interactive_flags", AsyncMock(return_value=(True, case != "disabled"))
    )
    resolver = AsyncMock(
        return_value=SimpleNamespace(
            language="pl",
            content_html='<img src="x">' if case == "image" else "<p>Approved only</p>",
        )
    )
    if case == "corrupt":
        resolver.side_effect = HTTPException(409, "integrity failure")
    monkeypatch.setattr(approval, "approved_version_for_generation", resolver)
    answer = AsyncMock(return_value="Odpowiedź")
    monkeypatch.setattr(chat, "answer_question", answer)
    db = object()
    request = Request({"type": "http", "method": "POST", "path": "/"})

    async def invoke():
        return await api.post_public_generated_cv_chat.__wrapped__(
            "synthetic",
            request,
            api.PublicCvChatRequest(question="Doświadczenie?"),
            Response(),
            db,
        )

    if case in {"corrupt", "image", "disabled"}:
        with pytest.raises(HTTPException) as caught:
            await invoke()
        assert caught.value.status_code == (404 if case == "disabled" else 409)
        answer.assert_not_awaited()
    else:
        await invoke()
        assert answer.call_args.kwargs["approved_context"] == (
            None
            if case == "legacy"
            else {"language": "pl", "approved_content": ["Approved only"]}
        )
    if case == "legacy":
        resolver.assert_not_awaited()
    else:
        resolver.assert_awaited_once_with(db, doc, 71)


@pytest.mark.parametrize("enabled", [False, True])
async def test_approved_interactivity_does_not_require_obsolete_generated_map(
    monkeypatch, enabled
):
    from unittest.mock import AsyncMock
    from app.api.public_share import _interactive_flags
    from app.services.cv_generator_b2b import document_policy
    from app.services import ai_quota

    db = AsyncMock()
    doc = SimpleNamespace(mode="upload", job_id=None, requirement_map=None)
    monkeypatch.setattr(
        document_policy, "interactive_client_enabled", AsyncMock(return_value=enabled)
    )
    monkeypatch.setattr(ai_quota, "get_master_enabled", AsyncMock(return_value=True))
    monkeypatch.setattr(
        ai_quota,
        "get_feature_config",
        AsyncMock(return_value=SimpleNamespace(enabled=True)),
    )
    assert await _interactive_flags(db, doc, approved_version=True) == (
        enabled,
        enabled,
    )
    assert await _interactive_flags(db, doc) == (False, False)
