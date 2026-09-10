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
