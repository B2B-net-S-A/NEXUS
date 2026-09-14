"""Per-request correlation without trusting caller-supplied private values."""

from uuid import UUID, uuid4

import sentry_sdk


class RequestCorrelationMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request_id = str(uuid4())
        headers = dict(scope.get("headers", []))
        try:
            operation_id = str(
                UUID(headers.get(b"x-operation-id", b"").decode("ascii"))
            )
        except (ValueError, UnicodeError):
            operation_id = request_id
        scope.setdefault("state", {}).update(
            request_id=request_id, operation_id=operation_id
        )

        async def send_correlated(message):
            if message["type"] == "http.response.start":
                message = {
                    **message,
                    "headers": [
                        *message.get("headers", []),
                        (b"x-request-id", request_id.encode()),
                    ],
                }
            await send(message)

        with sentry_sdk.isolation_scope() as context:
            context.set_context(
                "correlation", {"request_id": request_id, "operation_id": operation_id}
            )
            await self.app(scope, receive, send_correlated)
