"""Exercise the real SDK SSE accumulator, not a fake messages.create response.

The SDK's HTTP layer is ``httpx2`` since anthropic 1.0: an ``httpx.Client``
handed to ``Anthropic(http_client=...)`` is rejected with ``TypeError`` at
construction, so the mock transport has to come from ``httpx2`` too.
"""

from contextlib import contextmanager
import json

import anthropic
import httpx2
import pytest

from app.services import claude_client as client


def _json_message(events):
    """The same exchange as a plain (non-streaming) ``messages.create`` body."""
    message = dict(next(d["message"] for k, d in events if k == "message_start"))
    message["content"] = [
        {
            "type": "text",
            "text": "".join(
                d["delta"]["text"] for k, d in events if k == "content_block_delta"
            ),
        }
    ]
    for kind, data in events:
        if kind == "message_delta":
            message.update(data["delta"])
            message["usage"] = {**message["usage"], **data["usage"]}
    return message


def _sdk_over(events, captured_requests=None):
    def respond(request):
        body = json.loads(request.content)
        if captured_requests is not None:
            captured_requests.append(body)
        if not body.get("stream"):
            return httpx2.Response(200, json=_json_message(events))
        return httpx2.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content="".join(
                f"event: {kind}\ndata: {json.dumps(data)}\n\n" for kind, data in events
            ),
        )

    return anthropic.Anthropic(
        api_key="synthetic",
        http_client=httpx2.Client(transport=httpx2.MockTransport(respond)),
        max_retries=0,
    )


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
    captured, requests = [], []
    sdk = _sdk_over(events, requests)
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
    assert requests[0]["stream"] is True
    assert captured[0].input_tokens == 30 and captured[0].output_tokens == 8
    sdk.close()


def test_sampling_params_reach_the_wire_through_extra_body(monkeypatch):
    """anthropic 1.x removed ``temperature``/``top_p``/``top_k`` from the
    ``messages.create()``/``stream()`` signatures (TypeError), while the API
    still honours them. The champion parser and the notes extractor pin
    ``temperature=0``; the provider boundary must keep that on the wire
    instead of letting every call blow up. A fake client could not catch this
    — only the real SDK signature can."""
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
                    "usage": {"input_tokens": 3, "output_tokens": 0},
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
                "delta": {"type": "text_delta", "text": "ok"},
            },
        ),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        (
            "message_delta",
            {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                "usage": {"output_tokens": 1},
            },
        ),
        ("message_stop", {"type": "message_stop"}),
    ]
    requests = []
    sdk = _sdk_over(events, requests)
    monkeypatch.setattr(client.anthropic, "Anthropic", lambda **kw: sdk)
    monkeypatch.setattr(client, "_assert_declared", lambda *a: None)
    monkeypatch.setattr(client, "_record_tokens", lambda message, **kw: None)
    common = dict(
        messages=[{"role": "user", "content": "test"}],
        model="claude-sonnet-4-6",
        max_tokens=100,
        api_key="synthetic",
        temperature=0,
        top_k=5,
        extra_body={"top_k": 7, "metadata": {"user_id": "u"}},
    )
    assert client.call_claude_text(**common, stream_response=True) == "ok"
    assert client.call_claude_text(**common) == "ok"
    for body in requests:
        # caller's explicit extra_body wins on a colliding key; the rest is
        # merged into the request JSON exactly as the SDK migration guide says
        assert body["temperature"] == 0 and body["top_k"] == 7
        assert body["metadata"] == {"user_id": "u"}
        assert body["thinking"] == {"type": "disabled"}
    assert [b.get("stream") for b in requests] == [True, None]
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
