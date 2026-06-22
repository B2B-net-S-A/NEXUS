"""Unit tests for the Sentry ``before_send`` Anthropic-noise filter.

In-process — no network, no DB, no Sentry SDK. The filter is a pure function
over the (event, hint) dicts Sentry passes it, so we exercise it with
duck-typed fakes that match the shape of ``anthropic`` SDK exceptions and the
integration-built event payloads.
"""

from __future__ import annotations

from app.main import _is_transient_anthropic_exc, _sentry_before_send


class _FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class _FakeAnthropicError(Exception):
    """Mimics ``anthropic.APIStatusError``: ``status_code`` + ``body.error.type``."""

    def __init__(
        self,
        status_code: int | None = None,
        err_type: str | None = None,
        *,
        on_response: bool = False,
    ) -> None:
        super().__init__("boom")
        if status_code is not None and not on_response:
            self.status_code = status_code
        if status_code is not None and on_response:
            self.response = _FakeResponse(status_code)
        if err_type is not None:
            self.body = {"error": {"type": err_type}}


def _anthropic_event() -> dict:
    """Event payload as the AnthropicIntegration would build it."""
    return {"exception": {"values": [{"mechanism": {"type": "anthropic"}}]}}


def _app_event() -> dict:
    """Event payload for an error raised by our own (non-anthropic) code path."""
    return {"exception": {"values": [{"mechanism": {"type": "generic"}}]}}


class TestIsTransientAnthropicExc:
    def test_529_overloaded_status_is_transient(self):
        assert _is_transient_anthropic_exc(_FakeAnthropicError(status_code=529))

    def test_429_rate_limit_status_is_transient(self):
        assert _is_transient_anthropic_exc(_FakeAnthropicError(status_code=429))

    def test_status_on_response_attribute_is_detected(self):
        assert _is_transient_anthropic_exc(
            _FakeAnthropicError(status_code=529, on_response=True)
        )

    def test_overloaded_error_type_is_transient(self):
        assert _is_transient_anthropic_exc(
            _FakeAnthropicError(err_type="overloaded_error")
        )

    def test_rate_limit_error_type_is_transient(self):
        assert _is_transient_anthropic_exc(
            _FakeAnthropicError(err_type="rate_limit_error")
        )

    def test_500_server_error_is_not_classified_transient(self):
        # 5xx is retried by ai_client, but is NOT dropped from Sentry — a
        # sustained server error is worth surfacing.
        assert not _is_transient_anthropic_exc(_FakeAnthropicError(status_code=500))

    def test_400_bad_request_is_not_transient(self):
        assert not _is_transient_anthropic_exc(_FakeAnthropicError(status_code=400))

    def test_plain_exception_is_not_transient(self):
        assert not _is_transient_anthropic_exc(ValueError("nope"))


class TestSentryBeforeSend:
    def test_drops_transient_anthropic_mechanism_event(self):
        hint = {"exc_info": (None, _FakeAnthropicError(status_code=529), None)}
        assert _sentry_before_send(_anthropic_event(), hint) is None

    def test_keeps_transient_error_without_anthropic_mechanism(self):
        # Same transient exc, but raised by our own code → keep it.
        event = _app_event()
        hint = {"exc_info": (None, _FakeAnthropicError(status_code=529), None)}
        assert _sentry_before_send(event, hint) is event

    def test_keeps_non_transient_anthropic_event(self):
        event = _anthropic_event()
        hint = {"exc_info": (None, _FakeAnthropicError(status_code=500), None)}
        assert _sentry_before_send(event, hint) is event

    def test_keeps_event_without_exc_info(self):
        # The exhausted-retries logger.error() event has no exc_info → survives.
        event = _anthropic_event()
        assert _sentry_before_send(event, {}) is event

    def test_keeps_event_with_empty_hint(self):
        event = _app_event()
        assert _sentry_before_send(event, None) is event
