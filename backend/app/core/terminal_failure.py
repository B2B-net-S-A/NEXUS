"""Report one completed operation, preserving the original exception stack."""

from contextvars import ContextVar
from functools import wraps
from uuid import uuid4

import sentry_sdk
from sentry_sdk.utils import event_from_exception

from app.core.request_correlation import correlation_ids

_operation: ContextVar[dict | None] = ContextVar("sentry_operation", default=None)


def capture_terminal_failure(
    exc: Exception, *, operation: str, failure_kind: str
) -> None:
    state = _operation.get()
    if state and state["reported"]:
        return
    if state:
        state["reported"] = True
    # Prevent later logger.exception/ASGI handling from reporting the same error
    # after the final operation event has already retained its stack.
    exc._nexus_terminal_reported = True
    with sentry_sdk.new_scope() as scope:
        scope.set_tag("operation", operation)
        scope.set_tag("failure_kind", failure_kind)
        scope.set_tag("terminal", "true")
        scope.set_tag("sampling_policy", "all-terminal-operations")
        # Treść wyjątku jest czyszczona (prywatność), więc bez tego tagu nie
        # widać, że np. DeepSeek odmawia 402 „brak środków" (25.09.2026).
        status = getattr(exc, "status_code", None)
        if isinstance(status, int):
            scope.set_tag("http.status_code", str(status))
        # The SDK may already have seen this object on a retried provider attempt.
        # Serialize its original stack, then omit exc_info so SDK object-identity
        # deduplication cannot discard the terminal event after a filtered attempt.
        event, _ = event_from_exception(
            exc,
            client_options=sentry_sdk.get_client().options,
            mechanism={"type": "nexus.operation", "handled": True},
        )
        sentry_sdk.capture_event(event)


def terminal_operation(name: str):
    """Async operation boundary: intermediate captures remain breadcrumbs only."""

    def decorate(function):
        @wraps(function)
        async def wrapped(*args, **kwargs):
            token = _operation.set({"reported": False})
            try:
                with sentry_sdk.new_scope() as scope:
                    scope.set_tag("operation", name)
                    scope.set_tag("terminal", "false")
                    scope.set_tag("sampling_policy", "operation-in-progress")
                    # Preserve the request correlation; background jobs also get
                    # their own operation UUID independent of Sentry grouping.
                    existing = correlation_ids.get() or {}
                    scope.set_context(
                        "correlation", {"operation_id": str(uuid4()), **existing}
                    )
                    try:
                        return await function(*args, **kwargs)
                    except Exception as exc:
                        capture_terminal_failure(
                            exc, operation=name, failure_kind=type(exc).__name__
                        )
                        raise
            finally:
                _operation.reset(token)

        return wrapped

    return decorate
