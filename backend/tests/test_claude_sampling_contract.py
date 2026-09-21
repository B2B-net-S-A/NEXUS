"""Inspect the actual SDK HTTP body: extra_body must not bypass model policy."""

import json
import anthropic
import httpx2 as httpx
import pytest
from app.services.claude_client import _sdk_request_kwargs


@pytest.mark.parametrize(
    "model", ["claude-sonnet-5", "claude-opus-4-7", "claude-opus-4-8", "claude-opus-5"]
)
def test_unsupported_sampling_never_reaches_sdk_transport(model):
    seen = []

    def handle(request):
        seen.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "msg_test",
                "type": "message",
                "role": "assistant",
                "model": model,
                "content": [{"type": "text", "text": "{}"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        )

    kwargs = {
        "temperature": 0,
        "top_p": 0.5,
        "extra_body": {"top_k": 4, "temperature": 0.2},
    }
    client = anthropic.Anthropic(
        api_key="test", http_client=httpx.Client(transport=httpx.MockTransport(handle))
    )
    client.messages.create(
        model=model,
        max_tokens=10,
        messages=[{"role": "user", "content": "synthetic"}],
        **_sdk_request_kwargs(kwargs, model=model),
    )
    assert not {"temperature", "top_p", "top_k"} & seen[0].keys()
    assert kwargs["extra_body"]["temperature"] == 0.2


def test_supported_model_retains_sampling_and_extra_body_precedence():
    assert _sdk_request_kwargs(
        {"temperature": 0, "extra_body": {"temperature": 0.3, "metadata": {"x": 1}}},
        model="claude-haiku-4-5",
    ) == {"extra_body": {"temperature": 0.3, "metadata": {"x": 1}}}
