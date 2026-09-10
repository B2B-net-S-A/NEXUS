"""Exercise the real SDK SSE accumulator, not a fake messages.create response."""

from contextlib import contextmanager
import json

import anthropic
import httpx
import pytest

from app.services import claude_client as client


def test_cv_stream_accumulates_complete_message_and_usage(monkeypatch):
    events = [
        (
            "message_start",
            {
                "type": "message_start",
                "message": {
                    "id": "msg_test",
                    "type": "message",
                    "role": "assistant",
                    "model": "claude-sonnet-4-6",
                    "content": [],
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {"input_tokens": 30, "output_tokens": 0},
                },
            },
        ),
        (
            "content_block_start",
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "text", "text": ""},
            },
        ),
        (
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": '{"name":"Synthetic"}'},
            },
        ),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        (
            "message_delta",
            {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                "usage": {"output_tokens": 8},
            },
        ),
        ("message_stop", {"type": "message_stop"}),
    ]
    captured = []

    def respond(request):
        assert json.loads(request.content)["stream"] is True
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content="".join(
                f"event: {kind}\ndata: {json.dumps(data)}\n\n" for kind, data in events
            ),
        )

    sdk = anthropic.Anthropic(
        api_key="synthetic",
        http_client=httpx.Client(transport=httpx.MockTransport(respond)),
        max_retries=0,
    )
    monkeypatch.setattr(client.anthropic, "Anthropic", lambda **kw: sdk)
    monkeypatch.setattr(client, "_assert_declared", lambda *a: None)
    monkeypatch.setattr(
        client, "_record_tokens", lambda message, **kw: captured.append(message.usage)
    )
    result = client.call_claude_text(
        messages=[{"role": "user", "content": "test"}],
        model="claude-sonnet-4-6",
        max_tokens=100,
        api_key="synthetic",
        stream_response=True,
        total_timeout=300,
    )
    assert result == '{"name":"Synthetic"}'
    assert captured[0].input_tokens == 30 and captured[0].output_tokens == 8
    sdk.close()


def test_stream_deadline_closes_partial_response_without_retry(monkeypatch):
    clock = [0.0]
    closed, calls = [], []

    class Stream:
        def __iter__(self):
            clock[0] = 301.0
            yield object()

        def get_final_message(self):
            raise AssertionError("partial response cannot become a CV")

    class Messages:
        @contextmanager
        def stream(self, **kw):
            calls.append(kw)
            try:
                yield Stream()
            finally:
                closed.append(True)

    monkeypatch.setattr(client.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        client.anthropic,
        "Anthropic",
        lambda **kw: type("SDK", (), {"messages": Messages()})(),
    )
    monkeypatch.setattr(client, "_assert_declared", lambda *a: None)
    with pytest.raises(client.ClaudeDeadlineExceeded):
        client.call_claude(
            messages=[{"role": "user", "content": "test"}],
            model="a",
            fallback_models=["b"],
            max_tokens=100,
            api_key="synthetic",
            max_retries=3,
            stream_response=True,
            total_timeout=300,
        )
    assert closed == [True] and len(calls) == 1
