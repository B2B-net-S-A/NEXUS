"""Per-request correlation without trusting caller-supplied private values."""

from dataclasses import dataclass
from uuid import UUID, uuid4
from contextvars import ContextVar
import logging
import time

import sentry_sdk


correlation_ids: ContextVar[dict | None] = ContextVar(
    "request_correlation", default=None
)


@dataclass
class RequestDbUsage:
    """Zapytania jednego żądania. `seconds` obejmuje też kolejkę w pętli zdarzeń."""

    statements: int = 0
    seconds: float = 0.0

    def finished(self, seconds: float) -> None:
        self.statements += 1
        self.seconds += seconds

    def rounded_ms(self) -> float:
        return round(self.seconds * 1000, 2)


# Obiekt, nie liczby: zadania potomne dostają kopię kontekstu, ale ten sam licznik.
request_db_usage: ContextVar[RequestDbUsage | None] = ContextVar(
    "request_db_usage", default=None
)


class RequestCorrelationMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        started = time.monotonic()
        status_code = 500
        # Koniec odpowiedzi = ostatni kawałek ciała. Starlette wykonuje
        # `BackgroundTasks` PO nim, ale wciąż wewnątrz tego wywołania.
        response_done: tuple[float, int, float] | None = None
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
            nonlocal status_code, response_done
            if message["type"] == "http.response.body" and not message.get(
                "more_body", False
            ):
                response_done = (
                    time.monotonic(),
                    db_usage.statements,
                    db_usage.seconds,
                )
            if message["type"] == "http.response.start":
                status_code = message["status"]
                message = {
                    **message,
                    "headers": [
                        *message.get("headers", []),
                        (b"x-request-id", request_id.encode()),
                    ],
                }
            await send(message)

        correlation_token = correlation_ids.set(
            {"request_id": request_id, "operation_id": operation_id}
        )
        db_usage = RequestDbUsage()
        db_usage_token = request_db_usage.set(db_usage)
        with sentry_sdk.isolation_scope() as context:
            context.set_context(
                "correlation", {"request_id": request_id, "operation_id": operation_id}
            )

            def tag_request_failure(event, hint):
                tags = event.setdefault("tags", {})
                if (
                    tags.get("sampling_policy") != "operation-in-progress"
                    and event.get("type") != "transaction"
                ):
                    route = getattr(scope.get("route"), "path", "unmatched-route")
                    tags.setdefault(
                        "operation", f"{scope.get('method', 'UNKNOWN')} {route}"
                    )
                    tags.setdefault("terminal", "true")
                    tags.setdefault("failure_kind", "request_failure")
                    tags.setdefault("sampling_policy", "all-terminal-requests")
                slug = _service_slug(scope)
                if slug:
                    # Tag dozwolony przez `sentry_privacy` (slug, nie id klucza).
                    tags.setdefault("integration", slug)
                return event

            context.add_event_processor(tag_request_failure)
            try:
                await self.app(scope, receive, send_correlated)
            finally:
                correlation_ids.reset(correlation_token)
                request_db_usage.reset(db_usage_token)
                route = getattr(scope.get("route"), "path", "unmatched-route")
                finished = time.monotonic()
                extra = {
                    "event_kind": "http_outcome",
                    "route": route,
                    "method": scope.get("method", "UNKNOWN"),
                    "status_code": status_code,
                    **_timing_fields(started, finished, response_done, db_usage),
                    "request_id": request_id,
                    "operation_id": operation_id,
                }
                slug = _service_slug(scope)
                if slug:
                    # API integracyjne v1 (0443): które konto serwisowe wołało.
                    extra["actor"] = f"service_account:{slug}"
                logging.getLogger(__name__).info("http_outcome", extra=extra)


# Praca po odpowiedzi krótsza niż to i bez zapytań to narzut middleware'u, nie
# zadanie w tle — linia logu zostaje wtedy w dawnym kształcie.
_BACKGROUND_MS_FLOOR = 100.0


def _timing_fields(
    started: float,
    finished: float,
    response_done: tuple[float, int, float] | None,
    db_usage: RequestDbUsage,
) -> dict:
    """`duration_ms` i `db_*` do końca odpowiedzi, `background_*` po niej.

    18.11.2026: odczyt CV w `BackgroundTasks` (ekstrakcja, model, wektor)
    wliczał się w `duration_ms` trasy — `POST /api/candidates/{id}/cv` miał
    p50 18 s, choć klient dostawał odpowiedź wcześniej, a ranking wolnych tras
    mieszał czas czekania ludzi z pracą procesu po odpowiedzi.
    """
    if response_done is None:
        # Bez ciała odpowiedzi (rozłączenie, błąd przed wysłaniem): cały czas.
        return {
            "duration_ms": round((finished - started) * 1000, 2),
            "db_statements": db_usage.statements,
            "db_ms": db_usage.rounded_ms(),
        }
    done_at, statements, db_seconds = response_done
    fields: dict = {
        "duration_ms": round((done_at - started) * 1000, 2),
        "db_statements": statements,
        "db_ms": round(db_seconds * 1000, 2),
    }
    background_ms = (finished - done_at) * 1000
    background_statements = db_usage.statements - statements
    if background_ms >= _BACKGROUND_MS_FLOOR or background_statements:
        fields["background_ms"] = round(background_ms, 2)
        fields["background_db_statements"] = background_statements
        fields["background_db_ms"] = round((db_usage.seconds - db_seconds) * 1000, 2)
    return fields


def _service_slug(scope) -> str | None:
    """Slug konta serwisowego uwierzytelnionego kluczem w tym żądaniu."""
    principal = (scope.get("state") or {}).get("service_principal")
    return getattr(principal, "slug", None) or None
